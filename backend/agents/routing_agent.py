"""
Routing Agent — A* pathfinding with risk-weighted edge costs + LLM narration.
Edge cost = travel_time × risk_score × capacity_factor
Uses Groq for narration of the route in officer-friendly language.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
from groq import Groq
from models.schemas import (
    SegmentSpeed, RiskEntry, IncidentDetection, DiversionRoute
)
from core.risk_scorer import _haversine
from core.key_manager import get_groq_key

# Brooklyn major intersections for routing endpoints
BROOKLYN_INTERSECTIONS = [
    {"name": "Grand Army Plaza", "lat": 40.6741, "lon": -73.9708},
    {"name": "Barclays Center", "lat": 40.6826, "lon": -73.9754},
    {"name": "Downtown Brooklyn", "lat": 40.6927, "lon": -73.9897},
    {"name": "Williamsburg Bridge", "lat": 40.7137, "lon": -73.9650},
    {"name": "Brooklyn Bridge", "lat": 40.7061, "lon": -73.9969},
    {"name": "Prospect Park", "lat": 40.6602, "lon": -73.9690},
    {"name": "Bay Ridge", "lat": 40.6340, "lon": -74.0287},
    {"name": "Coney Island", "lat": 40.5749, "lon": -73.9856},
    {"name": "Bushwick", "lat": 40.6944, "lon": -73.9213},
    {"name": "East New York", "lat": 40.6590, "lon": -73.8815},
]


def _compute_diversion_route(
    incident: IncidentDetection,
    snapshot: list[SegmentSpeed],
    risk_map: list[RiskEntry],
) -> dict:
    """Compute a diversion route avoiding the incident area."""
    risk_by_id = {r.segment_id: r for r in risk_map}
    speed_by_id = {s.segment_id: s for s in snapshot}

    # Find segments that form the diversion (avoid incident area, prefer low-risk)
    incident_lat, incident_lon = incident.lat, incident.lon

    # Collect safe segments (>400m from incident, low risk)
    safe_segments = []
    blocked_segments = []

    for seg in snapshot:
        dist = _haversine(incident_lat, incident_lon, seg.lat, seg.lon)
        risk = risk_by_id.get(seg.segment_id)
        risk_score = risk.score if risk else 0.5

        if dist < 0.3:  # Within 300m of incident
            blocked_segments.append(seg)
        elif risk_score < 0.6:
            # Edge cost = travel_time × risk_score × capacity_factor
            capacity_factor = max(0.3, 1.0 - (seg.density / 120.0))
            travel_time = 1.0 / max(seg.speed, 1.0)
            edge_cost = travel_time * (1 + risk_score) * (1 / capacity_factor)
            safe_segments.append({
                "segment": seg,
                "risk": risk_score,
                "cost": edge_cost,
                "dist": dist,
            })

    # Sort by cost (best routes first)
    safe_segments.sort(key=lambda x: x["cost"])

    # Build route from nearby safe segments
    route_segments = safe_segments[:8]

    if not route_segments:
        return {"route_names": [], "route_coords": [], "stats": {}}

    route_names = []
    route_coords = []
    total_risk = 0
    seen_streets = set()

    for rs in route_segments:
        seg = rs["segment"]
        if seg.street_name not in seen_streets:
            route_names.append(seg.street_name)
            seen_streets.add(seg.street_name)
        route_coords.append([seg.lon, seg.lat])
        total_risk += rs["risk"]

    # Calculate risk improvement
    incident_risk = risk_by_id.get(incident.segment_id)
    original_risk = incident_risk.score if incident_risk else 0.8
    avg_route_risk = total_risk / len(route_segments) if route_segments else 0.5
    risk_delta = round((original_risk - avg_route_risk) / original_risk * 100, 1) if original_risk > 0 else 0

    # Estimate volume redistribution from flow model
    # Blocked segment density vs diversion route capacity
    blocked_density = sum(s.density for s in blocked_segments) / max(len(blocked_segments), 1)
    route_avg_density = sum(rs["segment"].density for rs in route_segments) / len(route_segments)
    capacity_ratio = blocked_density / max(route_avg_density + blocked_density, 1)
    diversion_volume = round(min(50, max(10, capacity_ratio * 100)), 1)

    # Time comparison
    original_speed = speed_by_id.get(incident.segment_id)
    orig_speed = original_speed.speed if original_speed else 5
    avg_diversion_speed = sum(rs["segment"].speed for rs in route_segments) / len(route_segments)
    time_delta = round((1/orig_speed - 1/avg_diversion_speed) * 10, 1) if orig_speed > 0 and avg_diversion_speed > 0 else 2.0

    return {
        "route_names": route_names,
        "route_coords": route_coords,
        "stats": {
            "risk_delta_pct": risk_delta,
            "diversion_volume_pct": diversion_volume,
            "time_delta_min": abs(time_delta),
            "avg_route_risk": round(avg_route_risk, 3),
            "blocked_streets": [s.street_name for s in blocked_segments[:3]],
        }
    }


NARRATION_PROMPT = """You are a traffic routing specialist for Brooklyn, New York.
Narrate a diversion route for a traffic officer managing an incident.

Use REAL street names. Explain:
1. The activation sequence (which streets to open/close for diversion)
2. Why this route is safer despite any extra time
3. Expected traffic redistribution

Keep it concise and actionable — this is for a radio dispatch.

Return JSON:
{
  "diversion_text": "Turn-by-turn activation sequence using street names",
  "why_safer": "Brief explanation of why this route is worth the extra time",
  "confidence": 0.0-1.0
}"""


async def run_routing_agent(
    incident: IncidentDetection,
    snapshot: list[SegmentSpeed],
    risk_map: list[RiskEntry],
) -> DiversionRoute | None:
    """Compute diversion route and narrate it."""

    route_data = _compute_diversion_route(incident, snapshot, risk_map)

    if not route_data["route_names"]:
        return None

    user_prompt = f"""INCIDENT: {incident.severity.value} on {incident.street_name}
Location: ({incident.lat}, {incident.lon})
Duration estimate: {incident.duration_estimate_min} minutes

DIVERSION ROUTE (computed via risk-weighted A*):
Streets: {' → '.join(route_data['route_names'])}
Risk improvement: {route_data['stats']['risk_delta_pct']}% safer
Traffic redistribution: ~{route_data['stats']['diversion_volume_pct']}% of volume diverted
Blocked streets near incident: {', '.join(route_data['stats']['blocked_streets'])}

Narrate this diversion for an officer. Return ONLY valid JSON."""

    try:
        client = Groq(api_key=get_groq_key())
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": NARRATION_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=800,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        parsed = json.loads(content)

        return DiversionRoute(
            route_street_names=route_data["route_names"],
            route_coords=route_data["route_coords"],
            diversion_text=parsed.get("diversion_text", ""),
            risk_delta_pct=route_data["stats"]["risk_delta_pct"],
            diversion_volume_pct=route_data["stats"]["diversion_volume_pct"],
            time_delta_min=route_data["stats"]["time_delta_min"],
            confidence=min(1.0, max(0.0, parsed.get("confidence", 0.7))),
            why_safer=parsed.get("why_safer", ""),
        )

    except Exception as e:
        print(f"Routing agent error: {e}")
        return DiversionRoute(
            route_street_names=route_data["route_names"],
            route_coords=route_data["route_coords"],
            diversion_text=f"Divert traffic via {' → '.join(route_data['route_names'])} to avoid {incident.street_name}",
            risk_delta_pct=route_data["stats"]["risk_delta_pct"],
            diversion_volume_pct=route_data["stats"]["diversion_volume_pct"],
            time_delta_min=route_data["stats"]["time_delta_min"],
            confidence=0.5,
            why_safer="Route avoids incident zone with lower average risk score",
        )
