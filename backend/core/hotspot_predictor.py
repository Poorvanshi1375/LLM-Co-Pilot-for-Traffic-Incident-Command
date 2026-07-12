"""
Hotspot Predictor — DBSCAN clustering on weighted synthetic accident records.
Uses Brooklyn OSMnx graph edges to generate realistic accident distributions,
then clusters them with DBSCAN (haversine metric) to identify predicted hotspot zones.
"""
from __future__ import annotations

import os
import time
import random
import numpy as np
import osmnx as ox
from sklearn.cluster import DBSCAN
from math import radians, sin, cos, sqrt, atan2
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
GRAPH_PATH = os.path.join(DATA_DIR, "brooklyn.graphml")

# Known high-incident intersections (from risk_scorer.py) — used for weighting
KNOWN_HOTSPOT_COORDS = [
    (40.6862, -73.9778), (40.6741, -73.9708), (40.6845, -73.9785),
    (40.6690, -73.9312), (40.6032, -73.9615), (40.6580, -73.8960),
    (40.6990, -73.9415), (40.6820, -73.9502), (40.6710, -73.9830),
    (40.6955, -73.9415), (40.5890, -73.9650), (40.6502, -73.9730),
    (40.6510, -73.9620), (40.6862, -73.9880), (40.7000, -73.9380),
    (40.7145, -73.9445), (40.6904, -73.9712), (40.6745, -73.8960),
    (40.6710, -73.9228), (40.6130, -73.9785), (40.6420, -73.9020),
]

# Road type weighting for accident likelihood
ROAD_TYPE_WEIGHTS = {
    "motorway": 8, "motorway_link": 7,
    "trunk": 8, "trunk_link": 7,
    "primary": 6, "primary_link": 5,
    "secondary": 4, "secondary_link": 3,
    "tertiary": 3, "tertiary_link": 2,
    "residential": 1, "unclassified": 1, "living_street": 1,
}

# Cache
_cache: dict = {"clusters": None, "timestamp": 0.0}
CACHE_TTL_S = 3600  # 1 hour


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def _hotspot_proximity_weight(lat: float, lon: float) -> float:
    """Extra weight if close to a known hotspot intersection."""
    min_dist = min(_haversine_km(lat, lon, hs[0], hs[1]) for hs in KNOWN_HOTSPOT_COORDS)
    if min_dist < 0.3:
        return 2.5
    elif min_dist < 0.8:
        return 1.5
    return 1.0


def _road_weight(highway_attr) -> int:
    """Get accident weight from OSMnx highway attribute (may be list)."""
    if isinstance(highway_attr, list):
        return max(ROAD_TYPE_WEIGHTS.get(h, 1) for h in highway_attr)
    return ROAD_TYPE_WEIGHTS.get(highway_attr, 1)


def _generate_synthetic_accidents(G, n: int = 500) -> np.ndarray:
    """Generate N synthetic accident locations weighted by road type + hotspot proximity."""
    rng = random.Random(42)  # reproducible
    edges = list(G.edges(data=True))
    nodes = dict(G.nodes(data=True))

    # Build weighted edge list
    weighted_edges = []
    weights = []
    for u, v, data in edges:
        u_data = nodes.get(u, {})
        v_data = nodes.get(v, {})
        u_lat = u_data.get("y", 0.0)
        u_lon = u_data.get("x", 0.0)
        v_lat = v_data.get("y", 0.0)
        v_lon = v_data.get("x", 0.0)
        if u_lat == 0.0 or v_lat == 0.0:
            continue

        hw = data.get("highway", "residential")
        rw = _road_weight(hw)
        mid_lat = (u_lat + v_lat) / 2
        mid_lon = (u_lon + v_lon) / 2
        hp = _hotspot_proximity_weight(mid_lat, mid_lon)

        w = rw * hp
        weighted_edges.append((u_lat, u_lon, v_lat, v_lon))
        weights.append(w)

    if not weighted_edges:
        return np.array([]).reshape(0, 2)

    total_w = sum(weights)
    probs = [w / total_w for w in weights]

    # Sample edges proportional to weight, interpolate position along edge
    accidents = []
    for _ in range(n):
        idx = rng.choices(range(len(weighted_edges)), weights=probs, k=1)[0]
        u_lat, u_lon, v_lat, v_lon = weighted_edges[idx]
        t = rng.random()
        lat = u_lat + t * (v_lat - u_lat) + rng.gauss(0, 0.0003)
        lon = u_lon + t * (v_lon - u_lon) + rng.gauss(0, 0.0003)
        accidents.append([lat, lon])

    return np.array(accidents)


def predict_hotspots() -> list[dict]:
    """Run DBSCAN clustering on synthetic accidents, return predicted hotspot clusters."""
    now = time.time()
    if _cache["clusters"] is not None and (now - _cache["timestamp"]) < CACHE_TTL_S:
        return _cache["clusters"]

    # Load graph
    if not os.path.exists(GRAPH_PATH):
        print("Downloading Brooklyn road network from OSM (one-time)...")
        G = ox.graph_from_place("Brooklyn, New York City, New York, USA", network_type="drive")
        os.makedirs(DATA_DIR, exist_ok=True)
        ox.save_graphml(G, GRAPH_PATH)
        print(f"Saved graph to {GRAPH_PATH}")
    else:
        G = ox.load_graphml(GRAPH_PATH)

    # Generate synthetic accidents
    accidents = _generate_synthetic_accidents(G, n=500)
    if len(accidents) == 0:
        return []

    # DBSCAN requires radians for haversine metric
    coords_rad = np.radians(accidents)
    db = DBSCAN(eps=0.00004, min_samples=3, metric="haversine", algorithm="ball_tree")
    labels = db.fit_predict(coords_rad)

    # Build clusters
    clusters = []
    unique_labels = set(labels)
    unique_labels.discard(-1)  # noise

    for cluster_id in sorted(unique_labels):
        mask = labels == cluster_id
        cluster_points = accidents[mask]
        center_lat = float(np.mean(cluster_points[:, 0]))
        center_lon = float(np.mean(cluster_points[:, 1]))
        count = int(mask.sum())

        # Severity: weighted random per point (seeded by cluster_id)
        severity_rng = random.Random(int(cluster_id) + 100)
        severities = [severity_rng.choices([1, 2, 3], weights=[60, 30, 10], k=1)[0] for _ in range(count)]
        avg_severity = sum(severities) / len(severities)

        risk_score = round(count * avg_severity, 2)

        # Radius: max distance from center to any point in cluster
        max_dist = max(
            _haversine_km(center_lat, center_lon, p[0], p[1])
            for p in cluster_points
        )
        radius_m = round(max_dist * 1000, 1)

        clusters.append({
            "cluster_id": int(cluster_id),
            "center_lat": round(center_lat, 6),
            "center_lon": round(center_lon, 6),
            "accident_count": count,
            "severity_score": round(avg_severity, 2),
            "risk_score": risk_score,
            "radius_m": max(radius_m, 50.0),  # minimum 50m for visibility
        })

    # Sort by risk score descending
    clusters.sort(key=lambda c: c["risk_score"], reverse=True)

    _cache["clusters"] = clusters
    _cache["timestamp"] = now
    return clusters
