"""
TrafficMind Backend — FastAPI application.
REST + WebSocket server for real-time traffic incident management.
"""
from __future__ import annotations

import os
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from core.feed_engine import FeedEngine
from core.risk_scorer import compute_risk_map, get_hotspots
from core.graph import TrafficGraph, AlreadyProcessingError
from core import road_graph
from core.llm_health import check_llms, get_status as get_llm_status
from integrations.twitter_poster import twitter_enabled
from pydantic import BaseModel
from models.schemas import (
    ChatRequest, ChatResponse, Severity, IncidentDetection,
    FeedTick, TimelineEntry,
)
from rag.retriever import get_all_documents
from core.weather_service import get_weather as fetch_weather
from core.hotspot_predictor import predict_hotspots as predict_hotspot_clusters
from core.route_finder import find_routes as compute_routes
from models.schemas import RouteRequest
from fastapi.responses import StreamingResponse
from typing import Optional
import httpx
import io
import csv


APP_VERSION = "3.0.0"

# Browser origins allowed to call the API (comma-separated), plus an optional
# regex for Vercel preview URLs, e.g. https://llm-co-pilot-.*\.vercel\.app
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()
]
ALLOWED_ORIGIN_REGEX = os.getenv(
    "ALLOWED_ORIGIN_REGEX", r"https://llm-co-pilot-for-traffic-incident-command[a-z0-9-]*\.vercel\.app"
) or None

# Operator token for settings that affect everyone (auto-post, auto-detect)
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

TRIGGER_COOLDOWN_S = 30
MAX_AUDIO_BYTES = 5 * 1024 * 1024
_last_trigger_by_ip: dict[str, float] = {}


class IncidentTriggerRequest(BaseModel):
    severity: str = "HIGH"
    segment_id: Optional[str] = None


def _client_ip(request: Request) -> str:
    """Client IP, honouring the proxy header Render sets."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _require_admin(token: Optional[str]):
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="ADMIN_TOKEN is not configured on the server")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token")


def _origin_allowed(origin: str) -> bool:
    import re
    if origin in ALLOWED_ORIGINS:
        return True
    return bool(ALLOWED_ORIGIN_REGEX and re.fullmatch(ALLOWED_ORIGIN_REGEX, origin))


# Global instances
feed_engine = FeedEngine()
traffic_graph: Optional[TrafficGraph] = None
connected_clients: list[WebSocket] = []


async def broadcast_ws(data: dict):
    """Send a JSON message to all connected WebSocket clients."""
    msg = json.dumps(data)
    disconnected = []
    for ws in connected_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connected_clients.remove(ws)


async def broadcast_tick(tick: FeedTick):
    """Broadcast feed tick to all connected WebSocket clients."""
    state = traffic_graph.get_state() if traffic_graph else {}
    await broadcast_ws({
        "type": "tick",
        "tick": tick.tick,
        "timestamp": tick.timestamp,
        "hour": feed_engine.get_simulated_hour(),
        "segments": [s.model_dump() for s in tick.segments],
        "risk_map": [r.model_dump() for r in (state.get("risk_map") or [])],
        "incident": state.get("incident").model_dump() if state.get("incident") else None,
        "processing": state.get("processing", False),
    })


@asynccontextmanager
async def lifespan(app: FastAPI):
    global traffic_graph
    
    # Initialize
    feed_engine.initialize()
    traffic_graph = TrafficGraph(feed_engine, on_event=broadcast_ws)
    feed_engine.add_listener(broadcast_tick)

    async def on_tick(tick: FeedTick):
        await traffic_graph.process_tick(tick.segments, feed_engine.get_simulated_hour())

    feed_engine.add_listener(on_tick)

    # Start feed in background
    feed_task = asyncio.create_task(feed_engine.run(interval=5.0))

    # Warm the road graph and test LLM keys without blocking startup
    def _load_road_graph():
        road_graph.get_graph()
        road_graph.attach_segments(feed_engine.get_segments())

    async def _warm_up():
        try:
            await asyncio.to_thread(_load_road_graph)
        except Exception as e:
            print(f"Road graph load failed: {e}")

    warm_tasks = [asyncio.create_task(_warm_up()), asyncio.create_task(check_llms())]

    yield

    # Cleanup
    feed_engine.stop()
    feed_task.cancel()
    for t in warm_tasks:
        t.cancel()


app = FastAPI(
    title="TrafficMind API",
    description="LLM Co-Pilot for Traffic Incident Command",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=False,  # the app sends no cookies
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Admin-Token"],
)


# ─── REST Endpoints ────────────────────────────────────────


@app.get("/health")
async def health():
    """Liveness plus readiness details. Always 200 so Render keeps the service up."""
    llm = get_llm_status()
    return {
        "status": "ok",
        "version": APP_VERSION,
        "segments": len(feed_engine.get_segments()),
        "road_graph_loaded": road_graph.is_loaded(),
        "llm": {
            "checked_at": llm["checked_at"],
            "groq": llm["groq"],
            "gemini": llm["gemini"],
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/llm/check")
async def recheck_llms(x_admin_token: Optional[str] = Header(default=None)):
    """Re-test every LLM key now (operator only)."""
    _require_admin(x_admin_token)
    return await check_llms()


@app.get("/api/state")
async def get_state():
    """Get current system state."""
    state = traffic_graph.get_state()
    return {
        "snapshot": [s.model_dump() for s in state.get("snapshot", [])],
        "risk_map": [r.model_dump() for r in state.get("risk_map", [])],
        "incident": state["incident"].model_dump() if state.get("incident") else None,
        "hour": state.get("hour", 0),
        "processing": state.get("processing", False),
        "last_update": state.get("last_update", ""),
    }


@app.get("/api/agents")
async def get_agent_output():
    """Get latest agent outputs."""
    state = traffic_graph.get_state()
    output = state.get("agent_output")
    if not output:
        return {"status": "no_incident", "agent_output": None}

    return {
        "status": "active",
        "agent_output": output.model_dump(),
        "incident": state["incident"].model_dump() if state.get("incident") else None,
    }


@app.get("/api/signals")
async def get_signals():
    """Get signal recommendations."""
    state = traffic_graph.get_state()
    return {
        "recommendations": [s.model_dump() for s in state.get("signal_recommendations", [])],
        "incident": state["incident"].model_dump() if state.get("incident") else None,
    }


@app.get("/api/diversion")
async def get_diversion():
    """Get diversion route."""
    state = traffic_graph.get_state()
    diversion = state.get("diversion")
    return {
        "diversion": diversion.model_dump() if diversion else None,
        "incident": state["incident"].model_dump() if state.get("incident") else None,
    }


@app.get("/api/alerts")
async def get_alerts():
    """Get alert drafts."""
    state = traffic_graph.get_state()
    alerts = state.get("alerts")
    return {
        "alerts": alerts.model_dump() if alerts else None,
        "incident": state["incident"].model_dump() if state.get("incident") else None,
    }


@app.get("/api/density")
async def get_density():
    """Get vehicle density data."""
    state = traffic_graph.get_state()
    density = state.get("density")
    return {
        "density": density.model_dump() if density else None,
    }


@app.get("/api/timeline")
async def get_timeline():
    """Get incident timeline."""
    state = traffic_graph.get_state()
    return {
        "timeline": [t.model_dump() for t in state.get("timeline", [])],
    }


@app.get("/api/hotspots")
async def get_hotspots_endpoint():
    """Get Brooklyn black-spot hotspot data."""
    return {"hotspots": get_hotspots()}


@app.get("/api/hotspots/predicted")
async def get_predicted_hotspots():
    """Get DBSCAN-predicted accident hotspot clusters."""
    clusters = await asyncio.to_thread(predict_hotspot_clusters)
    return {"clusters": clusters}


@app.get("/api/weather")
async def get_weather_endpoint():
    """Get current Brooklyn weather conditions."""
    weather = await fetch_weather()
    return {
        "condition": weather.condition,
        "temp_f": weather.temp_f,
        "precip_pct": weather.precip_pct,
        "wind_mph": weather.wind_mph,
        "is_severe": weather.is_severe,
        "description": weather.description,
        "timestamp": weather.timestamp,
    }


@app.get("/api/documents")
async def get_documents():
    """Get RAG document index."""
    return {"documents": get_all_documents()}


@app.get("/api/metrics")
async def get_metrics():
    """Get evaluation metrics."""
    state = traffic_graph.get_state()
    output = state.get("agent_output")
    incident = state.get("incident")

    base_metrics = {
        "active_segments": len(state.get("snapshot", [])),
        "risk_map_size": len(state.get("risk_map", [])),
        "incident_active": incident is not None,
        "simulated_hour": state.get("hour", 0),
    }

    if output:
        base_metrics.update(output.evaluation_metrics)
        base_metrics["cascade_risk"] = output.cascade_risk
        base_metrics["confidence_scores"] = output.confidence_scores

    if incident:
        # Response time estimate
        base_metrics["incident_severity"] = incident.severity.value
        base_metrics["duration_estimate_min"] = incident.duration_estimate_min
        # Illustrative only: 11 min is an assumed manual baseline, not a measurement
        base_metrics["manual_avg_min"] = 11.0
        base_metrics["time_saved_min"] = round(11.0 - (output.evaluation_metrics.get("response_latency_s", 5) / 60), 1) if output else 0
        base_metrics["illustrative_fields"] = ["manual_avg_min", "time_saved_min"]

    return base_metrics


@app.get("/api/twin")
async def get_twin_data():
    """Get digital twin comparison data."""
    state = traffic_graph.get_state()
    snapshot = state.get("snapshot", [])
    incident = state.get("incident")
    diversion = state.get("diversion")

    if not incident or not snapshot:
        return {"no_action": [], "with_action": [], "time_saved_min": 0}

    no_action = []
    with_action = []

    diversion_streets = set(diversion.route_street_names) if diversion else set()

    for seg in snapshot:
        base = {
            "street_name": seg.street_name,
            "lat": seg.lat,
            "lon": seg.lon,
            "segment_id": seg.segment_id,
        }

        # No-action: congestion spreads (distance-decay worsening)
        if seg.segment_id == incident.segment_id:
            no_action_speed = 2.0
        else:
            from core.feed_engine import _haversine
            dist = _haversine(seg.lat, seg.lon, incident.lat, incident.lon)
            if dist < 1.0:
                decay = max(0.2, dist / 1.0)
                no_action_speed = seg.speed * decay
            else:
                no_action_speed = seg.speed

        no_action.append({**base, "speed": round(no_action_speed, 1), "free_flow_speed": seg.free_flow_speed})

        # With-action: diversion working
        if seg.street_name in diversion_streets:
            # Slightly more traffic on diversion route
            with_speed = seg.speed * 0.85
        elif seg.segment_id == incident.segment_id:
            with_speed = seg.speed  # Still blocked but being managed
        else:
            with_speed = min(seg.free_flow_speed, seg.speed * 1.15)  # Recovery

        with_action.append({**base, "speed": round(with_speed, 1), "free_flow_speed": seg.free_flow_speed})

    # Illustrative: assumes intervention shortens the incident's impact by 30%
    time_saved = round(incident.duration_estimate_min * 0.3, 1) if incident else 0

    return {
        "no_action": no_action,
        "with_action": with_action,
        "time_saved_min": time_saved,
        "time_saved_is_illustrative": True,
        "incident": incident.model_dump() if incident else None,
    }


# ─── Route Intelligence ────────────────────────────────────

_last_route_response = None


@app.get("/api/geocode")
async def geocode_search(q: str):
    """Place search via Mapbox Search Box (landmarks + addresses), Brooklyn results only.

    Geocoding v6 no longer returns POIs, so "Barclays Center" found nothing useful;
    the Search Box API does, and tags each result's borough in context.locality.
    """
    token = os.getenv("MAPBOX_TOKEN", "")
    if not token:
        raise HTTPException(status_code=500, detail="MAPBOX_TOKEN not configured")
    q = q.strip()[:200]
    if len(q) < 2:
        return {"suggestions": []}

    params = {
        "q": q,
        "access_token": token,
        "bbox": "-74.05,40.57,-73.83,40.74",  # box around Brooklyn (also covers lower Manhattan)
        "proximity": "-73.9442,40.6782",       # bias toward central Brooklyn
        "country": "us",
        "language": "en",
        "limit": 10,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://api.mapbox.com/search/searchbox/v1/forward", params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Place search failed: {type(e).__name__}")

    suggestions = []
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        locality = (props.get("context", {}).get("locality") or {}).get("name", "")
        full = props.get("full_address") or props.get("place_formatted") or ""
        if locality != "Brooklyn" and "Brooklyn" not in full:
            continue  # drop Manhattan/Queens hits inside the bounding box
        name = props.get("name", "")
        label = f"{name}, {full}" if full and not full.startswith(name) else (full or name)
        coords = feat.get("geometry", {}).get("coordinates", [0, 0])
        suggestions.append({
            "place_name": label.replace(", United States", ""),
            "lat": coords[1],
            "lon": coords[0],
        })
        if len(suggestions) == 5:
            break
    return {"suggestions": suggestions}


@app.post("/api/routes")
async def compute_routes_endpoint(body: RouteRequest):
    """Compute k-shortest routes between origin and destination."""
    global _last_route_response
    state = traffic_graph.get_state() if traffic_graph else {}
    snapshot = state.get("snapshot", [])
    risk = state.get("risk_map", [])
    hour = state.get("hour", 12.0)

    # Get current weather condition
    weather_cond = "clear"
    try:
        w = await fetch_weather()
        weather_cond = w.condition
    except Exception:
        pass

    try:
        routes = await asyncio.wait_for(asyncio.to_thread(
            compute_routes,
            origin_lat=body.origin_lat,
            origin_lon=body.origin_lon,
            dest_lat=body.dest_lat,
            dest_lon=body.dest_lon,
            k=max(1, min(body.k, 3)),
            feed_snapshot=snapshot,
            risk_map=risk,
            vehicle_type=body.vehicle_type,
            weather_condition=weather_cond,
        ), timeout=60)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Route computation timed out")

    response = {
        "routes": routes,
        "origin": {"lat": body.origin_lat, "lon": body.origin_lon},
        "destination": {"lat": body.dest_lat, "lon": body.dest_lon},
        "vehicle_type": body.vehicle_type,
        "weather_condition": weather_cond,
    }
    _last_route_response = response
    return response


@app.get("/api/routes/csv")
async def export_routes_csv():
    """Export last computed routes as CSV."""
    if not _last_route_response or not _last_route_response.get("routes"):
        raise HTTPException(status_code=404, detail="No routes computed yet")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "route_index", "rank", "street_names", "total_length_km",
        "total_travel_time_min", "avg_density", "avg_accident_score",
        "avg_weather_penalty", "composite_score", "is_optimal",
        "vehicle_type", "weather_condition",
    ])
    for r in _last_route_response["routes"]:
        writer.writerow([
            r["route_index"],
            r["rank"],
            " → ".join(r["street_names"]),
            r["total_length_km"],
            r["total_travel_time_min"],
            r["avg_density"],
            r["avg_accident_score"],
            r["avg_weather_penalty"],
            r["composite_score"],
            r["is_optimal"],
            _last_route_response.get("vehicle_type", "normal"),
            _last_route_response.get("weather_condition", "clear"),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=routes.csv"},
    )


# ─── Actions ───────────────────────────────────────────────


@app.post("/api/trigger-incident")
async def trigger_incident(body: IncidentTriggerRequest, request: Request):
    """Trigger a demo incident (one per IP every 30 s), then wait up to 45 s for agents."""
    try:
        sev = Severity(body.severity)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown severity '{body.severity}'")

    ip = _client_ip(request)
    now = time.time()
    wait = TRIGGER_COOLDOWN_S - (now - _last_trigger_by_ip.get(ip, 0))
    if wait > 0:
        raise HTTPException(status_code=429, detail=f"Please wait {int(wait) + 1}s before triggering again")

    try:
        incident = await traffic_graph.trigger_incident(segment_id=body.segment_id, severity=sev)
    except AlreadyProcessingError:
        raise HTTPException(status_code=409, detail="Agents are already processing an incident")
    if not incident:
        raise HTTPException(status_code=400, detail="No segments available")
    _last_trigger_by_ip[ip] = now

    finished = await traffic_graph.wait_for_pipeline(timeout=45)
    state = traffic_graph.get_state()
    return {
        "incident": incident.model_dump(),
        "agent_output": state["agent_output"].model_dump() if state.get("agent_output") else None,
        "processing": not finished,
    }


@app.post("/api/resolve-incident")
async def resolve_incident():
    """Resolve the active incident."""
    await traffic_graph.resolve_incident()
    return {"status": "resolved"}


@app.get("/api/settings")
async def get_settings():
    """Get current settings."""
    return {
        "auto_post": traffic_graph.get_auto_post() if traffic_graph else False,
        "twitter_enabled": twitter_enabled(),
        "auto_detect": traffic_graph.get_auto_detect() if traffic_graph else False,
        "admin_configured": bool(ADMIN_TOKEN),
    }


@app.post("/api/settings/auto-post")
async def set_auto_post(body: dict, x_admin_token: Optional[str] = Header(default=None)):
    """Toggle auto-post to Twitter/X (operator only, and only if the server allows posting)."""
    enabled = bool(body.get("enabled", False))
    if enabled:
        if not twitter_enabled():
            raise HTTPException(status_code=403, detail="Posting is disabled on this server (TWITTER_ENABLED is not true)")
        _require_admin(x_admin_token)
    if traffic_graph:
        traffic_graph.set_auto_post(enabled)
    return {"auto_post": enabled}


@app.post("/api/settings/auto-detect")
async def set_auto_detect(body: dict, x_admin_token: Optional[str] = Header(default=None)):
    """Toggle automatic incident detection (operator only)."""
    _require_admin(x_admin_token)
    enabled = bool(body.get("enabled", False))
    if traffic_graph:
        traffic_graph.set_auto_detect(enabled)
    return {"auto_detect": enabled}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Send a message to the narrative agent."""
    if not request.message.strip():
        raise HTTPException(status_code=422, detail="Message is empty")
    if len(request.message) > 2000:
        raise HTTPException(status_code=413, detail="Message is longer than 2000 characters")
    narrative = traffic_graph.get_narrative_agent()
    response = await narrative.chat(request.message)
    return response.model_dump()


@app.get("/api/chat/history")
async def chat_history():
    """Get chat conversation history."""
    narrative = traffic_graph.get_narrative_agent()
    return {"messages": [m.model_dump() for m in narrative.get_messages()]}


@app.post("/api/chat/voice")
async def chat_voice(audio: UploadFile = File(...)):
    """Voice chat: transcribe audio → narrative agent (concise) → gTTS audio."""
    import base64
    from io import BytesIO
    from integrations.speech import transcribe_audio

    audio_bytes = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(audio_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty audio file")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio is larger than 5 MB")

    stt = await transcribe_audio(audio_bytes, audio.filename or "audio.webm")
    if stt["status"] != "ok" or not stt["text"]:
        return {
            "transcript": "",
            "response": "Sorry, I couldn't understand the audio. Please try again.",
            "thinking": "",
            "tool_calls": [],
            "confidence": 0.0,
            "rag_sources": [],
            "audio_base64": "",
            "source": "fallback",
            "error": stt.get("reason", "")[:200],
        }

    transcript = stt["text"]
    narrative = traffic_graph.get_narrative_agent()
    response = await narrative.chat(transcript, voice=True)
    result = response.model_dump()
    result["transcript"] = transcript

    # Generate gTTS audio from response text
    try:
        from gtts import gTTS

        def _synthesize_speech(text: str) -> bytes:
            tts = gTTS(text=text, lang="en")
            buf = BytesIO()
            tts.write_to_fp(buf)
            buf.seek(0)
            return buf.read()

        audio_bytes_out = await asyncio.to_thread(_synthesize_speech, result["response"])
        result["audio_base64"] = base64.b64encode(audio_bytes_out).decode("ascii")
    except Exception as e:
        print(f"gTTS error: {e}")
        result["audio_base64"] = ""

    return result


# ─── WebSocket ─────────────────────────────────────────────


def _state_message() -> dict:
    """Full current state, sent to each client when it connects."""
    state = traffic_graph.get_state()
    return {
        "type": "state",
        "incident": state["incident"].model_dump() if state.get("incident") else None,
        "agent_output": state["agent_output"].model_dump() if state.get("agent_output") else None,
        "processing": state.get("processing", False),
        "timeline": [t.model_dump() for t in state.get("timeline", [])],
    }


@app.websocket("/ws/feed")
async def websocket_feed(websocket: WebSocket):
    """Real-time feed WebSocket (server → client only; actions go through REST)."""
    origin = websocket.headers.get("origin")
    if origin and not _origin_allowed(origin):
        await websocket.close(code=1008)  # policy violation
        return

    await websocket.accept()
    connected_clients.append(websocket)

    try:
        await websocket.send_text(json.dumps(_state_message()))
        while True:
            # Keep the connection open; client messages are ignored
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
