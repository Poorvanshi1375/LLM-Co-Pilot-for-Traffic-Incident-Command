"""
Multi-agent orchestration — wires all agents into one incident pipeline.
Flow: feed tick → [risk_scorer, anomaly_detector] → (if incident) →
      [signal_agent || routing_agent || density_agent] → alert_agent (with diversion)
      → supervisor → narrative context

The pipeline runs as a background task guarded by a lock, so the 5 s feed
keeps ticking while agents work and only one incident is processed at a time.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import TypedDict, Callable, Awaitable, Optional
from datetime import datetime, timezone

from models.schemas import (
    SegmentSpeed, RiskEntry, IncidentDetection, SignalRecommendation,
    DiversionRoute, AlertDrafts, DensityData, AgentOutput,
    TimelineEntry, Severity,
)
from core.feed_engine import FeedEngine
from core.risk_scorer import compute_risk_map
from core.anomaly_detector import AnomalyDetector
from core.weather_service import get_weather
from agents.signal_agent import run_signal_agent
from agents.routing_agent import run_routing_agent
from agents.alert_agent import run_alert_agent
from agents.density_agent import run_density_agent
from agents.supervisor import run_supervisor
from agents.narrative_agent import NarrativeAgent
from rag.retriever import retrieve_sops
from integrations.twitter_poster import post_tweet

TIMELINE_MAX = 200
PIPELINE_TIMEOUT_S = 90


class TrafficState(TypedDict):
    """Complete state for the traffic management pipeline."""
    # Data layer
    snapshot: list[SegmentSpeed]
    risk_map: list[RiskEntry]
    hour: float

    # Detection
    incident: IncidentDetection | None

    # Agent outputs
    signal_recommendations: list[SignalRecommendation]
    diversion: DiversionRoute | None
    alerts: AlertDrafts | None
    density: DensityData | None

    # Supervisor
    agent_output: AgentOutput | None
    rag_context: list[str]

    # Meta
    timeline: list[TimelineEntry]
    processing: bool
    last_update: str


class AlreadyProcessingError(Exception):
    """An incident is already being processed."""


class TrafficGraph:
    """Orchestrates the multi-agent traffic management pipeline."""

    def __init__(self, feed_engine: FeedEngine, on_event: Optional[Callable[[dict], Awaitable[None]]] = None):
        self.feed = feed_engine
        self.detector = AnomalyDetector()
        self.narrative = NarrativeAgent(feed_engine=feed_engine)
        self._on_event = on_event
        self._state: TrafficState = {
            "snapshot": [],
            "risk_map": [],
            "hour": 8.5,
            "incident": None,
            "signal_recommendations": [],
            "diversion": None,
            "alerts": None,
            "density": None,
            "agent_output": None,
            "rag_context": [],
            "timeline": [],
            "processing": False,
            "last_update": "",
        }
        self._incident_active = False
        self._auto_post = False
        self._auto_detect = os.getenv("AUTO_DETECT_INCIDENTS", "false").lower() == "true"
        self._pipeline_lock = asyncio.Lock()
        self._pipeline_done = asyncio.Event()
        self._pipeline_done.set()
        self._pipeline_task: asyncio.Task | None = None

    def get_state(self) -> TrafficState:
        return self._state

    def get_narrative_agent(self) -> NarrativeAgent:
        return self.narrative

    def set_auto_post(self, enabled: bool):
        self._auto_post = enabled

    def get_auto_post(self) -> bool:
        return self._auto_post

    def set_auto_detect(self, enabled: bool):
        self._auto_detect = enabled
        if enabled:
            self.detector.reset_warmup()

    def get_auto_detect(self) -> bool:
        return self._auto_detect

    def is_processing(self) -> bool:
        return self._state["processing"]

    async def wait_for_pipeline(self, timeout: float) -> bool:
        """Wait until the running pipeline finishes; False on timeout."""
        try:
            await asyncio.wait_for(self._pipeline_done.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def _log(self, event: str, category: str = "system"):
        self._state["timeline"].append(TimelineEntry(
            timestamp=datetime.now(timezone.utc).isoformat(), event=event, category=category,
        ))
        del self._state["timeline"][:-TIMELINE_MAX]

    async def _emit(self, data: dict):
        """Emit a WebSocket event if callback is registered."""
        if self._on_event:
            await self._on_event(data)

    async def process_tick(self, snapshot: list[SegmentSpeed], hour: float):
        """Process one tick of data through the pipeline."""
        self._state["snapshot"] = snapshot
        self._state["hour"] = hour
        self._state["last_update"] = datetime.now(timezone.utc).isoformat()

        # Step 1: Update baselines and compute risk
        self.detector.update_baselines(snapshot)
        risk_map = compute_risk_map(snapshot, hour)
        self._state["risk_map"] = risk_map

        # Step 2: Detect anomalies (only if enabled, idle, and no active incident)
        if not self._auto_detect or self._incident_active or self.is_processing():
            return
        detection = self.detector.detect(snapshot, risk_map)
        if detection and detection.detected:
            self._open_incident(detection, f"Incident detected: {detection.severity.value} on {detection.street_name}")
            await self._emit({"type": "incident_detected", "incident": detection.model_dump()})
            self._start_pipeline(detection, snapshot, risk_map)

    async def trigger_incident(self, segment_id: str | None = None, severity: Severity = Severity.HIGH):
        """Manually trigger an incident (for demo). Raises AlreadyProcessingError if busy."""
        if self.is_processing() or self._pipeline_lock.locked():
            raise AlreadyProcessingError()
        snapshot = self._state["snapshot"] or self.feed.get_snapshot()
        if not snapshot:
            return None

        if segment_id:
            target = next((s for s in snapshot if s.segment_id == segment_id), snapshot[0])
        else:
            # Pick a dramatic segment (Flatbush Ave or similar major road)
            target = next(
                (s for s in snapshot if "flatbush" in s.street_name.lower()),
                next(
                    (s for s in snapshot if "atlantic" in s.street_name.lower()),
                    snapshot[0]
                )
            )

        # Inject speed drop
        self.feed.inject_incident(target.segment_id, speed_factor=0.05)

        incident = self.detector.force_incident(target, severity)
        self._open_incident(incident, f"Incident triggered: {incident.severity.value} on {incident.street_name}")

        risk_map = compute_risk_map(snapshot, self._state["hour"])
        self._state["risk_map"] = risk_map

        await self._emit({"type": "incident_detected", "incident": incident.model_dump()})
        self._start_pipeline(incident, snapshot, risk_map)
        return incident

    def _open_incident(self, incident: IncidentDetection, event: str):
        self._state["incident"] = incident
        self._incident_active = True
        self._state["processing"] = True
        self._pipeline_done.clear()
        self._log(f"🚨 {event}", "detection")

    def _start_pipeline(self, incident: IncidentDetection, snapshot: list[SegmentSpeed], risk_map: list[RiskEntry]):
        self._pipeline_task = asyncio.create_task(self._run_agents(incident, snapshot, risk_map))

    async def _run_agents(
        self,
        incident: IncidentDetection,
        snapshot: list[SegmentSpeed],
        risk_map: list[RiskEntry],
    ):
        """Run all agents, then supervisor (background task, one at a time)."""
        async with self._pipeline_lock:
            self._state["processing"] = True
            try:
                await asyncio.wait_for(self._pipeline(incident, snapshot, risk_map), PIPELINE_TIMEOUT_S)
            except asyncio.TimeoutError:
                self._log(f"❌ Agent pipeline timed out after {PIPELINE_TIMEOUT_S}s", "error")
                await self._emit({"type": "agents_failed", "error": "timeout", "timeline": self._timeline_dump()})
            except Exception as e:  # noqa: BLE001 — report, never kill the server
                print(f"Agent pipeline error: {e}")
                self._log(f"❌ Agent pipeline error: {str(e)[:100]}", "error")
                await self._emit({"type": "agents_failed", "error": str(e)[:200], "timeline": self._timeline_dump()})
            finally:
                self._state["processing"] = False
                self._pipeline_done.set()

    async def _pipeline(
        self,
        incident: IncidentDetection,
        snapshot: list[SegmentSpeed],
        risk_map: list[RiskEntry],
    ):
        start = time.time()

        # RAG retrieval (fast, no LLM)
        rag_query = f"{incident.severity.value} incident {incident.street_name} {incident.description}"
        rag_context = retrieve_sops(rag_query, top_k=2)
        self._state["rag_context"] = rag_context

        try:
            weather_condition = (await get_weather()).condition
        except Exception:
            weather_condition = "clear"

        # Fan-out: signal, routing and density run in parallel
        results = await asyncio.gather(
            run_signal_agent(incident, snapshot, risk_map),
            run_routing_agent(incident, snapshot, risk_map, weather_condition),
            run_density_agent(snapshot),
            return_exceptions=True,
        )
        signals, diversion, density = (None if isinstance(r, BaseException) else r for r in results)
        for name, r in zip(("signal", "routing", "density"), results):
            if isinstance(r, BaseException):
                print(f"{name} agent crashed: {r}")

        # Alerts once, with the diversion so the public message names it
        alerts = await run_alert_agent(incident, diversion)

        if self._state["incident"] is not incident:
            return  # resolved while agents were running; discard results

        self._state["signal_recommendations"] = signals or []
        self._state["diversion"] = diversion
        self._state["alerts"] = alerts
        self._state["density"] = density

        # Fan-in: Supervisor
        agent_output = await run_supervisor(
            incident, signals or [], diversion, alerts, density, rag_context
        )
        agent_output.agent_status.update({
            "signal": {"source": signals[0].source if signals else "none", "error": ""},
            "routing": {"source": diversion.source if diversion else "none", "error": ""},
            "alerts": {"source": alerts.source, "error": ""},
        })

        if self._state["incident"] is not incident:
            return

        self._state["agent_output"] = agent_output
        for entry in agent_output.timeline:
            self._state["timeline"].append(entry)
        del self._state["timeline"][:-TIMELINE_MAX]

        # Update narrative agent context
        self.narrative.set_context(incident, agent_output, snapshot, risk_map)

        # Auto-post tweet if enabled
        if self._auto_post and alerts.tweet:
            tweet_result = await asyncio.to_thread(post_tweet, alerts.tweet)
            tweet_status = tweet_result.get("status", "unknown")
            if tweet_status == "posted":
                self._log(f"📱 Tweet posted: {tweet_result.get('url', '')}", "social")
            else:
                self._log(f"📱 Tweet {tweet_status}: {tweet_result.get('reason', 'unknown')}", "social")

        fallbacks = [k for k, v in agent_output.agent_status.items() if v.get("source") == "fallback"]
        elapsed = round(time.time() - start, 2)
        note = f" — rule-based fallback used for: {', '.join(fallbacks)}" if fallbacks else ""
        self._log(f"✅ All agents complete ({elapsed}s total){note}", "system")

        await self._emit({
            "type": "agents_complete",
            "output": agent_output.model_dump(),
            "timeline": self._timeline_dump(),
        })

    def _timeline_dump(self) -> list[dict]:
        return [t.model_dump() for t in self._state["timeline"]]

    async def resolve_incident(self):
        """Clear the active incident and everything derived from it."""
        self._incident_active = False
        self.feed.clear_incident()
        self._state["incident"] = None
        self._state["signal_recommendations"] = []
        self._state["diversion"] = None
        self._state["alerts"] = None
        self._state["density"] = None
        self._state["agent_output"] = None
        self._state["rag_context"] = []
        self.narrative.clear()
        self._log("✅ Incident resolved, returning to normal operations", "resolution")
        await self._emit({"type": "incident_resolved", "timeline": self._timeline_dump()})
