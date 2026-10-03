"""
End-to-end checks against a running backend.

    TM_BASE_URL=http://localhost:8000 pytest tests -v          # local
    TM_BASE_URL=https://trafficmind-backend.onrender.com pytest tests -v   # deployed

Tests are skipped when the backend is unreachable. The trigger test calls the
real LLMs, so it needs working keys to see "llm" sources (it still passes on
rule-based fallbacks, and prints which agents fell back).
"""
from __future__ import annotations

import os
import time
from math import radians, sin, cos, sqrt, atan2

import httpx
import pytest

BASE = os.getenv("TM_BASE_URL", "http://localhost:8000").rstrip("/")


def _km(a, b) -> float:
    (lon1, lat1), (lon2, lat2) = a, b
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 6371 * 2 * atan2(sqrt(h), sqrt(1 - h))


@pytest.fixture(scope="session")
def client():
    c = httpx.Client(base_url=BASE, timeout=120)
    try:
        c.get("/health", timeout=90).raise_for_status()
    except Exception as e:
        pytest.skip(f"backend not reachable at {BASE}: {e}")
    # Wait for the road graph to finish loading in the background
    for _ in range(60):
        if c.get("/health").json().get("road_graph_loaded"):
            break
        time.sleep(2)
    yield c
    c.post("/api/resolve-incident")
    c.close()


def test_health_reports_llm_and_graph(client):
    h = client.get("/health").json()
    assert h["status"] == "ok"
    assert h["segments"] > 0
    assert h["road_graph_loaded"] is True
    assert {"groq", "gemini"} <= set(h["llm"])


def test_predicted_hotspots_are_fast(client):
    start = time.time()
    r = client.get("/api/hotspots/predicted")
    assert r.status_code == 200
    assert len(r.json()["clusters"]) > 0
    assert time.time() - start < 5


def test_routes_follow_roads_with_real_minutes(client):
    r = client.post("/api/routes", json={
        "origin_lat": 40.6826, "origin_lon": -73.9754,  # Barclays Center
        "dest_lat": 40.6602, "dest_lon": -73.9690,      # Prospect Park
        "k": 3, "vehicle_type": "normal",
    })
    assert r.status_code == 200
    routes = r.json()["routes"]
    assert routes, "no routes returned"
    for route in routes:
        coords = route["coords"]
        assert len(coords) > 2
        assert max(_km(a, b) for a, b in zip(coords, coords[1:])) < 1.0  # no straight jumps
        # Minutes must be plausible for the distance (between 3 and 60 mph average)
        km, minutes = route["total_length_km"], route["total_travel_time_min"]
        mph = (km / 1.609) / (minutes / 60)
        assert 3 <= mph <= 60, f"{km} km in {minutes} min"
        assert route["color"] in ("#10B981", "#F59E0B", "#EF4444")


def test_auto_post_cannot_be_enabled_publicly(client):
    r = client.post("/api/settings/auto-post", json={"enabled": True})
    assert r.status_code in (401, 403)


def test_cors_rejects_unknown_origin(client):
    r = client.get("/health", headers={"Origin": "https://example.com"})
    assert "access-control-allow-origin" not in r.headers


def test_incident_lifecycle(client):
    client.post("/api/resolve-incident")

    r = client.post("/api/trigger-incident", json={"severity": "HIGH"})
    if r.status_code == 429:
        pytest.skip("trigger cooldown active from an earlier run; retry in 30 s")
    assert r.status_code == 200, r.text
    data = r.json()
    incident = data["incident"]
    assert incident["severity"] == "HIGH"

    # Wait for agents if the endpoint returned before they finished
    output = data["agent_output"]
    for _ in range(30):
        if output:
            break
        time.sleep(2)
        output = client.get("/api/agents").json()["agent_output"]
    assert output, "agents never completed"

    status = output["agent_status"]
    fallbacks = [k for k, v in status.items() if v.get("source") == "fallback"]
    print(f"agent sources: {status} (fallbacks: {fallbacks or 'none'})")

    assert output["signal_recommendations"]
    for rec in output["signal_recommendations"]:
        a, _, b = rec["intersection_name"].partition(" & ")
        assert a != b, "street crossing itself"

    # Diversion follows roads and stays out of the blocked zone
    div = output["diversion"]
    assert div, "no diversion route"
    coords = div["route_coords"]
    assert len(coords) > 2
    assert max(_km(a, b) for a, b in zip(coords, coords[1:])) < 1.0
    inc = (incident["lon"], incident["lat"])
    assert min(_km(inc, c) for c in coords) > 0.15

    vms = output["alerts"]["vms"]
    assert len(vms) == 3 and all(len(line) <= 20 for line in vms)
    assert len(output["alerts"]["tweet"]) <= 280

    # A second trigger right away is refused
    again = client.post("/api/trigger-incident", json={"severity": "HIGH"})
    assert again.status_code in (409, 429)

    # Resolve clears everything derived from the incident
    client.post("/api/resolve-incident")
    agents = client.get("/api/agents").json()
    assert agents["status"] == "no_incident"
    assert client.get("/api/state").json()["incident"] is None


def test_place_search_finds_brooklyn_landmarks(client):
    r = client.get("/api/geocode", params={"q": "Barclays Center"})
    if r.status_code == 500 and "MAPBOX_TOKEN" in r.text:
        pytest.skip("MAPBOX_TOKEN not configured on this backend")
    assert r.status_code == 200
    hits = r.json()["suggestions"]
    assert hits, "no suggestions"
    top = hits[0]
    assert "Brooklyn" in top["place_name"]
    assert _km((top["lon"], top["lat"]), (-73.9754, 40.6826)) < 0.5
