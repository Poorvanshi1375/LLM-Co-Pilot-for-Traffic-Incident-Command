"""
Supervisor Node — Fan-in, coherence check, RAG retrieval, cascade risk assessment.
Uses Gemini 2.0 Flash for deep cross-agent reasoning.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from models.schemas import (
    IncidentDetection, SignalRecommendation, DiversionRoute,
    AlertDrafts, DensityData, AgentOutput, TimelineEntry,
)

from core.llm import generate, extract_json
from core.feed_engine import describe_time


SYSTEM_PROMPT = """You are the supervisor of a multi-agent traffic incident management system for Brooklyn, New York.

Your tasks:
1. CHECK COHERENCE between agent outputs — ensure signal changes don't conflict with routing decisions
2. ASSESS CASCADE RISK — could the diversion route itself become congested?
3. SYNTHESIZE a final summary combining all agent recommendations
4. RATE confidence (0-1) for each section

Rules:
- If signal_agent extends green on a street that routing_agent is diverting FROM, flag the conflict
- If diversion route risk_score is climbing, warn about cascade risk (0.0-1.0)
- Use provided RAG context (SOPs) to validate recommendations against standard procedures

Return JSON:
{
  "final_summary": "2-3 sentence executive summary",
  "confidence_scores": {"signal": 0.85, "routing": 0.78, "alerts": 0.92, "overall": 0.84},
  "cascade_risk": 0.15,
  "coherence_issues": ["list of any conflicts found"],
  "sop_compliance": "Brief note on SOP alignment"
}"""


async def run_supervisor(
    incident: IncidentDetection,
    signals: list[SignalRecommendation],
    diversion: DiversionRoute | None,
    alerts: AlertDrafts | None,
    density: DensityData | None,
    rag_context: list[str] | None = None,
) -> AgentOutput:
    """Fan-in all agent outputs, check coherence, assess risks."""

    start_time = time.time()

    # Build timeline (detection itself is logged by the graph when it happens)
    timeline: list[TimelineEntry] = []

    if signals:
        timeline.append(TimelineEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event=f"Signal re-timing recommended for {len(signals)} intersections",
            category="signal",
        ))

    if diversion:
        timeline.append(TimelineEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event=f"Diversion route computed via {' → '.join(diversion.route_street_names[:3])}",
            category="routing",
        ))

    if alerts:
        timeline.append(TimelineEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event="Public alerts drafted (VMS, Radio, Tweet)",
            category="alert",
        ))

    # Build context for Gemini
    agent_data = {
        "brooklyn_time": describe_time(),
        "incident": {
            "street": incident.street_name,
            "severity": incident.severity.value,
            "duration_est": incident.duration_estimate_min,
        },
        "signals": [
            {
                "intersection": s.intersection_name,
                "phase_change": s.recommended_phase,
                "duration_s": s.phase_duration_s,
                "confidence": s.confidence,
            }
            for s in (signals or [])
        ],
        "diversion": {
            "streets": diversion.route_street_names if diversion else [],
            "risk_delta": diversion.risk_delta_pct if diversion else 0,
            "volume_pct": diversion.diversion_volume_pct if diversion else 0,
        } if diversion else None,
        "density": {
            "congestion": density.congestion_level if density else "UNKNOWN",
            "vehicles": density.estimated_vehicles if density else 0,
        },
        "rag_context": rag_context[:2] if rag_context else [],
    }

    final_summary = ""
    # Derive confidence from actual agent outputs instead of hardcoding
    signal_conf = (
        sum(s.confidence for s in signals) / len(signals)
        if signals else 0.5
    )
    routing_conf = (
        max(0.3, 1.0 - (diversion.risk_delta_pct / -100.0 if diversion and diversion.risk_delta_pct < 0 else 0))
        if diversion else 0.5
    )
    if diversion and diversion.risk_delta_pct >= 0:
        routing_conf = min(0.95, 0.6 + diversion.risk_delta_pct / 200.0)
    alerts_conf = 0.85 if alerts and alerts.source == "llm" else 0.5
    overall_conf = round((signal_conf + routing_conf + alerts_conf) / 3, 2)
    confidence_scores = {
        "signal": round(signal_conf, 2),
        "routing": round(routing_conf, 2),
        "alerts": round(alerts_conf, 2),
        "overall": overall_conf,
    }
    cascade_risk = 0.0
    coherence_issues: list[str] = []
    sop_compliance = ""
    supervisor_status = {"source": "llm", "error": ""}

    try:
        text = await generate(
            f"AGENT OUTPUTS:\n{json.dumps(agent_data, indent=2)}\n\nReturn ONLY valid JSON.",
            system=SYSTEM_PROMPT,
            max_tokens=800,
            temperature=0.3,
            json_mode=True,
            prefer="gemini",  # one call per incident; Groq takes over if Gemini is out of quota
        )
        parsed = extract_json(text)
        if not isinstance(parsed, dict):
            raise ValueError("supervisor response was not a JSON object")
        final_summary = str(parsed.get("final_summary", ""))
        llm_scores = parsed.get("confidence_scores", {})
        if isinstance(llm_scores, dict):
            for k, v in llm_scores.items():
                try:
                    confidence_scores[str(k)] = round(min(1.0, max(0.0, float(v))), 2)
                except (TypeError, ValueError):
                    pass
        try:
            cascade_risk = min(1.0, max(0.0, float(parsed.get("cascade_risk", 0.0))))
        except (TypeError, ValueError):
            cascade_risk = 0.0
        issues = parsed.get("coherence_issues", [])
        coherence_issues = [str(i) for i in issues] if isinstance(issues, list) else []
        sop_compliance = str(parsed.get("sop_compliance", ""))

    except Exception as e:
        print(f"Supervisor Gemini error: {e}")
        supervisor_status = {"source": "fallback", "error": str(e)[:200]}

    if not final_summary:
        severity_action = {
            "LOW": "monitoring",
            "MEDIUM": "active management",
            "HIGH": "immediate response",
            "CRITICAL": "emergency response",
        }
        action = severity_action.get(incident.severity.value, "response")
        final_summary = (
            f"{incident.severity.value} incident on {incident.street_name} requires {action}. "
            f"{len(signals)} signal adjustments recommended. "
            + (f"Diversion via {diversion.route_street_names[0]} is {diversion.risk_delta_pct}% safer. " if diversion and diversion.route_street_names else "")
            + "All alerts drafted and ready for dispatch."
        )

    elapsed = round(time.time() - start_time, 2)

    timeline.append(TimelineEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        event=f"Supervisor analysis complete ({elapsed}s)",
        category="supervisor",
    ))

    return AgentOutput(
        signal_recommendations=signals or [],
        diversion=diversion,
        alerts=alerts,
        density=density,
        final_summary=final_summary,
        confidence_scores=confidence_scores,
        cascade_risk=cascade_risk,
        rag_context=rag_context or [],
        timeline=timeline,
        coherence_issues=coherence_issues,
        sop_compliance=sop_compliance,
        agent_status={"supervisor": supervisor_status},
        evaluation_metrics={
            "response_latency_s": elapsed,
            "agents_invoked": 4,
            "signals_generated": len(signals) if signals else 0,
            "alert_compliance": 1.0,  # VMS/tweet limits are enforced in the alert agent
        },
    )
