"""Pydantic models for TrafficMind backend."""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
import datetime


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SegmentSpeed(BaseModel):
    segment_id: str
    street_name: str
    speed: float
    free_flow_speed: float
    lat: float
    lon: float
    bearing: float = 0.0
    density: float = 0.0


class FeedTick(BaseModel):
    tick: int
    timestamp: str
    segments: list[SegmentSpeed]


class RiskEntry(BaseModel):
    segment_id: str
    street_name: str
    score: float
    speed_deviation: float
    historical_rate: float
    tod_weight: float
    lat: float
    lon: float


class IncidentDetection(BaseModel):
    detected: bool = False
    incident_id: str = ""
    street_name: str = ""
    segment_id: str = ""
    severity: Severity = Severity.LOW
    severity_tier: int = 1
    duration_estimate_min: float = 0.0
    lat: float = 0.0
    lon: float = 0.0
    timestamp: str = ""
    description: str = ""


class SignalRecommendation(BaseModel):
    intersection_name: str
    current_phase: str = ""
    recommended_phase: str
    phase_duration_s: int
    reason: str
    confidence: float
    sensor_citation: str = ""
    upstream_distance_m: float = 0.0
    source: str = "llm"  # "llm" or "fallback" (rule-based, LLM unavailable)


class DiversionRoute(BaseModel):
    route_street_names: list[str]
    route_coords: list[list[float]]
    diversion_text: str
    risk_delta_pct: float
    diversion_volume_pct: float
    time_delta_min: float = 0.0
    confidence: float = 0.5
    why_safer: str = ""
    source: str = "llm"


class AlertDrafts(BaseModel):
    vms: list[str] = Field(default_factory=list, description="3 lines, each ≤20 chars")
    radio_script: str = ""
    tweet: str = Field(default="", max_length=280)
    source: str = "llm"


class DensityData(BaseModel):
    segment_densities: dict[str, float] = Field(default_factory=dict)
    congestion_level: str = "NORMAL"
    estimated_vehicles: int = 0
    vision_analysis: str = ""


class TimelineEntry(BaseModel):
    timestamp: str
    event: str
    category: str = "system"


class AgentOutput(BaseModel):
    signal_recommendations: list[SignalRecommendation] = Field(default_factory=list)
    diversion: Optional[DiversionRoute] = None
    alerts: Optional[AlertDrafts] = None
    density: Optional[DensityData] = None
    final_summary: str = ""
    confidence_scores: dict[str, float] = Field(default_factory=dict)
    cascade_risk: float = 0.0
    rag_context: list[str] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    evaluation_metrics: dict[str, float] = Field(default_factory=dict)
    coherence_issues: list[str] = Field(default_factory=list)
    sop_compliance: str = ""
    # Per agent: {"source": "llm" | "fallback", "error": "..."}
    agent_status: dict[str, dict[str, str]] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: str
    content: str
    timestamp: str = ""
    tool_calls: list[dict] = Field(default_factory=list)
    thinking: str = ""


class ChatRequest(BaseModel):
    message: str
    incident_id: str = ""


class ChatResponse(BaseModel):
    response: str
    thinking: str = ""
    tool_calls: list[dict] = Field(default_factory=list)
    confidence: float = 0.0
    rag_sources: list[str] = Field(default_factory=list)
    source: str = "llm"
    error: str = ""


class WeatherConditionSchema(BaseModel):
    condition: str = "clear"
    temp_f: float = 55.0
    precip_pct: int = 0
    wind_mph: float = 5.0
    is_severe: bool = False
    description: str = ""
    timestamp: str = ""


class HotspotCluster(BaseModel):
    cluster_id: int
    center_lat: float
    center_lon: float
    accident_count: int
    severity_score: float
    risk_score: float
    radius_m: float


class RouteRequest(BaseModel):
    origin_lat: float
    origin_lon: float
    dest_lat: float
    dest_lon: float
    k: int = 3
    vehicle_type: str = "normal"


class CandidateRoute(BaseModel):
    route_index: int
    rank: str = "optimal"
    color: str = "#10B981"
    street_names: list[str] = Field(default_factory=list)
    coords: list[list[float]] = Field(default_factory=list)
    total_length_km: float = 0.0
    total_travel_time_min: float = 0.0
    avg_density: float = 0.0
    avg_accident_score: float = 0.0
    avg_weather_penalty: float = 1.0
    composite_score: float = 0.0
    is_optimal: bool = False
    signal_preemptions: list[dict] = Field(default_factory=list)


class RouteResponse(BaseModel):
    routes: list[CandidateRoute] = Field(default_factory=list)
    origin: dict = Field(default_factory=dict)
    destination: dict = Field(default_factory=dict)
    vehicle_type: str = "normal"
    weather_condition: str = "clear"


class GeocodeSuggestion(BaseModel):
    place_name: str
    lat: float
    lon: float


class TwinPrediction(BaseModel):
    no_action_segments: list[dict] = Field(default_factory=list)
    with_action_segments: list[dict] = Field(default_factory=list)
    time_saved_min: float = 0.0
    secondary_incidents_prevented: int = 0
