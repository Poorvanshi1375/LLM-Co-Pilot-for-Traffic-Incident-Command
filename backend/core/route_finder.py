"""
Route Finder — diverse shortest paths on the shared Brooklyn road graph.
Priority routing for emergency vehicles, weather-aware edge weighting,
live congestion from the feed, and routes coloured by their actual risk.

Edge costs are computed per request through a weight function and a local
memo; the shared graph is never written, so concurrent requests are safe.
"""
from __future__ import annotations

from math import radians, sin, cos, sqrt, atan2
from typing import Callable, Optional

import networkx as nx

from core.road_graph import get_graph, nearest_node, nodes_within, street_name

# Vehicle type speed/risk multipliers
# Emergency vehicles: travel faster, accept more risk
VEHICLE_PROFILES = {
    "normal":       {"speed_mult": 1.0, "risk_tolerance": 1.0},
    "ambulance":    {"speed_mult": 1.4, "risk_tolerance": 0.5},
    "police":       {"speed_mult": 1.3, "risk_tolerance": 0.6},
    "fire_brigade": {"speed_mult": 1.2, "risk_tolerance": 0.4},
}

DIVERSITY_PENALTY = 5.0  # cost multiplier on edges already used by an earlier route

# Route colour reflects the route's average risk relative to the whole network
# right now (percentile of live segment risk), not its rank: a fixed cut-off
# turns every route red at rush hour, when all risk scores rise together.
RISK_COLORS = {"low": "#10B981", "moderate": "#F59E0B", "high": "#EF4444"}
LOW_PCT, HIGH_PCT = 0.40, 0.75


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def _get_speed_limit(data: dict) -> float:
    """Extract speed limit in mph from edge data."""
    maxspeed = data.get("maxspeed", "25")
    if isinstance(maxspeed, list):
        maxspeed = maxspeed[0]
    try:
        return float(str(maxspeed).replace(" mph", ""))
    except (ValueError, TypeError):
        return 25.0


def _as_dict(item) -> dict | None:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return item if isinstance(item, dict) else None


class EdgeCosts:
    """Per-request edge metrics from live feed, risk and weather (memoised)."""

    def __init__(
        self,
        feed_snapshot: Optional[list] = None,
        risk_map: Optional[list] = None,
        vehicle_type: str = "normal",
        weather_condition: Optional[str] = None,
    ):
        self.feed = {d["segment_id"]: d for d in map(_as_dict, feed_snapshot or []) if d}
        self.risk = {d["segment_id"]: d for d in map(_as_dict, risk_map or []) if d}
        self.profile = VEHICLE_PROFILES.get(vehicle_type, VEHICLE_PROFILES["normal"])
        self.weather_fn: Callable[[str], float] | None = None
        if weather_condition and weather_condition not in ("clear", "partly_cloudy"):
            from core.weather_service import get_weather_penalty
            self.weather_fn = lambda name: get_weather_penalty(name, weather_condition)
        self._memo: dict[tuple, tuple] = {}

    def metrics(self, u, v, data: dict) -> tuple[float, float, float, float]:
        """(minutes, risk, density, weather_penalty) for one edge."""
        key = (u, v)
        if key in self._memo:
            return self._memo[key]
        speed_limit = _get_speed_limit(data)
        seg = self.feed.get(data.get("seg", ""))
        # Apply the nearest segment's congestion ratio to this edge's own limit
        if seg and seg.get("free_flow_speed", 0) > 0:
            congestion = max(0.05, seg["speed"] / seg["free_flow_speed"])
        else:
            congestion = 1.0
        speed = max(speed_limit * congestion * self.profile["speed_mult"], 3.0)
        minutes = (data.get("length", 100.0) / 1609.34) / speed * 60.0
        risk = self.risk.get(data.get("seg", ""), {}).get("score", 0.1)
        density = seg.get("density", 0.0) if seg else 0.0
        weather = self.weather_fn(street_name(data)) if self.weather_fn else 1.0
        result = (minutes, risk, density, weather)
        self._memo[key] = result
        return result

    def risk_level(self, route_risk: float) -> str:
        """low / moderate / high against the live network's risk distribution."""
        scores = sorted(r.get("score", 0.1) for r in self.risk.values())
        if not scores:
            return "low"
        below = sum(1 for x in scores if x < route_risk) / len(scores)
        if below < LOW_PCT:
            return "low"
        return "moderate" if below < HIGH_PCT else "high"

    def cost(self, u, v, data: dict) -> float:
        minutes, risk, _, weather = self.metrics(u, v, data)
        return minutes * (1.0 + risk * self.profile["risk_tolerance"]) * weather


def _edges_near(G: nx.DiGraph, lat: float, lon: float, radius_km: float) -> set[tuple]:
    """Edges whose end points or curve points come within radius_km of (lat, lon).

    Blocking nodes alone is not enough: a long edge can pass the incident
    with both of its end nodes outside the radius.
    """
    near = set()
    for u, v, d in G.edges(data=True):
        points = [(G.nodes[u]["x"], G.nodes[u]["y"]), (G.nodes[v]["x"], G.nodes[v]["y"])]
        points += [tuple(pt) for pt in d.get("shape", [])]
        # Also test segment midpoints so straight two-node edges are caught
        points += [((ax + bx) / 2, (ay + by) / 2) for (ax, ay), (bx, by) in zip(points[:-1], points[1:])]
        if any(_haversine_km(lat, lon, y, x) < radius_km for x, y in points):
            near.add((u, v))
    return near


def _cross_street(G: nx.DiGraph, node, street: str) -> str | None:
    """Name of a different street meeting `street` at `node`, if any."""
    for _, _, d in G.out_edges(node, data=True):
        other = street_name(d)
        if other not in (street, "Unknown"):
            return other
    for _, _, d in G.in_edges(node, data=True):
        other = street_name(d)
        if other not in (street, "Unknown"):
            return other
    return None


def diverse_paths(
    G: nx.DiGraph,
    source,
    target,
    k: int,
    costs: EdgeCosts,
    blocked_nodes: set | None = None,
    blocked_edges: set | None = None,
) -> list[list]:
    """Up to k paths, each penalising edges used by the ones before it."""
    blocked = blocked_nodes or set()
    no_edges = blocked_edges or set()
    penalty: dict[tuple, float] = {}

    def weight(u, v, d):
        if u in blocked or v in blocked or (u, v) in no_edges:
            return None  # hides the edge
        return costs.cost(u, v, d) * penalty.get((u, v), 1.0)

    paths = []
    for _ in range(k):
        try:
            path = nx.shortest_path(G, source, target, weight=weight)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            break
        if path in paths:
            break
        paths.append(path)
        for u, v in zip(path, path[1:]):
            penalty[(u, v)] = penalty.get((u, v), 1.0) * DIVERSITY_PENALTY
    return paths


def describe_path(G: nx.DiGraph, path: list, costs: EdgeCosts, vehicle_type: str = "normal") -> dict:
    """Coordinates, streets and real metrics for one path."""
    coords = [[G.nodes[path[0]]["x"], G.nodes[path[0]]["y"]]]
    streets: list[str] = []
    length_m = minutes = cost = risk_sum = density_sum = weather_sum = 0.0
    preemptions = []
    n = 0

    for i, (u, v) in enumerate(zip(path, path[1:])):
        data = G[u][v]
        coords.extend(data.get("shape", []))
        coords.append([G.nodes[v]["x"], G.nodes[v]["y"]])
        name = street_name(data)
        if name != "Unknown" and name not in streets:
            streets.append(name)
        e_min, e_risk, e_density, e_weather = costs.metrics(u, v, data)
        length_m += data.get("length", 100.0)
        minutes += e_min
        cost += costs.cost(u, v, data)
        risk_sum += e_risk
        density_sum += e_density
        weather_sum += e_weather
        n += 1

        if vehicle_type in ("ambulance", "police", "fire_brigade"):
            highway = data.get("highway", "")
            if isinstance(highway, list):
                highway = highway[0] if highway else ""
            cross = _cross_street(G, v, name)
            if highway in ("primary", "secondary", "trunk") and cross and i % 3 == 0:
                preemptions.append({
                    "intersection": f"{name} & {cross}",
                    "lat": G.nodes[v]["y"],
                    "lon": G.nodes[v]["x"],
                    "action": "Extend green phase",
                })

    n = max(n, 1)
    return {
        "coords": coords,
        "street_names": streets,
        "total_length_km": round(length_m / 1000.0, 2),
        "total_travel_time_min": round(minutes, 1),
        "composite_score": round(cost, 3),
        "avg_accident_score": round(risk_sum / n, 3),
        "avg_density": round(density_sum / n, 1),
        "avg_weather_penalty": round(weather_sum / n, 2),
        "signal_preemptions": preemptions,
    }


def find_routes(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    k: int = 3,
    feed_snapshot: Optional[list] = None,
    risk_map: Optional[list] = None,
    vehicle_type: str = "normal",
    weather_condition: Optional[str] = None,
) -> list[dict]:
    """
    Find up to k diverse routes from origin to destination on the Brooklyn road graph.
    Returns CandidateRoute dicts; route 0 has the lowest composite cost.
    """
    G = get_graph()
    costs = EdgeCosts(feed_snapshot, risk_map, vehicle_type, weather_condition)

    orig_node = nearest_node(origin_lat, origin_lon)
    dest_node = nearest_node(dest_lat, dest_lon)
    if orig_node == dest_node:
        return []

    routes = []
    for idx, path in enumerate(diverse_paths(G, orig_node, dest_node, k, costs)):
        info = describe_path(G, path, costs, vehicle_type)
        level = costs.risk_level(info["avg_accident_score"])
        color = RISK_COLORS[level]
        routes.append({
            "route_index": idx,
            "rank": "optimal" if idx == 0 else "alternative",
            "risk_level": level,
            "color": color,
            **info,
            "street_names": info["street_names"][:10],
            "is_optimal": idx == 0,
        })
    return routes


def find_diversion(
    incident_lat: float,
    incident_lon: float,
    incident_street: str,
    feed_snapshot: Optional[list] = None,
    risk_map: Optional[list] = None,
    weather_condition: Optional[str] = None,
    block_radius_km: float = 0.2,
    ring_km: tuple[float, float] = (0.4, 0.9),
) -> dict | None:
    """Real road path around a blocked incident zone.

    Picks entry and exit nodes on the incident street (or, if it has none,
    on any street) 400–900 m away on opposite sides, blocks every node within
    200 m of the incident, and routes between them.
    """
    G = get_graph()
    costs = EdgeCosts(feed_snapshot, risk_map, "normal", weather_condition)
    blocked = set(nodes_within(incident_lat, incident_lon, block_radius_km))
    blocked_edges = _edges_near(G, incident_lat, incident_lon, block_radius_km)

    ring = set(nodes_within(incident_lat, incident_lon, ring_km[1])) - set(
        nodes_within(incident_lat, incident_lon, ring_km[0])
    )
    on_street = {
        n for n in ring
        if any(street_name(d) == incident_street for _, _, d in G.edges(n, data=True))
        or any(street_name(d) == incident_street for _, _, d in G.in_edges(n, data=True))
    }
    candidates = on_street if len(on_street) >= 2 else ring
    if len(candidates) < 2:
        return None

    def pos(n):
        return G.nodes[n]["y"], G.nodes[n]["x"]

    # Entry = any candidate; exit = the candidate farthest from it (opposite side)
    nodes = sorted(candidates)
    entry = nodes[0]
    far = max(nodes, key=lambda n: _haversine_km(*pos(entry), *pos(n)))
    entry = max(nodes, key=lambda n: _haversine_km(*pos(far), *pos(n)))

    for source, target in ((entry, far), (far, entry)):
        paths = diverse_paths(G, source, target, 1, costs, blocked_nodes=blocked, blocked_edges=blocked_edges)
        if paths:
            info = describe_path(G, paths[0], costs)
            # Baseline: the normal direct trip between the same points. Time is
            # measured at free flow (what drivers lose overall); risk is measured
            # under live conditions along that normal path, through the incident.
            normal = EdgeCosts()
            direct = diverse_paths(G, source, target, 1, normal)
            direct_min = describe_path(G, direct[0], normal)["total_travel_time_min"] if direct else info["total_travel_time_min"]
            direct_risk = describe_path(G, direct[0], costs)["avg_accident_score"] if direct else info["avg_accident_score"]
            blocked_streets = sorted({street_name(G[u][v]) for u, v in blocked_edges} - {"Unknown"})
            return {
                **info,
                "extra_minutes": round(max(0.0, info["total_travel_time_min"] - direct_min), 1),
                "direct_risk": round(direct_risk, 3),
                "blocked_streets": blocked_streets[:5],
            }
    return None
