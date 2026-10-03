"""Precompute predicted hotspot clusters into data/hotspots.json.

Run from the backend folder after the road graph changes:
    python scripts/build_hotspots.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.hotspot_predictor import HOTSPOTS_PATH, compute_hotspots  # noqa: E402

clusters = compute_hotspots()
with open(HOTSPOTS_PATH, "w", encoding="utf-8") as f:
    json.dump(clusters, f, indent=1)
print(f"Wrote {len(clusters)} clusters to {HOTSPOTS_PATH}")
