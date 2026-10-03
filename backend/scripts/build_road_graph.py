"""Export the slim runtime road graph to data/brooklyn_graph.json.gz.

Run from the backend folder after brooklyn.graphml changes (needs osmnx from
requirements-dev.txt), then rebuild hotspots:
    python scripts/build_road_graph.py
    python scripts/build_hotspots.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.road_graph import GRAPH_PATH, build_from_graphml, save_slim  # noqa: E402

G = build_from_graphml()
save_slim(G)
print(f"Wrote {G.number_of_nodes()} nodes, {G.number_of_edges()} edges to {GRAPH_PATH} "
      f"({os.path.getsize(GRAPH_PATH) / 1e6:.1f} MB)")
