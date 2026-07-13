"""
Alert Agent — Generates three-format public alerts.
VMS (3 lines ≤20 chars), 15s radio script, 280-char tweet.
Uses Groq (Llama 3.3 70B).
"""
from __future__ import annotations

import asyncio
import json
import os
from groq import Groq
from models.schemas import IncidentDetection, DiversionRoute, AlertDrafts
from core.key_manager import get_groq_key

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
        client = Groq(api_key=get_groq_key())
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_tokens=600,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        parsed = json.loads(content)

        vms = parsed.get("vms", [])
        # Enforce constraints
        vms = [line[:20].upper() for line in vms[:3]]
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
        street_short = incident.street_name[:16]
        return AlertDrafts(
            vms=[
                f"INCIDENT AHEAD",
                f"{street_short}",
                "USE ALT ROUTE",
            ],
            radio_script=f"Brooklyn traffic advisory. A {incident.severity.value.lower()} severity incident "
                        f"has been reported on {incident.street_name}. Motorists are advised to seek alternate routes. "
                        f"Expect delays of approximately {incident.duration_estimate_min:.0f} minutes.",
            tweet=f"⚠️ Traffic Alert: {incident.severity.value} incident on {incident.street_name}, Brooklyn. "
                  f"Expect delays ~{incident.duration_estimate_min:.0f}min. Seek alternate routes. #BrooklynTraffic",
        )
