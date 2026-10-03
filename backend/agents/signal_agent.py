"""
Signal Agent — Recommends signal re-timing for upstream intersections.
Uses Groq (gpt-oss-120b by default) for fast inference.
600m pre-emptive upstream window.
"""
from __future__ import annotations

import json

from models.schemas import (
    SegmentSpeed, RiskEntry, IncidentDetection, SignalRecommendation
)
from core.risk_scorer import _haversine
from core.llm import groq_chat, extract_json

SYSTEM_PROMPT = """You are a traffic signal timing expert for Brooklyn, New York.
You receive real-time traffic data and must recommend signal phase changes for intersections
near and upstream of a traffic incident.

CRITICAL RULES:
- Use REAL street names only, never node IDs or segment IDs
- Recommend exact phase durations in seconds
- Focus on intersections within 600m UPSTREAM of the incident (pre-emptive)
- Explain WHY each change helps (queue prevention, flow management)
- Provide confidence (0.0-1.0) for each recommendation
- Include one-line sensor data citation for each recommendation

Return a JSON object {"recommendations": [...]} whose items have these fields:
{
  "intersection_name": "Street A & Street B",
  "current_phase": "NS: 45s green, EW: 30s green",
  "recommended_phase": "NS: 30s green, EW: 45s green",
  "phase_duration_s": 45,
  "reason": "Extending EW green to flush queue before it reaches incident on Street A",
  "confidence": 0.85,
  "sensor_citation": "Speed sensor: Street A at 12mph (baseline 30mph), 40% below normal",
  "upstream_distance_m": 350
}"""


def _find_upstream_intersections(
    incident: IncidentDetection,
    snapshot: list[SegmentSpeed],
    risk_map: list[RiskEntry],
    radius_km: float = 0.6,
) -> list[dict]:
    """Find congested segments within 600m upstream of incident."""
    nearby = []
    risk_by_id = {r.segment_id: r for r in risk_map}

    for seg in snapshot:
        dist = _haversine(incident.lat, incident.lon, seg.lat, seg.lon)
        if dist <= radius_km:
            risk = risk_by_id.get(seg.segment_id)
            nearby.append({
                "street_name": seg.street_name,
                "speed": seg.speed,
                "free_flow_speed": seg.free_flow_speed,
                "speed_pct": round(seg.speed / seg.free_flow_speed * 100, 1) if seg.free_flow_speed > 0 else 0,
                "risk_score": risk.score if risk else 0,
                "distance_m": round(dist * 1000),
                "density": seg.density,
            })

    # Sort by congestion severity (lowest speed first)
    nearby.sort(key=lambda x: x["speed"])
    return nearby[:8]  # Top 8 most congested


async def run_signal_agent(
    incident: IncidentDetection,
    snapshot: list[SegmentSpeed],
    risk_map: list[RiskEntry],
) -> list[SignalRecommendation]:
    """Generate signal re-timing recommendations."""

    upstream = _find_upstream_intersections(incident, snapshot, risk_map)

    if not upstream:
        return []

    user_prompt = f"""INCIDENT: {incident.severity.value} severity on {incident.street_name}
Location: ({incident.lat}, {incident.lon})
Description: {incident.description}
Estimated duration: {incident.duration_estimate_min} minutes

UPSTREAM SEGMENTS (within 600m):
{json.dumps(upstream, indent=2)}

Generate signal re-timing recommendations for 2-4 key intersections near these segments.
Focus on pre-emptive queue prevention — adjust signals BEFORE the queue reaches the incident.
Return ONLY the JSON object."""

    try:
        content = await groq_chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1000,
            temperature=0.3,
            json_mode=True,
        )
        parsed = extract_json(content)

        # Handle both direct array and wrapped object
        if isinstance(parsed, dict):
            parsed = parsed.get("recommendations", parsed.get("signals", [parsed]))
        if not isinstance(parsed, list):
            parsed = [parsed]

        recommendations = []
        for item in parsed[:4]:
            recommendations.append(SignalRecommendation(
                intersection_name=item.get("intersection_name", "Unknown"),
                current_phase=item.get("current_phase", ""),
                recommended_phase=item.get("recommended_phase", ""),
                phase_duration_s=item.get("phase_duration_s", 30),
                reason=item.get("reason", ""),
                confidence=min(1.0, max(0.0, item.get("confidence", 0.7))),
                sensor_citation=item.get("sensor_citation", ""),
                upstream_distance_m=item.get("upstream_distance_m", 0),
            ))

        if not recommendations:
            raise ValueError("model returned no recommendations")
        return recommendations

    except Exception as e:
        print(f"Signal agent error: {e}")
        # Fallback: rule-based recommendations from cross streets near the incident
        cross_streets, seen = [], {incident.street_name}
        for s in upstream:
            if s["street_name"] not in seen:
                seen.add(s["street_name"])
                cross_streets.append(s)
        recs = []
        for seg in cross_streets[:3]:
            recs.append(SignalRecommendation(
                intersection_name=f"{seg['street_name']} near {incident.street_name}",
                current_phase="Standard cycle",
                recommended_phase=f"Extend green away from incident ({seg['street_name']})",
                phase_duration_s=45,
                reason=f"Speed at {seg['speed']:.0f}mph ({seg['speed_pct']}% of normal) — extend green to flush queue",
                confidence=0.6,
                sensor_citation=f"Speed sensor: {seg['speed']:.0f}mph on {seg['street_name']}, {seg['distance_m']}m from incident",
                upstream_distance_m=seg["distance_m"],
                source="fallback",
            ))
        return recs
