"""Build the map's road layer: every Brooklyn road as a line, as static GeoJSON.

Writes frontend/public/road-network.geojson. Each feature has:
  c — road class for styling: 0 highway, 1 primary, 2 secondary/tertiary, 3 minor
  s — (only on roads with live data) the monitored segment whose speed colours it

A road takes a segment's colour only if it is the SAME street and within
MATCH_KM of that segment, so side streets stay grey instead of borrowing an
avenue's speed. Run after build_segments.py:
    python scripts/build_road_layer.py
"""
import json
import os
import sys
from math import atan2, cos, radians, sin, sqrt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.road_graph import get_graph, street_name  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SEGMENTS_PATH = os.path.join(ROOT, "backend", "data", "brooklyn_segments.json")
OUT_PATH = os.path.join(ROOT, "frontend", "public", "road-network.geojson")
MATCH_KM = 0.6

CLASS = {
    "motorway": 0, "motorway_link": 0, "trunk": 0, "trunk_link": 0,
    "primary": 1, "primary_link": 1,
    "secondary": 2, "secondary_link": 2, "tertiary": 2, "tertiary_link": 2,
}


def km(lat1, lon1, lat2, lon2):
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 6371 * 2 * atan2(sqrt(a), sqrt(1 - a))


def road_class(data) -> int:
    hw = data.get("highway", "")
    return min((CLASS.get(h, 3) for h in (hw if isinstance(hw, list) else [hw])), default=3)


with open(SEGMENTS_PATH, encoding="utf-8") as f:
    segments = json.load(f)
by_street: dict[str, list] = {}
for s in segments:
    by_street.setdefault(s["street_name"], []).append(s)

G = get_graph()
features, seen, colored = [], set(), 0
for u, v, d in G.edges(data=True):
    if (v, u) in seen:
        continue  # one line per two-way street
    seen.add((u, v))
    coords = [[G.nodes[u]["x"], G.nodes[u]["y"]], *d.get("shape", []), [G.nodes[v]["x"], G.nodes[v]["y"]]]
    coords = [[round(x, 5), round(y, 5)] for x, y in coords]
    props = {"c": road_class(d)}

    name = street_name(d)
    if name in by_street:
        mid_lat = (G.nodes[u]["y"] + G.nodes[v]["y"]) / 2
        mid_lon = (G.nodes[u]["x"] + G.nodes[v]["x"]) / 2
        best = min(by_street[name], key=lambda s: km(mid_lat, mid_lon, s["lat"], s["lon"]))
        if km(mid_lat, mid_lon, best["lat"], best["lon"]) <= MATCH_KM:
            props["s"] = best["segment_id"]
            colored += 1

    features.append({"type": "Feature", "properties": props, "geometry": {"type": "LineString", "coordinates": coords}})

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump({"type": "FeatureCollection", "features": features}, f, separators=(",", ":"))

print(f"Wrote {len(features)} roads ({colored} with live data) to {OUT_PATH} "
      f"({os.path.getsize(OUT_PATH) / 1e6:.1f} MB)")
