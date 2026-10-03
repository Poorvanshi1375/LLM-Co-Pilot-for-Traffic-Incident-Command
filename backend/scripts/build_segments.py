"""Choose the monitored feed segments, spread evenly across Brooklyn.

Picks one major-road edge (trunk/primary/secondary/tertiary, named) per grid
cell, preferring higher road classes, until about TARGET segments cover the
borough. Writes data/brooklyn_segments.json in the feed engine's format.

    python scripts/build_segments.py
"""
import json
import os
import sys
from math import atan2, cos, degrees, radians

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.road_graph import get_graph, street_name  # noqa: E402

TARGET = 250
SEGMENTS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "brooklyn_segments.json")
CLASS_RANK = {"trunk": 4, "primary": 3, "secondary": 2, "tertiary": 1}
DEFAULT_MPH = {"trunk": 40.0, "primary": 30.0, "secondary": 25.0, "tertiary": 25.0}


def road_class(data) -> str | None:
    hw = data.get("highway", "")
    for h in (hw if isinstance(hw, list) else [hw]):
        if h in CLASS_RANK:
            return h
    return None


def speed_limit(data, cls) -> float:
    ms = data.get("maxspeed")
    if isinstance(ms, list):
        ms = ms[0]
    try:
        return float(str(ms).replace(" mph", ""))
    except (TypeError, ValueError):
        return DEFAULT_MPH[cls]


G = get_graph()
candidates = []
seen_pairs = set()
for u, v, d in G.edges(data=True):
    cls = road_class(d)
    name = street_name(d)
    if not cls or name == "Unknown" or d.get("length", 0) < 60:
        continue
    if (v, u) in seen_pairs:
        continue  # keep one direction of a two-way street
    seen_pairs.add((u, v))
    lat = (G.nodes[u]["y"] + G.nodes[v]["y"]) / 2
    lon = (G.nodes[u]["x"] + G.nodes[v]["x"]) / 2
    candidates.append((u, v, d, cls, name, lat, lon))


def pick(cell_deg: float) -> list:
    best: dict = {}
    for c in candidates:
        _, _, d, cls, _, lat, lon = c
        key = (int(lat / cell_deg), int(lon / (cell_deg / cos(radians(40.65)))))
        score = (CLASS_RANK[cls], d.get("length", 0))
        if key not in best or score > best[key][0]:
            best[key] = (score, c)
    return [c for _, c in best.values()]


# Find the cell size that yields just over TARGET occupied cells
lo, hi = 0.002, 0.05
for _ in range(30):
    mid = (lo + hi) / 2
    if len(pick(mid)) > TARGET:
        lo = mid
    else:
        hi = mid
chosen = sorted(pick(lo), key=lambda c: (-CLASS_RANK[c[3]], -c[2].get("length", 0)))[:TARGET]

segments = []
for u, v, d, cls, name, lat, lon in chosen:
    bearing = degrees(atan2(
        (G.nodes[v]["x"] - G.nodes[u]["x"]) * cos(radians(lat)),
        G.nodes[v]["y"] - G.nodes[u]["y"],
    )) % 360
    segments.append({
        "segment_id": f"seg_{u}_{v}",
        "street_name": name,
        "free_flow_speed": speed_limit(d, cls),
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "length": round(float(d.get("length", 100.0)), 1),
        "bearing": round(bearing, 1),
    })

with open(SEGMENTS_PATH, "w", encoding="utf-8") as f:
    json.dump(segments, f)

names = {s["street_name"] for s in segments}
print(f"Wrote {len(segments)} segments on {len(names)} streets (grid cell {lo:.4f} deg) to {SEGMENTS_PATH}")
for must in ("Flatbush Avenue", "Atlantic Avenue"):
    print(f"  {must}: {'yes' if must in names else 'MISSING'}")
