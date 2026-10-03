"""
Alert Agent — Generates three-format public alerts.
VMS (3 lines ≤20 chars), 15s radio script, 280-char tweet.
Uses Groq (gpt-oss-120b by default).
"""
from __future__ import annotations

from models.schemas import IncidentDetection, DiversionRoute, AlertDrafts
from core.llm import groq_chat, extract_json

SYSTEM_PROMPT = """You are a public information officer for Brooklyn, New York traffic management.
Generate THREE types of alerts for a traffic incident:

1. VMS (Variable Message Sign): EXACTLY 3 lines, each line MUST be ≤20 characters. 
   Use ALL CAPS. These appear on electronic highway signs.
   
2. Radio Script: A 15-second spoken broadcast (roughly 35-40 words). 
   Natural speech, include "Brooklyn traffic advisory" opening.

3. Tweet: MUST be ≤280 characters. Include #BrooklynTraffic hashtag.
   Professional tone, include key details and diversion info.

Return ONLY valid JSON:
{
  "vms": ["LINE 1 MAX 20CH", "LINE 2 MAX 20CH", "LINE 3 MAX 20CH"],
  "radio_script": "Brooklyn traffic advisory...",
  "tweet": "Tweet text here #BrooklynTraffic"
}"""


async def run_alert_agent(
    incident: IncidentDetection,
    diversion: DiversionRoute | None = None,
) -> AlertDrafts:
    """Generate public alerts for the incident."""

    diversion_info = ""
    if diversion:
        diversion_info = f"""
DIVERSION: Traffic being rerouted via {' → '.join(diversion.route_street_names[:3])}
Volume redistribution: ~{diversion.diversion_volume_pct}% diverted"""

    user_prompt = f"""INCIDENT DETAILS:
Type: {incident.severity.value} traffic incident
Location: {incident.street_name}, Brooklyn
Time: {incident.timestamp}
Description: {incident.description}
Estimated duration: {incident.duration_estimate_min} minutes
{diversion_info}

Generate all three alert formats. Return ONLY valid JSON."""

    try:
        content = await groq_chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=600,
            temperature=0.4,
            json_mode=True,
        )
        parsed = extract_json(content)
        if not isinstance(parsed, dict):
            raise ValueError("alerts were not a JSON object")

        vms = parsed.get("vms", [])
        # Enforce constraints
        vms = [str(line)[:20].upper() for line in vms[:3]]
        while len(vms) < 3:
            vms.append("USE ALT ROUTE")

        radio = parsed.get("radio_script", "")
        tweet = parsed.get("tweet", "")[:280]

        return AlertDrafts(
            vms=vms,
            radio_script=radio,
            tweet=tweet,
        )

    except Exception as e:
        print(f"Alert agent error: {e}")
        # Fallback alerts
        street_short = incident.street_name[:20].upper()
        return AlertDrafts(
            vms=[
                "INCIDENT AHEAD",
                street_short,
                "USE ALT ROUTE",
            ],
            radio_script=f"Brooklyn traffic advisory. A {incident.severity.value.lower()} severity incident "
                        f"has been reported on {incident.street_name}. Motorists are advised to seek alternate routes. "
                        f"Expect delays of approximately {incident.duration_estimate_min:.0f} minutes.",
            tweet=f"⚠️ Traffic Alert: {incident.severity.value} incident on {incident.street_name}, Brooklyn. "
                  f"Expect delays ~{incident.duration_estimate_min:.0f}min. Seek alternate routes. #BrooklynTraffic",
            source="fallback",
        )
