"""
Anomaly Detector — Threshold-based detection + Bayesian severity forecast.
Triggers when segment drops >40% below rolling baseline OR risk_score > 0.75,
held on the same segment for PERSIST_TICKS consecutive ticks, and never during
the first WARMUP_TICKS ticks while baselines settle.
No LLM calls — pure statistical detection.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from models.schemas import SegmentSpeed, RiskEntry, IncidentDetection, Severity

# Bayesian conditional probability table for duration estimation
# Based on historical patterns (NYC collision data characteristics)
DURATION_TABLE = {
    Severity.LOW:      {"mean_min": 8,  "std_min": 3,  "p": 0.45},
    Severity.MEDIUM:   {"mean_min": 15, "std_min": 5,  "p": 0.30},
    Severity.HIGH:     {"mean_min": 35, "std_min": 10, "p": 0.18},
    Severity.CRITICAL: {"mean_min": 60, "std_min": 20, "p": 0.07},
}


WARMUP_TICKS = 12   # 1 minute at 5 s ticks
PERSIST_TICKS = 3   # condition must hold this many consecutive ticks


class AnomalyDetector:
    """Detects traffic incidents from speed feed and risk data."""

    def __init__(self):
        self._baselines: dict[str, float] = {}  # segment_id → rolling avg speed
        self._baseline_alpha = 0.1  # Exponential moving average factor
        self._incident_count = 0
        self._ticks_seen = 0
        self._streaks: dict[str, int] = {}  # segment_id → consecutive anomalous ticks

    def reset_warmup(self):
        """Restart the warm-up window (e.g. when auto-detection is switched on)."""
        self._ticks_seen = 0
        self._streaks.clear()

    def update_baselines(self, snapshot: list[SegmentSpeed]):
        """Update rolling baselines with new speed data."""
        self._ticks_seen += 1
        for seg in snapshot:
            if seg.segment_id in self._baselines:
                self._baselines[seg.segment_id] = (
                    (1 - self._baseline_alpha) * self._baselines[seg.segment_id]
                    + self._baseline_alpha * seg.speed
                )
            else:
                self._baselines[seg.segment_id] = seg.speed

    def detect(
        self,
        snapshot: list[SegmentSpeed],
        risk_map: list[RiskEntry],
    ) -> IncidentDetection | None:
        """
        Check for anomalies.
        Trigger conditions:
        1. Any segment drops >40% below its rolling baseline
        2. OR risk_score > 0.75
        Returns IncidentDetection if triggered, None otherwise.
        """
        risk_by_id = {r.segment_id: r for r in risk_map}
        warming_up = self._ticks_seen <= WARMUP_TICKS
        anomalous: set[str] = set()

        worst_segment = None
        worst_score = 0.0
        worst_reason = ""

        for seg in snapshot:
            baseline = self._baselines.get(seg.segment_id, seg.free_flow_speed)
            risk = risk_by_id.get(seg.segment_id)

            # Condition 1: Speed drop >40% below baseline
            if baseline > 0:
                drop_pct = (baseline - seg.speed) / baseline
                if drop_pct > 0.40:
                    anomalous.add(seg.segment_id)
                    score = drop_pct + (risk.score if risk else 0)
                    if score > worst_score and self._streaks.get(seg.segment_id, 0) + 1 >= PERSIST_TICKS:
                        worst_score = score
                        worst_segment = seg
                        worst_reason = f"Speed dropped {drop_pct*100:.0f}% below baseline ({baseline:.0f} → {seg.speed:.0f} mph)"

            # Condition 2: Risk score > 0.75
            if risk and risk.score > 0.75:
                anomalous.add(seg.segment_id)
                score = risk.score + 0.5
                if score > worst_score and self._streaks.get(seg.segment_id, 0) + 1 >= PERSIST_TICKS:
                    worst_score = score
                    worst_segment = seg
                    worst_reason = f"Risk score {risk.score:.2f} exceeds threshold (historical + speed + time-of-day)"

        # Update streaks: increment segments anomalous this tick, drop the rest
        self._streaks = {sid: self._streaks.get(sid, 0) + 1 for sid in anomalous}

        if worst_segment is None or warming_up:
            return None
        self._streaks.clear()

        # Determine severity
        severity = self._classify_severity(worst_score, worst_segment)
        duration = self._estimate_duration(severity)

        self._incident_count += 1

        return IncidentDetection(
            detected=True,
            incident_id=f"INC-BK-{self._incident_count:04d}",
            street_name=worst_segment.street_name,
            segment_id=worst_segment.segment_id,
            severity=severity,
            severity_tier=self._severity_to_tier(severity),
            duration_estimate_min=duration,
            lat=worst_segment.lat,
            lon=worst_segment.lon,
            timestamp=datetime.now(timezone.utc).isoformat(),
            description=worst_reason,
        )

    def _classify_severity(self, score: float, segment: SegmentSpeed) -> Severity:
        """Classify severity based on composite score."""
        if score > 1.5 or segment.speed < 3:
            return Severity.CRITICAL
        elif score > 1.2 or segment.speed < 8:
            return Severity.HIGH
        elif score > 0.9:
            return Severity.MEDIUM
        else:
            return Severity.LOW

    def _severity_to_tier(self, severity: Severity) -> int:
        return {Severity.LOW: 1, Severity.MEDIUM: 2, Severity.HIGH: 3, Severity.CRITICAL: 4}[severity]

    def _estimate_duration(self, severity: Severity) -> float:
        """Bayesian duration estimate from historical patterns."""
        entry = DURATION_TABLE[severity]
        # Sample from normal distribution centered on historical mean
        duration = max(5, random.gauss(entry["mean_min"], entry["std_min"]))
        return round(duration, 1)

    def force_incident(self, segment: SegmentSpeed, severity: Severity = Severity.HIGH) -> IncidentDetection:
        """Force an incident on a specific segment (for demo)."""
        self._incident_count += 1
        duration = self._estimate_duration(severity)

        descriptions = {
            Severity.LOW: "Minor fender bender reported, single lane partially blocked",
            Severity.MEDIUM: "Two-vehicle collision, right lane blocked, minor injuries reported",
            Severity.HIGH: "Multi-vehicle collision on {street}, two lanes blocked, emergency services dispatched",
            Severity.CRITICAL: "Severe multi-vehicle pile-up on {street}, all lanes blocked, multiple injuries, FDNY and NYPD on scene",
        }

        return IncidentDetection(
            detected=True,
            incident_id=f"INC-BK-{self._incident_count:04d}",
            street_name=segment.street_name,
            segment_id=segment.segment_id,
            severity=severity,
            severity_tier=self._severity_to_tier(severity),
            duration_estimate_min=duration,
            lat=segment.lat,
            lon=segment.lon,
            timestamp=datetime.now(timezone.utc).isoformat(),
            description=descriptions[severity].format(street=segment.street_name),
        )
