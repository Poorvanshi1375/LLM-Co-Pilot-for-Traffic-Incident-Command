# TrafficMind Updates Log

## v3.0.0 — Demo Recovery: working agents, real routes, security (Current)

Released: October 3, 2026

- **Agents work again**: `llama-3.3-70b-versatile` was removed from Groq, so every Groq agent had been silently falling back. Default is now `openai/gpt-oss-120b` (`GROQ_MODEL` to override). Gemini moved from the deprecated `google-generativeai` SDK to `google-genai`, with thinking off so short token limits no longer return empty answers.
- **Shared LLM layer** (`core/llm.py`): timeouts, key failover (401/403 benches a key for 10 min, 429 for 1 min), JSON parsing. `/health` reports per-provider key checks.
- **Honest output**: every agent result carries `source: llm | fallback`; the UI shows a "Rule-based fallback" badge. Illustrative metrics are labelled.
- **Real diversion routes**: the diversion is now a weighted shortest path on the road graph around a blocked 200 m zone, following road curves, with extra minutes against the normal direct trip.
- **Fits the free tier**: the road graph is prebuilt to a 1.3 MB file and loaded once; hotspots are precomputed; osmnx, scikit-learn and pandas left the runtime. Local server memory dropped to about 175 MB.
- **Route planning**: per-request weight function (no shared-graph mutation), real minutes, routes coloured by average risk relative to the live network.
- **Borough-wide coverage**: the 250 monitored segments were clustered in east/south Brooklyn; they are now one major-road segment per grid cell across the borough (`scripts/build_segments.py`), so 79% of road edges get live speed and risk (was 29%).
- **Diversion clearance**: edges whose geometry passes within 200 m of the incident are blocked, not just nearby nodes.
- **Dashboard**: map flies to a new incident and fits its diversion; chat answers are plain text.
- **Traffic map redesign**: clean base map with only live traffic lines on top (green/orange/red with a soft white edge, continuous along each monitored street), hover card with street and speed, compact legend; hotspots and risk heatmap off by default behind toggles; dots and glow removed.
- **Map search** (overview mode): monitored streets match instantly and get spotlighted with their average live speed; places (Mapbox Search Box) get a pin and the nearest live reading.
- **LLM resilience**: Gemini <-> Groq cross-provider fallback (Gemini's free tier allows only 20 requests/day), second Groq model on per-minute limits, daily-quota keys benched for an hour, `/health` shows runtime `last_errors`. Chat runs on Groq first with a compact prompt.
- **Chat grounding**: explicit "no incident" context and a rule against inventing figures; diversion facts passed verbatim; compliance stated as not measured.
- **Operator toggles** stay locked with a hint until the server has an `ADMIN_TOKEN` and the token is saved in the browser.
- **Pipeline**: runs as a background task under a lock, so the feed keeps ticking and overlapping triggers get 409; alerts run once, after routing; resolve clears all derived state; timeline capped at 200; UTC timestamps.
- **Phantom incidents**: detector warm-up (1 min) and 3-tick persistence; auto-detect off by default and switchable by the operator.
- **Security**: tweeting off unless `TWITTER_ENABLED=true`; admin token for settings; one trigger per IP per 30 s; CORS limited to known origins; WebSocket is server-to-client only with an Origin check.
- **Frontend**: full state on connect, wake-up banner for the sleeping backend, error toasts, responsive layout, Brooklyn landmark search (Mapbox Search Box).
- **Tests**: `backend/tests/test_e2e.py` (pytest) against any backend URL; CI workflow; optional keep-alive workflow.

---

## v2.9.0 — Final Polish + E2E Verification

Released: March 22, 2026

- Full backend import checks passing: `route_finder`, `hotspot_predictor`, `weather_service`, `key_manager`.
- Frontend TypeScript type check (`npx tsc --noEmit`) clean — no type errors.
- End-to-end flow verified: Overview mode → hotspots + weather → Route Planning mode → geocoding → 3 color-coded routes → incident simulation → dynamic confidence → RAG chat with sources → voice chat → auto-tweet → Digital Twin.

---

## v2.8.0 — Branding: Logo + Favicon

Released: March 22, 2026

- **`frontend/public/logo.svg`**: Traffic signal + neural network fusion SVG in emerald/blue tones.
- **`frontend/src/app/icon.svg`**: Simplified 32×32 favicon for Next.js App Router auto-favicon.
- **Sidebar Logo**: Replaced `<Zap>` icon with branded SVG logo.
- **Layout Metadata**: `icons: { icon: "/icon.svg" }` added to `frontend/src/app/layout.tsx`.

---

## v2.7.0 — Voice Chat (Whisper STT + Browser TTS)

Released: March 22, 2026

- **Voice Endpoint** (`POST /api/chat/voice`): Accepts audio `UploadFile`, transcribes via Groq Whisper (`whisper-large-v3-turbo`) using key rotation, passes transcript to `narrative_agent.chat()`, returns `{transcript, response, rag_sources}`.
- **Mic Button in ChatInterface**: `MediaRecorder` → webm → sent to `/api/chat/voice`. Red pulsing indicator while recording.
- **TTS Toggle**: `window.speechSynthesis.speak()` for all assistant responses. Toggle button in chat header.
- **`python-multipart>=0.0.18`** added to `backend/requirements.txt`.

---

## v2.6.0 — Social Media Auto-Posting

Released: March 22, 2026

- **Twitter Poster** (`backend/integrations/twitter_poster.py`): `post_tweet(text)` via tweepy OAuth 1.0a. Returns `{tweet_id, url, status}`. Gracefully skips with `{status: "skipped", reason: "Twitter credentials not configured"}` when env vars absent.
- **LangGraph Pipeline Integration**: Post-alerts step in `graph.py` auto-posts tweet if enabled. Timeline entry added: "📱 Tweet posted: {url}" or "Tweet skipped: no credentials".
- **Auto-Post Toggle**: `POST /api/settings/auto-post` + `GET /api/settings` endpoints. Toggle switch added to Sidebar.
- **`tweepy>=4.14.0`** added to `backend/requirements.txt`.

---

## v2.5.0 — RAG-Powered Chat

Released: March 22, 2026

- **RAG Injection into Narrative Agent**: `narrative_agent.py` now calls `retrieve_sops(user_message, top_k=2)` before every chat response. SOP content injected into LLM context — questions like "What's the flooding protocol?" receive answers grounded in actual SOP documents.
- **RAG Sources in Response**: `ChatResponse` schema updated with `rag_sources: list[str]`. `/api/chat` returns document names used.
- **Source Badges in ChatInterface**: RAG-grounded assistant messages show collapsible "📄 Sources" badges. Click to see which SOP documents were referenced.

---

## v2.4.0 — Route Intelligence: Toggle Mode, Geocoding, Priority, Weather, Coloring

Released: March 22, 2026

- **Route Finder** (`backend/core/route_finder.py`): Loads Brooklyn OSMnx graph, converts `MultiDiGraph → DiGraph` (fixes `NetworkXNotImplemented` crash). Computes live edge weights from feed speed + risk + weather penalty + vehicle-type multiplier. Uses `nx.shortest_simple_paths` for top-K routes.
- **Vehicle Priority Routing**: `ambulance` (0.6×), `police` (0.65×), `fire_brigade` (0.7×) weight multipliers. Emergency vehicles also get reduced risk weighting and signal preemption intersection lists from SOP 04.
- **3-Route Color Ranking**: Lowest composite score → GREEN `#22c55e` (optimal); middle → YELLOW `#f59e0b` (moderate); highest → RED `#ef4444` (risky). Routes follow actual Brooklyn road geometry.
- **Composite Route Score**: `0.25×density + 0.30×travel_time + 0.25×accident + 0.20×weather`.
- **Mapbox Geocoding Proxy** (`GET /api/geocode?q=...`): Brooklyn-scoped (`-74.05,40.57,-73.83,40.74`) forward geocoding via Mapbox Search API.
- **`POST /api/routes`** and **`GET /api/routes/csv`** endpoints added.
- **Dashboard Mode Toggle**: Segmented control "Map Overview | Route Planning" in dashboard top bar.
- **Search Boxes in TrafficMap**: Debounced geocoding autocomplete (300ms), click-to-set origin/destination, green START / red END markers, crosshair cursor in route mode. Route lines rendered as colored LineString layers; click to select.
- **Vehicle Type Selector**: Dropdown (Normal / Ambulance / Police / Fire Brigade) visible in Route Planning mode.
- **RoutingPanel Route Cards**: Left color bar, rank badge, 4-metric grid (time/distance/density/risk), weather penalty indicator, street name sequence, signal preemption list for emergency vehicles, CSV Export button.
- **New Types/Store**: `CandidateRoute`, `RouteRequest`, `RouteResponse`, `GeocodeSuggestion`, `VehicleType`; `dashboardMode`, `candidateRoutes`, `vehicleType`, `routeOrigin`, `routeDestination` in Zustand store.

---

## v2.3.0 — Hotspot Prediction (DBSCAN)

Released: March 22, 2026

- **Hotspot Predictor** (`backend/core/hotspot_predictor.py`): Generates 500 synthetic accident records weighted by OSMnx road type, proximity to the 21 known Brooklyn hotspots, time-of-day, and severity. Runs DBSCAN (`eps=0.0008, min_samples=4, haversine metric`) to produce accident cluster zones.
- **`/api/hotspots/predicted` Endpoint**: Returns `HotspotCluster[]` with `center_lat`, `center_lon`, `accident_count`, `severity_score`, `risk_score`, `radius_m`, `peak_hours`. Distinct from existing `/api/hotspots` (static 21 known hotspots).
- **Map Visualization**: Semi-transparent graduated red circles on the Brooklyn map. Circle radius proportional to `risk_score`. Tooltip: "Predicted Hotspot — N incidents, risk score X".
- **Schema**: `HotspotCluster` added to `backend/models/schemas.py`.

---

## v2.2.0 — Weather Intelligence

Released: March 22, 2026

- **Weather Service** (`backend/core/weather_service.py`): Fetches real Brooklyn weather from Weather.gov API (free, no key). Caches for 15 minutes. Returns `WeatherCondition(condition, temp_f, precip_pct, wind_mph, is_severe)`.
- **Road Vulnerability Classification**: Brooklyn roads classified as flood-prone (Belt Pkwy, Gowanus area), ice/wind-prone (bridges, BQE), or snow-accumulation (Eastern Pkwy, Ocean Pkwy). `get_weather_penalty()` returns 1.0–3.0 multiplier per road + weather combination.
- **`/api/weather` Endpoint**: Returns current `WeatherCondition` for the Brooklyn area.
- **Weather Widget in Sidebar**: Icon (☀️/🌧️/❄️) + temperature + condition, color-coded green/yellow/orange/red based on severity.
- **Schema**: `WeatherCondition` added to `backend/models/schemas.py`.

---

## v2.1.0 — Core Infrastructure: Real Time, Key Rotation, Dynamic Stats

Released: March 22, 2026

- **API Key Rotation** (`backend/core/key_manager.py`): Thread-safe Groq + Gemini key pools parsed from comma-separated env vars (`GROQ_API_KEYS`, `GOOGLE_AI_API_KEYS`). Auto-rotates on 429 rate-limit errors, falls back to primary keys.
- **Real Wall-Clock Time**: Replaced `_simulated_hour` fixed value with `datetime.now()` in `feed_engine.py` — sidebar now shows actual current time.
- **Flow-Based Diversion Volume**: Replaced `random.uniform()` in `routing_agent.py` with a computation derived from blocked segment density vs. route segment density.
- **Dynamic Confidence Scores**: Supervisor (`supervisor.py`) now derives per-agent confidence from live data (`mean(s.confidence for s in signals)`, diversion confidence, weighted overall) instead of hardcoded defaults (0.7/0.8).
- **Cascade Risk Computation**: Cascade risk in Supervisor derived from diversion route average risk vs. incident risk ratio — no longer hardcoded `0.0`.
- **"Current Time" Label**: Sidebar label changed from "Simulated Time" to "Current Time".

---

## v2.0.0 — Upgrade Baseline

Released: March 22, 2026

TrafficMind v2.0 upgrade plan initiated. Starting point for the full platform upgrade across 9 incremental versions (v2.1.0–v2.9.0). Base system is v1.0.0 with the Brooklyn OSMnx road graph, 6-agent LangGraph pipeline, and Next.js dashboard.

---

## v1.0.0 — Initial Release

Released: March 21, 2026

### 🚀 Core Features

- **Real-Time Feed**: 250 Brooklyn road segments with simulated speed data sourced from OSMnx road graph, updated every 5 seconds via WebSocket.
- **Multi-Agent Pipeline**: 6 LLM agents running in a parallel fan-out → Supervisor fan-in pattern, orchestrated by LangGraph.
- **Signal Agent**: Upstream/downstream intersection phase adjustment recommendations with sensor citations (Groq Llama 3.3 70B).
- **Routing Agent**: Alternative diversion route computation with risk delta and volume redistribution (Groq Llama 3.3 70B).
- **Alert Agent**: Triple-format public alerts — VMS (≤20 chars/line), 15-second radio script, 280-character tweet (Groq Llama 3.3 70B).
- **Density Agent**: Vehicle density estimation using the fundamental flow equation with optional Gemini vision analysis.
- **Supervisor Agent**: Cross-agent coherence checking, cascade risk assessment, and SOP compliance validation (Gemini 2.0 Flash).
- **Narrative Agent**: Natural language chat interface with full incident context (Gemini 2.0 Flash).

### 🗺️ Data & Infrastructure

- **Brooklyn Road Network**: Actual OSMnx-sourced road graph — 250 real segments, not mock data.
- **Risk Scorer**: Rule-based risk computation across all segments on every feed tick.
- **Anomaly Detector**: Statistical deviation detection for automatic incident flagging.
- **RAG Retrieval**: TF-IDF vectorizer over 12 Standard Operating Procedure documents for recommendation grounding.

### 🏙️ Frontend

- **Dashboard** (`/dashboard`): Live Brooklyn map with 250 real-time speed-coloured segments, risk overlay, and incident controls.
- **Digital Twin** (`/twin`): Side-by-side before/after map comparison with quantified travel time savings.
- **Tabs**: Signals, Routing, Alerts, Chat, Timeline, and Supervisor Summary.
- **WebSocket**: 5-second live tick feed with instant incident event propagation.
- **State**: Zustand client-side store synced to server via REST + WebSocket.

### ⚡ Performance

- Sub-2s end-to-end pipeline response; measured 0.34s with Groq Llama 3.3 70B.
- Parallel fan-out across all four specialist agents to minimise total latency.

Built with ❤️ by **Team 2AM Coders**.
