"""
Alert Agent — Generates three-format public alerts.
VMS (3 lines ≤20 chars), 15s radio script, 280-char tweet.
Uses Groq (gpt-oss-120b by default).
"""
from __future__ import annotations

from models.schemas import IncidentDetection, DiversionRoute, AlertDrafts
from core.llm import groq_chat, extract_json
from core.feed_engine import describe_time

VMS_WIDTH = 20
VMS_ABBREVIATIONS = {
    "AVENUE": "AVE", "STREET": "ST", "BOULEVARD": "BLVD", "PARKWAY": "PKWY",
    "EXPRESSWAY": "EXPY", "ROAD": "RD", "PLACE": "PL", "DRIVE": "DR",
    "ACCIDENT": "CRASH", "INCIDENT": "INCIDENT", "ALTERNATE": "ALT", "BROOKLYN": "BKLYN",
    "NORTHBOUND": "NB", "SOUTHBOUND": "SB", "EASTBOUND": "EB", "WESTBOUND": "WB",
}


def fit_vms(lines: list[str], width: int = VMS_WIDTH, rows: int = 3) -> list[str]:
    """Fit sign text into `rows` lines of at most `width` characters without cutting words.

    Each line keeps its own meaning: words are abbreviated (AVENUE -> AVE) and only a
    line that is still too long is wrapped onto extra lines. Anything beyond `rows`
    lines is dropped at a word boundary rather than cut mid-word.
    """
    out: list[str] = []
    for line in lines:
        words = [VMS_ABBREVIATIONS.get(w.strip(".,"), w)[:width] for w in str(line).upper().split()]
        current = ""
        for w in words:
            candidate = f"{current} {w}".strip()
            if len(candidate) <= width:
                current = candidate
            else:
                out.append(current)
                current = w
        if current:
            out.append(current)
    return [line for line in out if line][:rows]


SYSTEM_PROMPT = """You are a public information officer for Brooklyn, New York traffic management.
Generate THREE types of alerts for a traffic incident:

1. VMS (Variable Message Sign): EXACTLY 3 lines, each line MUST be ≤20 characters. 
   Use ALL CAPS. These appear on electronic highway signs.
   Use whole words. The ONLY allowed abbreviations are AVE, ST, BLVD, PKWY, EXPY, RD and
   NB/SB/EB/WB. Never shorten other words (write CRASH, not ACC or ACCID).
   
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
Time (Brooklyn): {describe_time()}
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

        # Enforce constraints: 3 lines, 20 chars, whole words only
        vms = fit_vms(parsed.get("vms", [])[:3])
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
        return AlertDrafts(
            vms=fit_vms(["INCIDENT AHEAD"]) + fit_vms([incident.street_name], rows=1) + ["USE ALT ROUTE"],
            radio_script=f"Brooklyn traffic advisory. A {incident.severity.value.lower()} severity incident "
                        f"has been reported on {incident.street_name}. Motorists are advised to seek alternate routes. "
                        f"Expect delays of approximately {incident.duration_estimate_min:.0f} minutes.",
            tweet=f"⚠️ Traffic Alert: {incident.severity.value} incident on {incident.street_name}, Brooklyn. "
                  f"Expect delays ~{incident.duration_estimate_min:.0f}min. Seek alternate routes. #BrooklynTraffic",
            source="fallback",
        )
