# Pyra

Pyra is an AI-assisted wildfire command platform built around a live operational map, incident-centric resource coordination, and human-confirmed dispatch workflows.

It is designed as a decision-support system, not an automated dispatch engine. Pyra can rank units, score routes, generate briefings, suggest loadouts, surface shortages, and triage alerts, but dispatch and close-out actions remain explicitly human-controlled.

Live Demo - https://pyra-ai.vercel.app/

## What Pyra Is

Pyra combines four layers into a single command surface:

1. Real-time incident state: fires, unit positions, alerts, containment, weather, AQI, terrain, and perimeters.
2. Operational intelligence: spread-risk modeling, fire-behavior estimates, composite risk scoring, route safety scoring, and resource recommendation logic.
3. AI assistance: tactical recommendation summaries, dispatch advice, alert triage, per-unit loadout suggestions, SITREP chat, operational briefings, handoff briefings, and AAR review.
4. Command UX: a map-dominant interface with floating tactical panels for incident detail, engaged units, unified activity, and cross-incident prioritization.

## Distribution

Pyra ships as both a containerized web application and a standalone desktop app.

### Desktop (Electron)

The Electron wrapper packages the FastAPI backend and React frontend into a single native application for macOS, Windows, and Linux. The desktop build:

- Spawns the Python/uvicorn backend as a child process on `127.0.0.1:8000`.
- Loads the built frontend from `frontend/dist/` or a local Vite dev server in development.
- Exposes IPC handlers (`get-api-key`, `set-api-key`, `restart-backend`) via a context-isolated preload so the Settings panel can manage the Anthropic API key and hot-restart the backend without touching the terminal.
- Packages to `.dmg`/`.zip` on macOS, `.exe`/`.portable` on Windows, and `.AppImage` on Linux via `electron-builder`.

Run in development:

```
npm run dev
```

Build a distributable:

```
npm run build
```

### Containerized

The default runtime shape is four services via `docker-compose`:

- `db` — PostgreSQL 16 for persistent operational state.
- `migrate` — One-shot Alembic migration runner.
- `backend` — FastAPI application serving operational APIs, scheduling, AI endpoints, and simulation/enrichment jobs.
- `frontend` — Vite-built React application served behind a lightweight web container.

An optional `osrm` service can be started for local routing instead of relying on the public OSRM endpoint.

## Interface Model

The frontend is a map-first React/Leaflet application with four persistent operational surfaces:

- Top bar: system metrics, health state, overlay toggles, command view toggle, user/settings access.
- Left sidebar: engaged units for the currently selected incident, filtered to active operational states (`en_route`, `on_scene`, `returning`).
- Right panel: unified activity feed that merges alerts and timeline-style incident events, plus a system-wide unit roster.
- Incident detail panel: the primary tactical workspace for a selected incident.

The map remains the center of gravity. Panels are secondary, floating controls layered over the map rather than structural page columns.

## Core Operational Surfaces

### Live Map

The map renders:

- Severity-coded fire markers with animated heat/glow treatment.
- Smoothed unit motion with state-coded markers and click feedback.
- Callsign labels at higher zoom levels.
- Selected-unit route previews and per-unit operational routes.
- Spread-risk overlay in fire/live map modes.
- Toggleable overlays for fire growth, perimeters, heatmap, evac zones, water sources, satellite, and weather.

Map interaction is designed around tactical confirmation:

- Clicking a fire selects the incident.
- Clicking a unit focuses it and can enter follow/tracking mode.
- Camera transitions use eased `flyTo`, `panTo`, and `flyToBounds` movements without changing routing logic.

### Incident Detail Panel

This is the deepest workflow surface in the app. For a selected incident, it exposes:

- Recommendation profile and confidence.
- Situation summary and fire intelligence metrics.
- Recommended unit types, including filled-vs-unfilled status.
- Already-deployed units actively committed to that incident.
- Dispatch Intelligence, which ranks candidate units by fit and route posture.
- Direct unit selection and route previewing.
- Dispatch advice against current selection.
- AI loadout configuration before dispatch approval.
- SITREP chat, AI operational briefing, PDF report export, close-out workflow, and post-incident review.

### Activity System

The right panel merges two previously separate surfaces into one activity model:

- Alerts: severity-driven operational notifications with inline AI triage and dispatch workflow.
- Timeline events: incident lifecycle and detection events presented in the same stream.

This feed can collapse to a narrow floating rail and expand back into full tactical context. System units remain available in the lower section with status filters.

### Command View

The command panel is a multi-incident prioritization surface. It ranks incidents using composite risk logic and supports higher-level allocation decisions across the incident set.

### Settings Panel

The settings panel surfaces user-level configuration. In the Electron build it also exposes Anthropic API key management and a backend restart trigger via IPC, so the app can be fully configured without opening a terminal.

## Intelligence and Decision Logic

Pyra uses both deterministic scoring and AI-assisted interpretation.

### Deterministic engines

- `recommendation_engine.py`
  Produces incident recommendations, loadout profiles, unit type demand, confidence, and tactical notes from incident attributes and route context.

- `unit_selection.py`
  Converts recommendation demand into actual candidate units by subtracting already-committed resources, ranking available units, and reporting shortfalls.

- `route_safety.py` and `routing.py`
  Build route geometry, assign route safety state, and normalize route-related reasoning. Routing uses a multi-tier fallback chain: local OSRM → public OSRM-A → public OSRM-B → ORS. Each endpoint is health-tracked with exponential backoff (60 s → 120 s → 240 s, capped at 300 s).

- `fire_behavior.py`, `composite_risk.py`, `spread_risk.py`
  Estimate fire behavior, composite incident risk, and directional spread posture from weather, terrain, AQI, and incident state.

### Simulation engine

The backend continuously evolves incident state. Key mechanics:

- **Containment**: tracked per-incident with a 12-minute hold at 100% before slow decay begins. Each on-scene unit contributes `+0.06` containment per tick; 2–3 full dispatch batches bring a typical incident to 100% in under 10 minutes.
- **Weather variation**: wind and humidity fluctuate each tick (`±2.0 mph`, `±1.5 %`) around a base reading.
- **Weather alerts**: automatic alerts fire when wind exceeds 25 mph or humidity drops below 12%.
- **Alert pruning**: unacknowledged alerts are capped at 15 per incident, acknowledged at 50, and 500 globally, to prevent feed saturation.

### AI-assisted flows

Anthropic-backed endpoints are used where freeform reasoning is useful:

- Dispatch advice: assess whether a selected deployment is optimal, adequate, or suboptimal.
- Loadout generation: recommend per-unit fluid/equipment configuration from a structured equipment database covering engines, hand crews, dozers, water tenders, helicopters, air tankers, command units, and rescue units. Results are LRU-cached.
- Alert triage: summarize operational significance and likely response posture. Results are TTL-cached (120 s) and keyed to incident state.
- Briefing generation: operational incident briefing and handoff briefing.
- SITREP chat: interactive incident Q&A.
- AAR review: post-incident evaluation.

Pyra also includes non-AI fallbacks or rule-based support where appropriate, so the interface degrades gracefully when an AI call fails or a key is absent.

## Data Sources and Enrichment

Pyra fuses internal state with multiple external feeds:

- Open-Meteo: weather enrichment.
- Open-Meteo AQ: AQI enrichment with alert severity mapping.
- Open-Elevation: terrain enrichment.
- NASA FIRMS: hotspot ingestion and satellite-aware incident updates.
- Overpass / OpenStreetMap: water sources and road-derived context.
- NIFC ArcGIS: fire perimeters.
- OSRM: road routing, with optional local OSRM runtime and public fallback chain.

These are not presented as isolated widgets. They are normalized into incident state, overlays, routing, and recommendation logic.

## Backend

The backend is a FastAPI application organized by operational concern, with `slowapi` rate limiting on sensitive endpoints.

### API domains

- `/api/auth` — Authentication and current-user identity.
- `/api/incidents` — Incident state, close-out checklist, and closure actions.
- `/api/units` — Unit inventory and location updates.
- `/api/alerts` — Alert lifecycle, acknowledgement, clearing, and statistics.
- `/api/dispatch` — Human-confirmed dispatch approval and alert dispatch.
- `/api/recommendations` — Dispatch intelligence and feedback capture.
- `/api/dispatch-advice` — AI assessment of a proposed dispatch selection.
- `/api/dispatch/loadout` — AI loadout recommendation and fallback handling.
- `/api/intelligence` — Fire behavior, spread risk, recommendation summary, alert recommendation, and intelligence aggregation.
- `/api/routes` — Route safety and route-related metadata.
- `/api/water-sources` — Water source discovery and operational support data.
- `/api/multi-incident` — Cross-incident prioritization.
- `/api/briefing` — Operational briefing and handoff generation.
- `/api/chat` — SITREP chat stream.
- `/api/review` — Post-incident review stream.
- `/api/report` — PDF incident report export.
- `/api/audit` — Audit logging with cryptographic checksum integrity verification and CSV export. Verification is commander-only.
- `/api/ingestion` — Manual or scheduled ingestion status.
- `/health` — Multi-component health check (database pool, AI key readiness).

### Background jobs

Pyra is not a static CRUD backend. It continuously evolves operational state via scheduled services:

- simulation updates
- route generation / refresh
- weather enrichment
- AQI enrichment
- FIRMS ingest
- terrain enrichment
- road / access enrichment

This gives the UI a continuously moving command picture instead of a manually refreshed dashboard.

## Frontend

The frontend is a React 19 + Vite 8 application using React-Leaflet 5 for the operational map.

### Primary components

- [App.jsx](frontend/src/App.jsx)
  Top-level orchestration, polling, auth gate, panel composition, keyboard shortcuts, and layout geometry.

- [IncidentMap.jsx](frontend/src/components/IncidentMap.jsx)
  Core map rendering, marker systems, map camera control, route overlays, follow mode, and map legend.

- [LeftSidebar.jsx](frontend/src/components/LeftSidebar.jsx)
  Incident-specific engaged-unit rail with compact/scroll behavior.

- [RightPanel.jsx](frontend/src/components/RightPanel.jsx)
  Unified activity feed and system unit roster.

- [IncidentDetailPanel.jsx](frontend/src/components/IncidentDetailPanel.jsx)
  Tactical incident workspace.

- [DispatchRecommendations.jsx](frontend/src/components/DispatchRecommendations.jsx)
  Dispatch intelligence candidate ranking and selection flow.

- [LoadoutConfigurator.jsx](frontend/src/components/LoadoutConfigurator.jsx)
  Per-unit resource/loadout configuration prior to dispatch approval.

- [TopBar.jsx](frontend/src/components/TopBar.jsx)
  System metrics and overlay toggles.

- [SettingsPanel.jsx](frontend/src/components/SettingsPanel.jsx)
  User settings; in the Electron build exposes API key management and backend restart.

- [AuditLogPanel.jsx](frontend/src/components/AuditLogPanel.jsx)
  Audit log viewer with integrity verification status and CSV export trigger.

- [PostIncidentReview.jsx](frontend/src/components/PostIncidentReview.jsx)
  Streaming post-incident AAR surface.

- [SitrepChat.jsx](frontend/src/components/SitrepChat.jsx)
  Interactive SITREP Q&A chat.

- [WeatherPanel.jsx](frontend/src/components/WeatherPanel.jsx)
  Atmospheric conditions overlay panel.

- [Toast.jsx](frontend/src/components/Toast.jsx)
  System-wide toast notification surface for operational feedback.

### Map overlays

- `EvacZonesOverlay.jsx` — Evacuation zone polygons.
- `FireGrowthOverlay.jsx` — Fire growth projection.
- `FirePerimetersOverlay.jsx` — NIFC perimeter boundaries.
- `RiskHeatmapOverlay.jsx` — Composite risk heatmap.
- `SpreadRiskOverlay.jsx` — Directional spread risk.
- `WaterSourcesOverlay.jsx` — Water source markers.

### Interaction model

The frontend intentionally avoids hard page segmentation:

- Panels are floating and glass-tinted.
- Hover and press interactions are standardized.
- Alerts and timeline events are unified.
- Collapsible surfaces minimize map obstruction.
- Key tactical actions stay one or two steps from the map.
- Toast notifications provide immediate feedback on dispatch, alert, and system events.

## Roles and Permissions

Pyra enforces role-based access:

- `viewer` — Read-only access to operational data.
- `dispatcher` — Dispatch operations, alert acknowledgement, and briefing-related actions.
- `commander` — Full operational access, including higher-authority workflows such as close-out, review, and audit log verification.

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `Esc` | Close panels / clear active tactical surfaces |
| `C` | Toggle command view |
| `M` | Toggle satellite layer |
| `1` | Toggle evac zones |
| `2` | Toggle fire growth |
| `3` | Toggle perimeters |
| `4` | Toggle heat map |
| `5` | Toggle satellite layer |
| `6` | Toggle weather |
| `7` | Toggle water sources |
| `Enter` | Confirm actions or send chat where applicable |

## Repository Layout

```text
PyraAI/
├── electron/
│   ├── main.js
│   └── preload.js
├── backend/
│   ├── alembic/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── ext/
│   │   ├── intelligence/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── scripts/
│   │   ├── services/
│   │   └── utils/
│   └── tests/
├── frontend/
│   └── src/
│       ├── api/
│       ├── components/
│       ├── context/
│       ├── services/
│       └── utils/
├── package.json
├── docker-compose.yml
└── README.md
```

## Runtime Stack

### Desktop

- Electron `28`
- electron-builder `24`

### Backend

- FastAPI `0.115.0`
- SQLAlchemy `2.0.36`
- Pydantic `2.9.2`
- APScheduler `3.10.4`
- Anthropic SDK `0.40.0`
- Alembic `1.13.3`
- slowapi `0.1.9`
- PostgreSQL 16

### Frontend

- React `19.2.4`
- React DOM `19.2.4`
- React-Leaflet `5.0.0`
- Leaflet `1.9.4`
- Vite `8.0.0`
- Tailwind CSS `4.2.1`

## Deployment Notes

Pyra expects a backend secret, database connection, and Anthropic API key for full capability. A NASA FIRMS key enables hotspot ingestion. If a local OSRM container is present, the backend targets it for routing; otherwise a public OSRM fallback chain is used automatically.

In the Electron desktop build, the Anthropic API key can be set and persisted via the Settings panel without touching a `.env` file directly.

## Operational Boundary

Pyra is built to support wildfire command reasoning, not replace it.

- It can recommend.
- It can rank.
- It can summarize.
- It can project.
- It does not autonomously dispatch or close incidents.

That boundary is part of the system design, not just a UI warning.
