"""
Road Graph — loads the Brooklyn road network once and shares it.
Routing, diversion and hotspot code all read from this single copy.

At runtime the graph comes from data/brooklyn_graph.json.gz, a slim export
(node coordinates; edge length, name, speed limit, road type, curve shape)
built offline by scripts/build_road_graph.py from the OSMnx graphml. Loading
it needs only networkx — no osmnx/geopandas — which keeps the server well
inside a 512 MB instance. Nearest-node lookups use a KD-tree.
"""
from __future__ import annotations

import gzip
import json
import os
import threading
from math import cos, radians

import networkx as nx
import numpy as np
from scipy.spatial import cKDTree

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
GRAPHML_PATH = os.path.join(DATA_DIR, "brooklyn.graphml")
GRAPH_PATH = os.path.join(DATA_DIR, "brooklyn_graph.json.gz")

# Brooklyn centre latitude — longitudes are scaled by cos(lat) so KD-tree
# distances are roughly isotropic at this latitude.
_LON_SCALE = cos(radians(40.65))

# Edge attributes the app actually reads; everything else is dropped.
_EDGE_KEEP = ("length", "name", "maxspeed", "highway")

_lock = threading.Lock()
_graph: nx.DiGraph | None = None
_tree: cKDTree | None = None
_node_ids: list = []


def build_from_graphml(path: str = GRAPHML_PATH) -> nx.DiGraph:
    """Offline: OSMnx graphml → slim DiGraph (keeps the shortest of parallel edges).

    Needs osmnx, which is a build-time dependency only (requirements-dev.txt).
    """
    import osmnx as ox

    multi = ox.load_graphml(path)
    G = nx.DiGraph()
    for node, data in multi.nodes(data=True):
        G.add_node(node, x=float(data["x"]), y=float(data["y"]))

    for u, v, data in multi.edges(data=True):
        slim = {k: data[k] for k in _EDGE_KEEP if k in data}
        slim["length"] = float(slim.get("length", 100.0))
        geom = data.get("geometry")
        if geom is not None:
            # Interior points of a curved road, as compact [lon, lat] pairs
            slim["shape"] = [[round(x, 6), round(y, 6)] for x, y in list(geom.coords)[1:-1]]
        if G.has_edge(u, v):
            if slim["length"] < G[u][v]["length"]:
                G[u][v].clear()
                G[u][v].update(slim)
        else:
            G.add_edge(u, v, **slim)
    return G


def save_slim(G: nx.DiGraph, path: str = GRAPH_PATH) -> None:
    """Write the slim graph as gzipped JSON (version-independent, unlike a pickle)."""
    payload = {
        "nodes": [[n, round(d["x"], 7), round(d["y"], 7)] for n, d in G.nodes(data=True)],
        "edges": [[u, v, d] for u, v, d in G.edges(data=True)],
    }
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))


def _load_slim(path: str = GRAPH_PATH) -> nx.DiGraph:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        payload = json.load(f)
    G = nx.DiGraph()
    for n, x, y in payload["nodes"]:
        G.add_node(n, x=x, y=y)
    for u, v, d in payload["edges"]:
        G.add_edge(u, v, **d)
    return G


def _build() -> None:
    """Load the slim graph (or, if missing, build it from graphml) and its KD-tree."""
    global _graph, _tree, _node_ids
    if os.path.exists(GRAPH_PATH):
        G = _load_slim()
    else:
        print(f"{GRAPH_PATH} missing — building from graphml (slow, needs osmnx)")
        G = build_from_graphml()

    node_ids = list(G.nodes)
    coords = np.array([[G.nodes[n]["x"] * _LON_SCALE, G.nodes[n]["y"]] for n in node_ids])
    _tree = cKDTree(coords)
    _node_ids = node_ids
    _graph = G
    print(f"Road graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")


def get_graph() -> nx.DiGraph:
    """Return the shared DiGraph, loading it on first use (thread-safe)."""
    if _graph is None:
        with _lock:
            if _graph is None:
                _build()
    assert _graph is not None
    return _graph


def is_loaded() -> bool:
    return _graph is not None


def nearest_node(lat: float, lon: float):
    """Graph node closest to (lat, lon)."""
    get_graph()
    assert _tree is not None
    _, idx = _tree.query([lon * _LON_SCALE, lat])
    return _node_ids[int(idx)]


def attach_segments(segments: list[dict], max_km: float = 0.5) -> None:
    """Tag each edge with its nearest feed segment ("seg") once, via KD-tree.

    Per-request routing then reads live speed and risk with a dict lookup
    instead of scanning every segment for every edge. Edges farther than
    max_km from any segment get no tag and fall back to their speed limit.
    """
    G = get_graph()
    if not segments:
        return
    seg_ids = [s["segment_id"] for s in segments]
    seg_tree = cKDTree([[s["lon"] * _LON_SCALE, s["lat"]] for s in segments])

    edges = list(G.edges(data=True))
    mids = [
        [(G.nodes[u]["x"] + G.nodes[v]["x"]) / 2 * _LON_SCALE, (G.nodes[u]["y"] + G.nodes[v]["y"]) / 2]
        for u, v, _ in edges
    ]
    dists, idxs = seg_tree.query(mids)
    max_deg = max_km / 111.0  # ~111 km per degree of latitude
    for (u, v, data), d, i in zip(edges, dists, idxs):
        if d <= max_deg:
            data["seg"] = seg_ids[int(i)]
        else:
            data.pop("seg", None)


def nodes_within(lat: float, lon: float, radius_km: float) -> list:
    """All graph nodes within radius_km of (lat, lon)."""
    get_graph()
    assert _tree is not None
    idxs = _tree.query_ball_point([lon * _LON_SCALE, lat], radius_km / 111.0)
    return [_node_ids[i] for i in idxs]


def street_name(data: dict) -> str:
    """Street name from edge data (OSMnx may store a list)."""
    name = data.get("name", "")
    if isinstance(name, list):
        return name[0] if name else "Unknown"
    return name or "Unknown"
