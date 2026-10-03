"""
Routing Agent — Real road diversion around the incident + LLM narration.
The path is a weighted shortest path on the Brooklyn road graph with every
node within 200 m of the incident blocked; edge cost = travel time × (1 + risk)
× weather penalty. Uses Groq for narration in officer-friendly language.
"""
from __future__ import annotations

import asyncio

from models.schemas import (
    SegmentSpeed, RiskEntry, IncidentDetection, DiversionRoute
)
from core.risk_scorer import _haversine
from core.route_finder import find_diversion
from core.llm import groq_chat, extract_json


def _compute_diversion_route(
    incident: IncidentDetection,
    snapshot: list[SegmentSpeed],
    risk_map: list[RiskEntry],
    weather_condition: str | None = None,
) -> dict | None:
    """Compute a road-following diversion and its stats, or None if no path exists."""
    path = find_diversion(
        incident.lat, incident.lon, incident.street_name,
        feed_snapshot=snapshot, risk_map=risk_map, weather_condition=weather_condition,
    )
    if not path or not path["street_names"]:
        return None

    # Risk change versus the normal route through the incident, under live conditions
    original_risk = path["direct_risk"]
    route_risk = path["avg_accident_score"]
    risk_delta = round((original_risk - route_risk) / original_risk * 100, 1) if original_risk > 0 else 0.0

    # The path starts and ends on the incident street (where drivers leave and
    # rejoin it); list only the detour streets so nobody reads "via the blocked street"
    via = [s for s in path["street_names"] if s != incident.street_name] or path["street_names"]

    # Volume redistribution from the flow model: blocked-zone density vs route density
    near = [s for s in snapshot if _haversine(incident.lat, incident.lon, s.lat, s.lon) < 0.3]
    blocked_density = sum(s.density for s in near) / max(len(near), 1)
    capacity_ratio = blocked_density / max(path["avg_density"] + blocked_density, 1)
    diversion_volume = round(min(50, max(10, capacity_ratio * 100)), 1)

    return {
        "route_names": via,
        "route_coords": path["coords"],
        "stats": {
            "risk_delta_pct": risk_delta,
            "diversion_volume_pct": diversion_volume,
            "time_delta_min": path["extra_minutes"],
            "length_km": path["total_length_km"],
            "avg_route_risk": route_risk,
            "blocked_streets": path["blocked_streets"],
        },
    }


NARRATION_PROMPT = """You are a traffic routing specialist for Brooklyn, New York.
Narrate a diversion route for a traffic officer managing an incident.

Use REAL street names, in the order given. Drivers leave the incident street before the
blocked zone and rejoin it after; never describe the incident street itself as part of the detour.
Explain:
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
    weather_condition: str | None = None,
) -> DiversionRoute | None:
    """Compute diversion route and narrate it."""

    try:
        route_data = await asyncio.to_thread(
            _compute_diversion_route, incident, snapshot, risk_map, weather_condition
        )
    except Exception as e:
        print(f"Routing agent: diversion search failed: {e}")
        return None
    if not route_data:
        return None

    stats = route_data["stats"]
    user_prompt = f"""INCIDENT: {incident.severity.value} on {incident.street_name}
Location: ({incident.lat}, {incident.lon})
Duration estimate: {incident.duration_estimate_min} minutes

DIVERSION ROUTE (risk-weighted shortest path on the road network, incident zone blocked):
Leave {incident.street_name} before the incident, then: {' → '.join(route_data['route_names'])}, then rejoin {incident.street_name}
Length: {stats['length_km']} km, about {stats['time_delta_min']} min longer than the direct route
Risk change: {stats['risk_delta_pct']}% versus staying on the normal route through the incident
Traffic redistribution: ~{stats['diversion_volume_pct']}% of volume diverted
Blocked streets near incident: {', '.join(stats['blocked_streets']) or incident.street_name}

Narrate this diversion for an officer. Return ONLY valid JSON."""

    base = dict(
        route_street_names=route_data["route_names"],
        route_coords=route_data["route_coords"],
        risk_delta_pct=stats["risk_delta_pct"],
        diversion_volume_pct=stats["diversion_volume_pct"],
        time_delta_min=stats["time_delta_min"],
        avoids_street=incident.street_name,
    )

    try:
        content = await groq_chat(
            [
                {"role": "system", "content": NARRATION_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=800,
            temperature=0.3,
            json_mode=True,
        )
        parsed = extract_json(content)
        if not isinstance(parsed, dict):
            raise ValueError("narration was not a JSON object")

        return DiversionRoute(
            **base,
            diversion_text=parsed.get("diversion_text", ""),
            confidence=min(1.0, max(0.0, float(parsed.get("confidence", 0.7)))),
            why_safer=parsed.get("why_safer", ""),
        )

    except Exception as e:
        print(f"Routing agent error: {e}")
        return DiversionRoute(
            **base,
            diversion_text=(
                f"Leave {incident.street_name} before the incident, take {' → '.join(route_data['route_names'][:6])}, "
                f"then rejoin {incident.street_name} past the blocked zone"
            ),
            confidence=0.5,
            why_safer="Route avoids the blocked incident zone with a lower average risk score",
            source="fallback",
        )
