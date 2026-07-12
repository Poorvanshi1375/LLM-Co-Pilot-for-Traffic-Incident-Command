"""
Route Finder — K-shortest paths on Brooklyn OSMnx road graph.
MultiDiGraph → DiGraph conversion, priority routing for emergency vehicles,
weather-aware edge weighting, and green/yellow/red route coloring.
"""
from __future__ import annotations

import os
import heapq
import networkx as nx
import osmnx as ox
import numpy as np
from math import radians, sin, cos, sqrt, atan2
from typing import Optional
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
GRAPH_PATH = os.path.join(DATA_DIR, "brooklyn.graphml")

# Vehicle type speed/risk multipliers
# Emergency vehicles: travel faster, accept more risk
VEHICLE_PROFILES = {
    "normal":       {"speed_mult": 1.0, "risk_tolerance": 1.0},
    "ambulance":    {"speed_mult": 1.4, "risk_tolerance": 0.5},
    "police":       {"speed_mult": 1.3, "risk_tolerance": 0.6},
    "fire_brigade": {"speed_mult": 1.2, "risk_tolerance": 0.4},
}

# Cached graph (loaded once)
_di_graph = None
_multi_graph = None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def _load_graph():
    """Load Brooklyn graph and convert MultiDiGraph → DiGraph (keeping min-weight edges)."""
    global _di_graph, _multi_graph
    if _di_graph is not None:
        return _di_graph, _multi_graph

    if not os.path.exists(GRAPH_PATH):
        print("Downloading Brooklyn road network from OSM (one-time)...")
        _multi_graph = ox.graph_from_place("Brooklyn, New York City, New York, USA", network_type="drive")
        os.makedirs(DATA_DIR, exist_ok=True)
        ox.save_graphml(_multi_graph, GRAPH_PATH)
        print(f"Saved graph to {GRAPH_PATH}")
    else:
        _multi_graph = ox.load_graphml(GRAPH_PATH)

    # Convert MultiDiGraph → DiGraph: for each (u,v) keep the edge with minimum length
    _di_graph = nx.DiGraph()
    for node, data in _multi_graph.nodes(data=True):
        _di_graph.add_node(node, **data)

    for u, v, key, data in _multi_graph.edges(keys=True, data=True):
        length = data.get("length", 100.0)
        if _di_graph.has_edge(u, v):
            if length < _di_graph[u][v].get("length", float("inf")):
                _di_graph[u][v].update(data)
        else:
            _di_graph.add_edge(u, v, **data)

    return _di_graph, _multi_graph


def _get_street_name(data: dict) -> str:
    """Extract street name from edge data."""
    name = data.get("name", "")
    if isinstance(name, list):
        return name[0] if name else "Unknown"
    return name or "Unknown"


def _get_speed_limit(data: dict) -> float:
    """Extract speed limit in mph from edge data."""
    maxspeed = data.get("maxspeed", "25")
    if isinstance(maxspeed, list):
        maxspeed = maxspeed[0]
    try:
        return float(str(maxspeed).replace(" mph", ""))
    except (ValueError, TypeError):
        return 25.0


def _compute_edge_weight(
    u_data: dict,
    v_data: dict,
    edge_data: dict,
    feed_lookup: dict,
    risk_lookup: dict,
    vehicle_type: str = "normal",
    weather_penalty_fn=None,
) -> float:
    """Compute composite edge weight considering distance, traffic, risk, weather, and vehicle type."""
    length_m = edge_data.get("length", 100.0)
    street_name = _get_street_name(edge_data)
    speed_limit = _get_speed_limit(edge_data)

    profile = VEHICLE_PROFILES.get(vehicle_type, VEHICLE_PROFILES["normal"])

    # Current speed from feed (if available), else use speed limit
    u_lat = u_data.get("y", 0.0)
    u_lon = u_data.get("x", 0.0)
    mid_lat = (u_lat + v_data.get("y", 0.0)) / 2
    mid_lon = (u_lon + v_data.get("x", 0.0)) / 2

    # Find closest segment speed from feed
    current_speed = speed_limit
    closest_dist = float("inf")
    for seg_id, seg_data in feed_lookup.items():
        d = abs(seg_data["lat"] - mid_lat) + abs(seg_data["lon"] - mid_lon)
        if d < closest_dist:
            closest_dist = d
            current_speed = seg_data.get("speed", speed_limit)

    # Emergency vehicles travel faster
    effective_speed = max(current_speed * profile["speed_mult"], 5.0)

    # Travel time in minutes
    travel_time = (length_m / 1609.34) / (effective_speed / 60.0)  # length in miles / speed in mph * 60

    # Risk score from risk map
    risk_score = 0.1
    closest_risk_dist = float("inf")
    for seg_id, r_data in risk_lookup.items():
        d = abs(r_data["lat"] - mid_lat) + abs(r_data["lon"] - mid_lon)
        if d < closest_risk_dist:
            closest_risk_dist = d
            risk_score = r_data.get("score", 0.1)

    # Weather penalty
    w_penalty = 1.0
    if weather_penalty_fn is not None:
        try:
            w_penalty = weather_penalty_fn(street_name)
        except Exception:
            w_penalty = 1.0

    # Composite weight: travel_time * (1 + risk * risk_tolerance) * weather_penalty
    weight = travel_time * (1.0 + risk_score * profile["risk_tolerance"]) * w_penalty

    return weight


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
    Find k-shortest routes from origin to destination on Brooklyn road graph.
    Returns list of CandidateRoute dicts with coords, metrics, and coloring.
    """
    G, MG = _load_graph()

    # Build lookup dicts from live data
    feed_lookup = {}
    if feed_snapshot:
        for seg in feed_snapshot:
            if hasattr(seg, "model_dump"):
                s = seg.model_dump()
            elif isinstance(seg, dict):
                s = seg
            else:
                continue
            feed_lookup[s.get("segment_id", "")] = s

    risk_lookup = {}
    if risk_map:
        for r in risk_map:
            if hasattr(r, "model_dump"):
                rd = r.model_dump()
            elif isinstance(r, dict):
                rd = r
            else:
                continue
            risk_lookup[rd.get("segment_id", "")] = rd

    # Weather penalty function
    weather_penalty_fn = None
    if weather_condition and weather_condition != "clear":
        try:
            from core.weather_service import get_weather_penalty
            weather_penalty_fn = lambda name: get_weather_penalty(name, weather_condition)
        except ImportError:
            pass

    # Snap to nearest graph nodes
    orig_node = ox.nearest_nodes(MG, X=origin_lon, Y=origin_lat)
    dest_node = ox.nearest_nodes(MG, X=dest_lon, Y=dest_lat)

    if orig_node == dest_node:
        return []

    # Compute base edge weights
    for u, v, data in G.edges(data=True):
        u_data = G.nodes[u]
        v_data = G.nodes[v]
        w = _compute_edge_weight(u_data, v_data, data, feed_lookup, risk_lookup, vehicle_type, weather_penalty_fn)
        data["_weight"] = w
        data["_base_weight"] = w  # preserve original for penalty resets

    # Find k diverse paths using penalty-based approach:
    # After finding each shortest path, penalize its edges heavily so the next
    # shortest path is forced onto different roads.
    paths = []
    DIVERSITY_PENALTY = 5.0  # multiplier applied to shared edges
    for _ in range(k):
        try:
            path = nx.shortest_path(G, orig_node, dest_node, weight="_weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            break
        paths.append(path)
        # Penalize edges used by this path so future paths avoid them
        for j in range(len(path) - 1):
            u, v = path[j], path[j + 1]
            if G.has_edge(u, v):
                G[u][v]["_weight"] *= DIVERSITY_PENALTY

    # Restore original weights so cached graph isn't corrupted
    for u, v, data in G.edges(data=True):
        if "_base_weight" in data:
            data["_weight"] = data["_base_weight"]

    if not paths:
        return []

    # Build route responses
    routes = []
    colors = ["#10B981", "#F59E0B", "#EF4444"]  # green, yellow, red
    ranks = ["optimal", "moderate", "high"]

    for idx, path in enumerate(paths):
        coords = []
        street_names = []
        total_length_m = 0.0
        total_time = 0.0
        density_sum = 0.0
        risk_sum = 0.0
        weather_sum = 0.0
        segment_count = 0
        signal_preemptions = []

        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            u_data = G.nodes[u]
            v_data = G.nodes[v]
            edge_data = G[u][v]

            lat_u = u_data.get("y", 0.0)
            lon_u = u_data.get("x", 0.0)
            coords.append([lon_u, lat_u])

            street = _get_street_name(edge_data)
            if street not in street_names:
                street_names.append(street)

            length_m = edge_data.get("length", 100.0)
            total_length_m += length_m

            weight = edge_data.get("_weight", 1.0)
            total_time += weight

            # Collect metrics
            mid_lat = (lat_u + v_data.get("y", 0.0)) / 2
            mid_lon = (lon_u + v_data.get("x", 0.0)) / 2

            # Find density from feed
            seg_density = 0.5
            closest_d = float("inf")
            for sid, sd in feed_lookup.items():
                d = abs(sd["lat"] - mid_lat) + abs(sd["lon"] - mid_lon)
                if d < closest_d:
                    closest_d = d
                    seg_density = sd.get("density", 0.5)
            density_sum += seg_density

            # Risk
            seg_risk = 0.1
            closest_r = float("inf")
            for sid, rd in risk_lookup.items():
                d = abs(rd["lat"] - mid_lat) + abs(rd["lon"] - mid_lon)
                if d < closest_r:
                    closest_r = d
                    seg_risk = rd.get("score", 0.1)
            risk_sum += seg_risk

            # Weather penalty
            if weather_penalty_fn:
                try:
                    weather_sum += weather_penalty_fn(street)
                except Exception:
                    weather_sum += 1.0
            else:
                weather_sum += 1.0

            segment_count += 1

            # Signal preemptions for emergency vehicles
            if vehicle_type in ("ambulance", "police", "fire_brigade"):
                highway = edge_data.get("highway", "")
                if isinstance(highway, list):
                    highway = highway[0] if highway else ""
                if highway in ("primary", "secondary", "trunk") and i % 3 == 0:
                    signal_preemptions.append({
                        "intersection": f"{street} node {v}",
                        "lat": v_data.get("y", 0.0),
                        "lon": v_data.get("x", 0.0),
                        "action": "Extend green phase",
                    })

        # Add final node
        last_node = path[-1]
        last_data = G.nodes[last_node]
        coords.append([last_data.get("x", 0.0), last_data.get("y", 0.0)])

        avg_density = density_sum / max(segment_count, 1)
        avg_risk = risk_sum / max(segment_count, 1)
        avg_weather = weather_sum / max(segment_count, 1)

        composite_score = total_time

        route = {
            "route_index": idx,
            "rank": ranks[min(idx, len(ranks) - 1)],
            "color": colors[min(idx, len(colors) - 1)],
            "street_names": street_names[:10],  # top 10 streets
            "coords": coords,
            "total_length_km": round(total_length_m / 1000.0, 2),
            "total_travel_time_min": round(total_time, 2),
            "avg_density": round(avg_density, 3),
            "avg_accident_score": round(avg_risk, 3),
            "avg_weather_penalty": round(avg_weather, 2),
            "composite_score": round(composite_score, 3),
            "is_optimal": idx == 0,
            "signal_preemptions": signal_preemptions if vehicle_type != "normal" else [],
        }
        routes.append(route)

    return routes


def _k_shortest_paths(G, source, target, k, weight="_weight"):
    """Yen's k-shortest simple loopless paths algorithm."""
    try:
        shortest = nx.shortest_path(G, source, target, weight=weight)
    except nx.NetworkXNoPath:
        return

    yield shortest
    if k == 1:
        return

    A = [shortest]
    B = []  # candidates (heap)

    for i in range(1, k):
        for j in range(len(A[i - 1]) - 1):
            spur_node = A[i - 1][j]
            root_path = A[i - 1][:j + 1]

            removed_edges = []
            for path in A:
                if len(path) > j and path[:j + 1] == root_path:
                    u, v = path[j], path[j + 1]
                    if G.has_edge(u, v):
                        edge_data = G[u][v].copy()
                        G.remove_edge(u, v)
                        removed_edges.append((u, v, edge_data))

            # Remove root_path nodes (except spur_node) from graph temporarily
            removed_nodes = []
            for node in root_path[:-1]:
                if node != spur_node and node in G:
                    node_edges = list(G.edges(node, data=True)) + list(G.in_edges(node, data=True))
                    removed_nodes.append((node, dict(G.nodes[node]), node_edges))
                    G.remove_node(node)

            try:
                spur_path = nx.shortest_path(G, spur_node, target, weight=weight)
                total_path = root_path[:-1] + spur_path
                total_weight = sum(
                    G[total_path[n]][total_path[n + 1]].get(weight, 1.0)
                    for n in range(len(total_path) - 1)
                    if G.has_edge(total_path[n], total_path[n + 1])
                )

                if total_path not in A:
                    heapq.heappush(B, (total_weight, total_path))
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                pass

            # Restore removed nodes and edges
            for node, node_data, node_edges in removed_nodes:
                G.add_node(node, **node_data)
                for u2, v2, ed in node_edges:
                    if not G.has_edge(u2, v2):
                        G.add_edge(u2, v2, **ed)

            for u, v, ed in removed_edges:
                if not G.has_edge(u, v):
                    G.add_edge(u, v, **ed)

        if not B:
            break

        while B:
            cost, path = heapq.heappop(B)
            if path not in A:
                A.append(path)
                yield path
                break
        else:
            break
