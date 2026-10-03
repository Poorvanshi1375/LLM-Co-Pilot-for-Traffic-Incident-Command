# TrafficMind — AI Co-Pilot for Traffic Incident Command (v3.0.0)

A real-time, LLM-powered multi-agent system for traffic incident detection, response coordination, and public alert management — built for Brooklyn, NYC.

![TrafficMind](https://img.shields.io/badge/TrafficMind-v3.0.0-2563eb?style=for-the-badge)
![Next.js](https://img.shields.io/badge/Next.js-16-000?style=flat-square&logo=next.js)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi)
![Multi-Agent](https://img.shields.io/badge/Multi--Agent-Pipeline-7C3AED?style=flat-square)

## 🔄 Updates

All updates from v1.0.0 onwards are documented in [UPDATES.md](UPDATES.md). 📝

Refer to it for the latest changes! 😉

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   PRESENTATION LAYER                     │
│  Next.js 16 + React 19 + TypeScript + Tailwind + Mapbox │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐                │
│  │ Dashboard │ │Digital Twin│ │ Landing  │                │
│  └──────────┘ └───────────┘ └──────────┘                │
│              ▲ WebSocket (real-time) ▲                    │
├──────────────┼───────────────────────┼───────────────────┤
│              │    AGENT LAYER        │                    │
│  ┌───────────▼───────────────────────▼────────────┐      │
│  │         Agent Orchestrator (asyncio)           │      │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐       │      │
│  │  │  Signal   │ │ Routing  │ │  Alert   │       │      │
│  │  │  Agent    │ │  Agent   │ │  Agent   │       │      │
│  │  │ (Groq)   │ │(graph+Groq)│ (Groq)   │       │      │
│  │  └──────────┘ └──────────┘ └──────────┘       │      │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐       │      │
│  │  │ Density  │ │Supervisor│ │Narrative │       │      │
│  │  │ Agent    │ │ (Gemini) │ │  Agent   │       │      │
│  │  └──────────┘ └──────────┘ └──────────┘       │      │
│  └────────────────────────────────────────────────┘      │
├──────────────────────────────────────────────────────────┤
│                     DATA LAYER                           │
│  ┌────────────┐ ┌────────────┐ ┌──────────────────┐     │
│  │ Feed Engine │ │Risk Scorer │ │ RAG (12 SOPs)    │     │
│  │ 250 segs   │ │  Anomaly   │ │ TF-IDF retrieval │     │
│  │ Brooklyn   │ │  Detector  │ │                  │     │
│  └────────────┘ └────────────┘ └──────────────────┘     │
└──────────────────────────────────────────────────────────┘
```

## Key Features

| Feature | Description |
|---------|-------------|
| **Real-Time Feed** | 250 Brooklyn road segments with simulated wall-clock speed data on the OSM road graph |
| **Multi-Agent Pipeline** | 6 LLM agents run in parallel fan-out → supervisor fan-in pattern |
| **API Key Failover** | Comma-separated key pools for Groq + Gemini; a key failing with 401/403 is benched 10 min, a 429 for 1 min |
| **Signal Re-Timing** | Upstream/downstream intersection phase adjustments with sensor citations |
| **Smart Diversion** | Alternative route computation with flow-based volume redistribution |
| **Triple-Format Alerts** | VMS (≤20 chars/line), 15s radio script, 280-char tweet — format-constrained |
| **Social Media Auto-Post** | Tweet auto-posts to Twitter/X via tweepy; toggle via sidebar |
| **Vehicle Density** | Fundamental flow equation + optional Gemini vision analysis |
| **RAG-Grounded SOPs** | 12 Standard Operating Procedures retrieved via TF-IDF for recommendation validation |
| **RAG-Powered Chat** | Chat agent cites SOP sources; RAG source badges shown in UI |
| **Voice Chat** | Groq Whisper STT + browser TTS — speak questions, hear answers |
| **Weather-Aware Routing** | Weather.gov real conditions; flood/ice/snow road penalties applied to route scoring |
| **Priority Routing** | Emergency vehicle mode (ambulance/police/fire) with edge-weight multipliers + signal preemptions |
| **Route Intelligence** | 3 candidate routes — green (optimal), yellow (moderate), red (risky) — following actual roads |
| **Geocoding Search** | Google Maps-style searchbox with Mapbox autocomplete, Brooklyn-scoped |
| **DBSCAN Hotspot Prediction** | Accident clusters from DBSCAN over synthetic, road-weighted accidents (precomputed) |
| **Digital Twin** | Side-by-side before/after comparison map showing intervention impact |
| **Dynamic Confidence** | Supervisor confidence scores derived from live agent data, not hardcoded defaults |
| **Fast Response** | Whole agent pipeline measured at about 2.6 s end to end (local run, 2026-10-03) |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 16, React 19, TypeScript 5, Tailwind v4, Mapbox GL |
| Backend | FastAPI, Python 3.11, Pydantic v2 |
| LLM (Fast) | Groq — openai/gpt-oss-120b (override with `GROQ_MODEL`) |
| LLM (Deep) | Google Gemini 2.5 Flash via `google-genai` (override with `GEMINI_MODEL`) |
| STT | Groq Whisper (whisper-large-v3-turbo) |
| TTS | Browser Web Speech API |
| Maps | Mapbox GL JS via react-map-gl v8 |
| Geocoding | Mapbox Search API (backend-proxied) |
| Road Data | Brooklyn OSM drive network (12,223 nodes), prebuilt to a 1.3 MB file; osmnx only at build time |
| Routing | NetworkX weighted shortest paths with a per-request weight function (time × risk × weather) |
| Weather | Weather.gov API (free, no key required) |
| Hotspots | scikit-learn DBSCAN, precomputed to `data/hotspots.json` |
| Social | tweepy (Twitter/X OAuth 1.0a) |
| RAG | Built-in TF-IDF retriever on 12 SOP documents |
| Real-Time | WebSocket (5s tick interval) |
| State | Zustand (client), in-memory (server) |
| Key Failover | Thread-safe key pool with benching of failed keys (Groq + Gemini) |

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- API keys: Groq, Google AI Studio, Mapbox

### 1. Clone & Configure

```bash
git clone https://github.com/YOUR_TEAM/trafficmind.git
cd trafficmind

# Create .env in project root
cat > .env << 'EOF'
# Primary keys
GROQ_API_KEY=your_groq_key
GOOGLE_AI_API_KEY=your_google_ai_key
GOOGLE_AI_API_KEY_2=your_google_ai_key_2

# Key rotation (comma-separated — enables failover on rate limits)
GROQ_API_KEYS=key1,key2,key3,key4,key5,key6,key7
GOOGLE_AI_API_KEYS=gemini1,gemini2,gemini3,gemini4

# Mapbox
NEXT_PUBLIC_MAPBOX_TOKEN=your_mapbox_token
MAPBOX_TOKEN=your_mapbox_token

# Twitter/X (optional — gracefully skipped if not set)
TWITTER_API_KEY=optional
TWITTER_API_SECRET=optional
TWITTER_ACCESS_TOKEN=optional
TWITTER_ACCESS_SECRET=optional

# NYC Open Data (optional — for real accident/speed data)
NYC_OPEN_DATA_TOKEN=optional
NEXT_PUBLIC_API_URL=http://localhost:8000
EOF
```

### 2. Backend

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

The server will:
- Load the prebuilt Brooklyn road graph (`data/brooklyn_graph.json.gz`) in the background
- Generate 250 road segments
- Start the real-time feed engine (5s tick interval)
- Index 12 SOP documents for RAG retrieval

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) — the landing page. Navigate to `/dashboard` for the operational view.

## Deployment

Backend on Render (`render.yaml`, Docker, free plan), frontend on Vercel.

**Render environment variables**

| Variable | Required | Purpose |
|---|---|---|
| `GROQ_API_KEY`, `GOOGLE_AI_API_KEY` | Yes | LLM keys; optional extra keys in `GROQ_API_KEYS` / `GOOGLE_AI_API_KEYS` |
| `MAPBOX_TOKEN` | Yes | Place search |
| `ADMIN_TOKEN` | Yes | Operator token for auto-post / auto-detect / key re-check |
| `ALLOWED_ORIGINS` | Yes | Comma-separated browser origins, e.g. your Vercel production URL |
| `ALLOWED_ORIGIN_REGEX` | No | Defaults to this project's `*.vercel.app` URLs |
| `TWITTER_ENABLED` | No | `true` allows tweeting (default `false`) |
| `AUTO_DETECT_INCIDENTS` | No | `true` starts with auto-detection on (default `false`) |
| `GROQ_MODEL`, `GEMINI_MODEL` | No | Model overrides |

**Vercel environment variables**: `NEXT_PUBLIC_API_URL` (the Render URL) and `NEXT_PUBLIC_MAPBOX_TOKEN`. Both are baked in at build time, so redeploy after changing them.

After deploying, open `/health`: `road_graph_loaded` should be `true` and both `llm` providers `ok`. Run the end-to-end suite against it with `TM_BASE_URL=https://<backend> pytest backend/tests -v`.

**Rebuilding data files** (only when the road graph changes; needs `pip install -r backend/requirements-dev.txt`):

```bash
cd backend
python scripts/build_road_graph.py   # brooklyn.graphml → data/brooklyn_graph.json.gz
python scripts/build_hotspots.py     # → data/hotspots.json
```

## Demo Flow

1. **Open Dashboard** → `/dashboard` — see the Brooklyn map with 250 real-time speed segments, weather in sidebar, hotspot prediction circles
2. **Click "Simulate Incident"** → triggers a HIGH severity incident on Flatbush Avenue
3. **Watch the agent pipeline**:
   - Signal Agent: 4 intersection re-timing recommendations
   - Routing Agent: Alternative diversion route with flow-based volume redistribution
   - Alert Agent: VMS signs, radio script, social media post (auto-tweeted if configured)
   - Density Agent: Vehicle density estimation
   - Supervisor: Dynamic confidence scoring, cascade risk assessment, SOP compliance
4. **Explore tabs**: Signals, Routing, Alerts, Chat, Timeline, Summary
5. **Chat** → ask "What's the emergency corridor protocol?" — cites SOP source with badge
6. **Voice Chat** → click mic, speak your question → Whisper transcribes → TTS reads response
7. **Toggle "Route Planning" mode** → search boxes appear
   - Select vehicle type: Normal / Ambulance / Police / Fire Brigade
   - Search origin + destination → 3 color-coded routes render (green/yellow/red)
   - Panel shows time, distance, density, risk + signal preemptions for emergency vehicles
8. **Digital Twin** → `/twin` — side-by-side before/after impact comparison
9. **Click "Resolve"** → clears incident, returns to normal monitoring

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Status, road-graph readiness, and per-provider LLM key checks |
| GET | `/api/state` | Current snapshot, risk map, incident |
| GET | `/api/agents` | Latest agent outputs |
| GET | `/api/signals` | Signal re-timing recommendations |
| GET | `/api/diversion` | Active diversion route |
| GET | `/api/alerts` | Alert drafts (VMS/Radio/Tweet) |
| GET | `/api/density` | Vehicle density data |
| GET | `/api/timeline` | Incident timeline events |
| GET | `/api/hotspots` | Brooklyn black-spot data |
| GET | `/api/metrics` | Evaluation metrics |
| GET | `/api/twin` | Digital twin comparison data |
| GET | `/api/documents` | RAG document index |
| POST | `/api/trigger-incident` | Trigger demo incident |
| POST | `/api/resolve-incident` | Resolve active incident |
| POST | `/api/chat` | Chat with narrative agent |
| POST | `/api/chat/voice` | Voice chat (Whisper transcription + answer + TTS audio) |
| GET | `/api/geocode?q=` | Brooklyn place search (Mapbox Search Box) |
| POST | `/api/routes` | Up to 3 diverse routes, coloured by average risk |
| GET | `/api/settings` | Auto-post, auto-detect and server capability flags |
| POST | `/api/settings/auto-post` | Toggle tweeting (needs `X-Admin-Token`, and `TWITTER_ENABLED=true`) |
| POST | `/api/settings/auto-detect` | Toggle automatic incident detection (needs `X-Admin-Token`) |
| POST | `/api/llm/check` | Re-test every LLM key now (needs `X-Admin-Token`) |
| WS | `/ws/feed` | Real-time WebSocket feed |

## Multi-Agent Pipeline

```
Feed Tick (5s)
    │
    ├─→ Risk Scorer (rule-based, no LLM)
    │
    ├─→ Anomaly Detector (statistical deviation)
    │       │
    │       ▼ (if incident detected)
    │
    ├─→ RAG Retrieval (TF-IDF, top-2 SOPs)
    │
    ├─→ [PARALLEL FAN-OUT]
    │       ├─→ Signal Agent (Groq gpt-oss-120b)
    │       ├─→ Routing Agent (road-graph diversion + Groq narration)
    │       └─→ Density Agent (simulated + optional Gemini vision)
    │
    ├─→ Alert Agent (Groq) — after routing, so alerts name the diversion
    │
    └─→ [FAN-IN] Supervisor (Gemini 2.5 Flash)
            │
            ├─→ Coherence check
            ├─→ Cascade risk assessment
            ├─→ SOP compliance validation
            └─→ Final summary + confidence scores
```

## Project Structure

```
trafficmind/
├── .env                          # API keys
├── backend/
│   ├── main.py                   # FastAPI app + WebSocket
│   ├── requirements.txt
│   ├── models/
│   │   └── schemas.py            # Pydantic models
│   ├── core/
│   │   ├── feed_engine.py        # Real-time data feed (OSMnx)
│   │   ├── risk_scorer.py        # Risk computation
│   │   ├── anomaly_detector.py   # Statistical anomaly detection
│   │   ├── graph.py              # Agent orchestrator (background task + lock)
│   │   ├── llm.py                # Shared Groq/Gemini calls: timeouts, failover
│   │   ├── llm_health.py         # Key self-check reported by /health
│   │   └── road_graph.py         # Shared road graph + KD-tree lookups
│   ├── agents/
│   │   ├── signal_agent.py       # Signal re-timing (Groq)
│   │   ├── routing_agent.py      # Diversion routing (Groq)
│   │   ├── alert_agent.py        # Public alerts (Groq)
│   │   ├── density_agent.py      # Vehicle density (Gemini)
│   │   ├── supervisor.py         # Cross-agent supervision (Gemini)
│   │   └── narrative_agent.py    # Chat interface (Gemini)
│   ├── rag/
│   │   ├── retriever.py          # TF-IDF RAG retriever
│   │   └── documents/            # 12 SOP documents
│   ├── scripts/                  # Offline builds: road graph, hotspots
│   └── tests/                    # End-to-end pytest suite
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx           # Landing page
│   │   │   ├── dashboard/page.tsx # Operational dashboard
│   │   │   ├── twin/page.tsx      # Digital twin view
│   │   │   ├── layout.tsx         # Root layout
│   │   │   └── globals.css        # Tailwind v4 theme
│   │   ├── components/
│   │   │   ├── TrafficMap.tsx     # Mapbox GL map
│   │   │   ├── Sidebar.tsx       # Status sidebar
│   │   │   ├── SignalPanel.tsx   # Signal recommendations
│   │   │   ├── RoutingPanel.tsx  # Diversion route
│   │   │   ├── AlertPanel.tsx    # Alert drafts
│   │   │   ├── ChatInterface.tsx # Chat UI
│   │   │   ├── Timeline.tsx      # Event timeline
│   │   │   └── SummaryPanel.tsx  # Supervisor summary
│   │   └── lib/
│   │       ├── types.ts           # TypeScript interfaces
│   │       ├── api.ts             # REST client
│   │       ├── store.ts           # Zustand state
│   │       ├── utils.ts           # Utilities
│   │       └── useWebSocket.ts    # WebSocket hook
│   └── .env.local                 # Frontend env vars
└── README.md
```

## Differentiators

1. **Fast inference** — Groq-hosted gpt-oss-120b; the full pipeline runs in about 2.6 s
2. **Real road network** — 250 monitored segments on the actual Brooklyn OSM graph (speeds are simulated)
3. **Format-constrained alerts** — VMS signs enforce ≤20 chars/line, tweets ≤280 chars
4. **RAG-grounded SOPs** — 12 real standard operating procedures validate recommendations + source-cited chat
5. **Digital twin** — Before/after impact visualization with quantified time savings
6. **Cascade risk assessment** — Supervisor checks if diversion routes are themselves at risk
7. **Cross-agent coherence** — Supervisor detects conflicts between signal and routing recommendations
8. **WebSocket real-time** — Live 5-second ticks with instant incident event propagation
9. **Production architecture** — Clean separation: data layer → agent layer → presentation layer
10. **Priority routing** — Emergency vehicles get edge-weight discounts + signal preemption lists
11. **Weather intelligence** — Real Weather.gov conditions factor into routing penalty scores
12. **DBSCAN hotspot prediction** — Accident cluster zones visualized as graduated risk circles
13. **Voice-first interface** — End-to-end voice: Groq Whisper STT + Web Speech TTS
14. **Key rotation failover** — Never go down on a rate limit: automatic Groq/Gemini key pool switching
15. **Social media pipeline** — Incident tweets can be auto-posted (off unless the server sets `TWITTER_ENABLED=true`)

## Team

**2AM Coders**

## License

MIT
