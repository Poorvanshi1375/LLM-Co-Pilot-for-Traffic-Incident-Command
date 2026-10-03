"""
Feed Engine — Generates synthetic Brooklyn traffic speed data.
Uses OSMnx edges with time-of-day degradation, peak-hour curves, and Gaussian noise.
"""
from __future__ import annotations

import os
import json
import time
import random
import threading
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

NYC_TZ = ZoneInfo("America/New_York")

try:
    import osmnx as ox
    import networkx as nx
    OSMNX_AVAILABLE = True
except ImportError:
    OSMNX_AVAILABLE = False

from models.schemas import SegmentSpeed, FeedTick

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
GRAPH_PATH = os.path.join(DATA_DIR, "brooklyn.graphml")
SEGMENTS_PATH = os.path.join(DATA_DIR, "brooklyn_segments.json")

# Peak hour windows (24h format)
MORNING_PEAK = (8.0, 10.5)   # 08:00 – 10:30
EVENING_PEAK = (17.5, 20.5)  # 17:30 – 20:30


def _time_of_day_factor(hour: float, jitter: float = 0.5) -> float:
    """Returns speed degradation factor (0.4 = worst, 1.0 = free flow).

    jitter (0–1) varies off-peak levels; the feed draws it once per hour so the
    whole network does not jump up and down every tick.
    """
    if MORNING_PEAK[0] <= hour <= MORNING_PEAK[1]:
        peak_center = (MORNING_PEAK[0] + MORNING_PEAK[1]) / 2
        dist = abs(hour - peak_center) / ((MORNING_PEAK[1] - MORNING_PEAK[0]) / 2)
        return 0.4 + 0.3 * dist
    elif EVENING_PEAK[0] <= hour <= EVENING_PEAK[1]:
        peak_center = (EVENING_PEAK[0] + EVENING_PEAK[1]) / 2
        dist = abs(hour - peak_center) / ((EVENING_PEAK[1] - EVENING_PEAK[0]) / 2)
        return 0.35 + 0.3 * dist
    elif 6.0 <= hour < 8.0 or 10.5 < hour < 17.5:
        return 0.75 + 0.15 * jitter
    elif 20.5 < hour <= 23.0:
        return 0.8 + 0.15 * jitter
    else:
        return 0.95 + 0.05 * jitter


def _download_and_cache_graph():
    """Download Brooklyn road network via OSMnx and cache it."""
    if not OSMNX_AVAILABLE:
        return None
    if os.path.exists(GRAPH_PATH):
        return ox.load_graphml(GRAPH_PATH)

    print("Downloading Brooklyn road network from OSM (one-time)...")
    G = ox.graph_from_place("Brooklyn, New York City, New York, USA", network_type="drive")
    os.makedirs(DATA_DIR, exist_ok=True)
    ox.save_graphml(G, GRAPH_PATH)
    print(f"Saved graph to {GRAPH_PATH}")
    return G


def _generate_segments_from_graph(G) -> list[dict]:
    """Extract road segments with real street names from OSMnx graph."""
    segments = []
    seen_streets = set()

    for u, v, data in G.edges(data=True):
        street_name = data.get("name", None)
        if street_name is None:
            continue
        if isinstance(street_name, list):
            street_name = street_name[0]

        # Deduplicate to ~200 representative segments
        if street_name in seen_streets and random.random() > 0.15:
            continue
        seen_streets.add(street_name)

        u_data = G.nodes[u]
        v_data = G.nodes[v]
        lat = (u_data["y"] + v_data["y"]) / 2
        lon = (u_data["x"] + v_data["x"]) / 2

        max_speed = data.get("maxspeed", "30")
        if isinstance(max_speed, list):
            max_speed = max_speed[0]
        try:
            free_flow = float(str(max_speed).replace(" mph", ""))
        except (ValueError, TypeError):
            free_flow = 30.0

        length = data.get("length", 200)
        bearing = data.get("bearing", random.uniform(0, 360))

        segments.append({
            "segment_id": f"seg_{u}_{v}",
            "street_name": street_name,
            "free_flow_speed": free_flow,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "length": round(float(length), 1),
            "bearing": round(float(bearing) if isinstance(bearing, (int, float)) else random.uniform(0, 360), 1),
        })

        if len(segments) >= 250:
            break

    return segments


def _generate_fallback_segments() -> list[dict]:
    """Fallback Brooklyn street segments if OSMnx isn't available."""
    streets = [
        ("Flatbush Avenue", 40.6832, -73.9712, 30),
        ("Atlantic Avenue", 40.6862, -73.9778, 30),
        ("Eastern Parkway", 40.6711, -73.9584, 30),
        ("Ocean Avenue", 40.6492, -73.9615, 25),
        ("Bedford Avenue", 40.6942, -73.9573, 25),
        ("Fulton Street", 40.6872, -73.9752, 25),
        ("Myrtle Avenue", 40.6945, -73.9685, 25),
        ("Broadway", 40.7000, -73.9415, 30),
        ("4th Avenue", 40.6750, -73.9830, 30),
        ("3rd Avenue", 40.6785, -73.9810, 25),
        ("Nostrand Avenue", 40.6629, -73.9502, 25),
        ("Utica Avenue", 40.6580, -73.9312, 25),
        ("Kings Highway", 40.6032, -73.9622, 30),
        ("Coney Island Avenue", 40.6350, -73.9650, 25),
        ("Bay Parkway", 40.6130, -73.9785, 25),
        ("Linden Boulevard", 40.6580, -73.9218, 30),
        ("Empire Boulevard", 40.6625, -73.9580, 25),
        ("Church Avenue", 40.6510, -73.9620, 25),
        ("Prospect Park West", 40.6635, -73.9788, 25),
        ("Grand Army Plaza", 40.6741, -73.9708, 20),
        ("Smith Street", 40.6862, -73.9887, 25),
        ("Court Street", 40.6870, -73.9920, 25),
        ("Bergen Street", 40.6810, -73.9768, 25),
        ("DeKalb Avenue", 40.6904, -73.9742, 25),
        ("Flushing Avenue", 40.6980, -73.9650, 30),
        ("McGuinness Boulevard", 40.7280, -73.9510, 30),
        ("Manhattan Avenue", 40.7230, -73.9540, 25),
        ("Graham Avenue", 40.7145, -73.9445, 25),
        ("Metropolitan Avenue", 40.7145, -73.9510, 25),
        ("Division Avenue", 40.7100, -73.9580, 25),
        ("Williamsburg Bridge Approach", 40.7137, -73.9650, 35),
        ("BQE Service Road", 40.6920, -73.9800, 35),
        ("Prospect Expressway", 40.6502, -73.9822, 40),
        ("Belt Parkway", 40.5890, -73.9680, 45),
        ("Shore Parkway", 40.5780, -73.9700, 40),
        ("Pennsylvania Avenue", 40.6580, -73.8960, 25),
        ("Rockaway Parkway", 40.6420, -73.9020, 25),
        ("Ralph Avenue", 40.6680, -73.9228, 25),
        ("Sutter Avenue", 40.6650, -73.9100, 25),
        ("Pitkin Avenue", 40.6710, -73.9060, 25),
        ("Liberty Avenue", 40.6745, -73.8980, 25),
        ("Jamaica Avenue", 40.6810, -73.8880, 25),
        ("Bushwick Avenue", 40.7000, -73.9380, 25),
        ("Knickerbocker Avenue", 40.6990, -73.9195, 25),
        ("Wyckoff Avenue", 40.7020, -73.9120, 25),
        ("Fresh Pond Road", 40.7060, -73.8960, 25),
        ("Greenpoint Avenue", 40.7310, -73.9530, 25),
        ("Kent Avenue", 40.7210, -73.9620, 25),
        ("Vanderbilt Avenue", 40.6810, -73.9688, 25),
        ("Washington Avenue", 40.6790, -73.9650, 25),
    ]

    segments = []
    for i, (name, lat, lon, ffs) in enumerate(streets):
        segments.append({
            "segment_id": f"seg_bk_{i}",
            "street_name": name,
            "free_flow_speed": ffs,
            "lat": lat,
            "lon": lon,
            "length": random.uniform(150, 800),
            "bearing": random.uniform(0, 360),
        })
    return segments


class FeedEngine:
    """Manages the synthetic traffic speed feed."""

    def __init__(self):
        self._segments: list[dict] = []
        self._tick = 0
        self._running = False
        self._lock = threading.Lock()
        self._snapshot: list[SegmentSpeed] = []
        self._listeners: list[Callable] = []
        self._incident_segment: str | None = None
        self._incident_speed_factor: float = 0.0
        # Congestion decay after incident clears (15-min window)
        self._decay_segment: str | None = None
        self._decay_start: float | None = None  # time.time() when decay started
        self._decay_duration: float = 900.0  # 15 minutes in seconds
        now = datetime.now(NYC_TZ)
        self._simulated_hour: float = now.hour + now.minute / 60.0
        self._jitter_hour: int = -1
        self._jitter: float = 0.5

    def initialize(self):
        """Load or generate segment data."""
        if os.path.exists(SEGMENTS_PATH):
            with open(SEGMENTS_PATH) as f:
                self._segments = json.load(f)
            print(f"Loaded {len(self._segments)} segments from cache")
            return

        try:
            G = _download_and_cache_graph()
            if G is not None:
                self._segments = _generate_segments_from_graph(G)
        except Exception as e:
            print(f"OSMnx failed: {e}, using fallback segments")

        if not self._segments:
            self._segments = _generate_fallback_segments()

        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SEGMENTS_PATH, "w") as f:
            json.dump(self._segments, f)
        print(f"Generated {len(self._segments)} segments")

    def get_segments(self) -> list[dict]:
        return self._segments

    def get_snapshot(self) -> list[SegmentSpeed]:
        with self._lock:
            return list(self._snapshot)

    def get_simulated_hour(self) -> float:
        return self._simulated_hour

    def inject_incident(self, segment_id: str, speed_factor: float = 0.05):
        """Simulate incident on a segment (near-zero speed)."""
        self._incident_segment = segment_id
        self._incident_speed_factor = speed_factor

    def clear_incident(self):
        # Start congestion decay window instead of instant clear
        if self._incident_segment:
            self._decay_segment = self._incident_segment
            self._decay_start = time.time()
        self._incident_segment = None
        self._incident_speed_factor = 0.0

    def add_listener(self, callback: Callable):
        self._listeners.append(callback)

    def _generate_tick(self) -> FeedTick:
        """Generate one tick of speed data."""
        self._tick += 1
        # Use NYC wall-clock time
        now = datetime.now(NYC_TZ)
        self._simulated_hour = now.hour + now.minute / 60.0

        if now.hour != self._jitter_hour:
            self._jitter_hour = now.hour
            self._jitter = random.random()
        tod_factor = _time_of_day_factor(self._simulated_hour, self._jitter)
        speeds = []

        for seg in self._segments:
            ffs = seg["free_flow_speed"]

            # Base speed with time-of-day degradation
            base_speed = ffs * tod_factor

            # Gaussian noise (±15%)
            noise = np.random.normal(0, ffs * 0.08)
            speed = max(2.0, base_speed + noise)

            # Incident effect: affected segment and neighbors
            if self._incident_segment:
                if seg["segment_id"] == self._incident_segment:
                    speed = ffs * self._incident_speed_factor
                else:
                    # Proximity-based slowdown for nearby segments
                    inc_seg = next((s for s in self._segments if s["segment_id"] == self._incident_segment), None)
                    if inc_seg:
                        dist = _haversine(seg["lat"], seg["lon"], inc_seg["lat"], inc_seg["lon"])
                        if dist < 0.8:  # Within 800m
                            decay = max(0.3, dist / 0.8)
                            speed *= decay

            # Post-incident congestion decay (gradual recovery over 15 min)
            elif self._decay_segment and self._decay_start:
                elapsed_s = time.time() - self._decay_start
                if elapsed_s < self._decay_duration:
                    recovery = elapsed_s / self._decay_duration  # 0→1 over 15 min
                    decay_seg = next((s for s in self._segments if s["segment_id"] == self._decay_segment), None)
                    if decay_seg:
                        if seg["segment_id"] == self._decay_segment:
                            # Incident segment: recover from 5% → normal
                            speed = speed * (0.3 + 0.7 * recovery)
                        else:
                            dist = _haversine(seg["lat"], seg["lon"], decay_seg["lat"], decay_seg["lon"])
                            if dist < 0.8:
                                residual = max(0.0, 1.0 - recovery) * max(0.0, 1.0 - dist / 0.8) * 0.5
                                speed *= (1.0 - residual)
                else:
                    # Decay window expired
                    self._decay_segment = None
                    self._decay_start = None

            # Density from fundamental flow equation: density = flow / speed
            # flow ≈ proportional to time-of-day
            flow_factor = 1.0 - (tod_factor - 0.35) / 0.65
            density = max(5, min(120, (flow_factor * 80) / max(speed / ffs, 0.1)))

            speeds.append(SegmentSpeed(
                segment_id=seg["segment_id"],
                street_name=seg["street_name"],
                speed=round(speed, 1),
                free_flow_speed=ffs,
                lat=seg["lat"],
                lon=seg["lon"],
                bearing=seg.get("bearing", 0),
                density=round(density, 1),
            ))

        with self._lock:
            self._snapshot = speeds

        now = datetime.now(NYC_TZ)
        sim_time = now.replace(
            hour=int(self._simulated_hour),
            minute=int((self._simulated_hour % 1) * 60),
            second=now.second
        )

        return FeedTick(
            tick=self._tick,
            timestamp=sim_time.isoformat(),
            segments=speeds,
        )

    async def run(self, interval: float = 5.0):
        """Run the feed loop (call from async context)."""
        import asyncio
        self._running = True
        while self._running:
            tick = self._generate_tick()
            for listener in self._listeners:
                try:
                    if asyncio.iscoroutinefunction(listener):
                        await listener(tick)
                    else:
                        listener(tick)
                except Exception as e:
                    print(f"Feed listener error: {e}")
            await asyncio.sleep(interval)

    def stop(self):
        self._running = False

    def generate_single_tick(self) -> FeedTick:
        """Generate one tick synchronously (for testing)."""
        return self._generate_tick()


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in km between two points."""
    from math import radians, sin, cos, sqrt, atan2
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))
