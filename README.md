# Pyra

**AI-Powered Wildfire Command & Intelligence Platform**

Pyra is a real-time wildfire command-support system for incident commanders and CAL FIRE dispatch operations. It aggregates satellite detections, live weather, terrain data, and unit positions into a single map-based interface, and uses Claude AI to generate dispatch recommendations, tactical briefings, and risk assessments.

Pyra is a **decision-support system** — it surfaces data and recommendations but never automates dispatch. Every action requires a human commander or dispatcher to confirm.

---

## Screenshots

> Live map with spread risk cones, unit positions, and the dispatch intelligence panel.
![1](https://cdn.discordapp.com/attachments/1487454221971492914/1487594710385033286/image.png)

![2](https://cdn.discordapp.com/attachments/1487454221971492914/1487594732753260544/image.png)

![3](https://cdn.discordapp.com/attachments/1487454221971492914/1487594760813281464/image.png)

---

## Features

### Live Map
- Fire severity markers (critical / high / moderate / low) with size scaled to acres burned
- Unit positions updating every 3 seconds with status colour coding
- Route polylines drawn for en-route units via OSRM road routing
- Click any unit on the map to preview its road route to its assigned incident

### Overlays (toggleable from the top bar)
| Overlay | What it shows |
|---|---|
| Spread Risk | Directional fire spread cone, terrain-adjusted, colour by risk level |
| Fire Growth | Projected burn area at +1h/+4h/+12h or +15/+30/+60 min |
| Fire Perimeters | Live NIFC perimeter polygons |
| Risk Heatmap | Composite risk score across all active incidents |
| Water Sources | Hydrants, lakes, reservoirs, tanks from OpenStreetMap — with unit assignments and fill times |
| Evac Zones | Order / Warning / Watch zones from ArcGIS |
| Satellite | NASA FIRMS hotspot detections |
| Weather | Draggable panel with wind, humidity, AQI per incident |

### Incident Detail Panel
- AI confidence score and loadout profile recommendation
- Fire intelligence: behavior index, rate of spread, suppression effectiveness, AQI, terrain
- Dispatch Intelligence Engine: ranked available units with route badges (FASTEST / CAUTION / AVOID) and road-distance ETA
- Dispatch Advisor: Claude evaluates your selected loadout against the system recommendation and returns OPTIMAL / ADEQUATE / SUBOPTIMAL with reasoning
- Loadout configurator: set water %, foam %, retardant %, and equipment per unit before dispatching
- SITREP Chat: ask Claude anything about the incident in natural language
- AI operational briefing (ICS format, streaming)
- Close-out checklist: units recalled, briefing generated, containment status
- Shift handoff briefing generation with auto-trigger on incident close
- AAR post-incident review (commander only)
- PDF report export

### Command Panel (`C` key)
- All active incidents ranked by composite priority score (severity, spread, structures, containment, resource gap, fire weather)
- Score tooltip explains why a CRITICAL incident may rank below a HIGH one (e.g. high containment)
- Cross-incident resource allocation suggestions (greedy nearest-unit assignment)

### Right Panel
- Active alerts with severity, type, and inline triage summary from Claude
- Click any alert to expand: AI recommendation, action list, unit selector, dispatch button
- Resolved alerts tab
- Unit roster with status filter (all / available / en route / returning)
- Draggable divider between alerts and units

### Roles
| Role | Can do |
|---|---|
| `viewer` | Read all data, no dispatch or close actions |
| `dispatcher` | Dispatch units, acknowledge alerts, generate briefings |
| `commander` | All of the above + force close incidents, AAR review |

---

## Tech Stack

**Backend**
- Python 3.11, FastAPI 0.115, SQLAlchemy 2.0, Alembic
- APScheduler (background jobs), httpx, Pydantic v2
- Anthropic Claude (`claude-sonnet-4-20250514`) for AI features
- PostgreSQL (production) / SQLite (tests)
- OSRM for road routing (public instance + optional local Docker)

**Frontend**
- React 19, Vite 8
- React-Leaflet 5 / Leaflet 1.9
- Served via nginx in Docker

**External APIs (all free tier)**
| API | Used for | Key required |
|---|---|---|
| Open-Meteo | Weather (wind, humidity) | No |
| Open-Meteo AQ | Air quality index | No |
| Open-Elevation | Terrain slope and aspect | No |
| NASA FIRMS | Satellite hotspot detections | Yes (free) |
| Overpass (OSM) | Water sources, road data | No |
| OSRM (public) | Road routing | No |
| NIFC ArcGIS | Fire perimeters | No |

---

## Getting Started

### Prerequisites
- Docker and Docker Compose
- An [Anthropic API key](https://console.anthropic.com/)
- A free [NASA FIRMS API key](https://firms.modaps.eosdis.nasa.gov/api/area/) (optional — satellite detections won't work without it)

### 1. Clone and configure

```bash
git clone https://github.com/your-org/pyra.git
cd pyra
```

Create a `.env` file in the project root:

```env
# Required
POSTGRES_PASSWORD=choose_a_strong_password
SECRET_KEY=choose_a_long_random_string
ANTHROPIC_API_KEY=sk-ant-...

# Optional
NASA_FIRMS_API_KEY=your_firms_key
CORS_ORIGINS=http://localhost:5173
ACCESS_TOKEN_EXPIRE_HOURS=8
VITE_API_URL=http://localhost:8000
```

> **Important:** `SECRET_KEY` must be set or all tokens are invalidated on every backend restart.

### 2. Start with Docker

```bash
docker compose up --build
```

This starts:
- **PostgreSQL** on port 5432
- **Alembic migrations** (runs once, waits for DB)
- **FastAPI backend** on port 8000
- **React frontend** on port 5173

Open **http://localhost:5173** in your browser.

### 3. Seed demo data

```bash
docker compose exec backend python app/scripts/seed_data.py
```

This creates 3 incidents (LNU Lightning Complex, Shasta River Fire, San Jose Structure Fire), ~104 units across CAL FIRE stations, and supporting data.

### 4. Log in

| Username | Password | Role |
|---|---|---|
| `commander` | `pyra2025` | Full access |
| `dispatcher` | `pyra2025` | Dispatch + briefings |
| `viewer` | `pyra2025` | Read only |

---

## Local Development (without Docker)

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Set up your .env (see above), then:
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies all `/api/*` requests to `localhost:8000` automatically.

### Seed data

```bash
cd backend
python app/scripts/seed_data.py
```


---

## Optional: Local OSRM

By default Pyra uses the public OSRM instance at `router.project-osrm.org`. For offline use or better performance, you can run OSRM locally:

```bash
# Download a region (e.g. California)
wget https://download.geofabrik.de/north-america/us/california-latest.osm.pbf -P osrm-data/

# Pre-process
docker run -t -v $(pwd)/osrm-data:/data osrm/osrm-backend osrm-extract -p /opt/car.lua /data/california-latest.osm.pbf
docker run -t -v $(pwd)/osrm-data:/data osrm/osrm-backend osrm-partition /data/california-latest.osrm
docker run -t -v $(pwd)/osrm-data:/data osrm/osrm-backend osrm-customize /data/california-latest.osrm

# Start with the osrm profile
docker compose --profile osrm up
```

---

## API Reference

Interactive docs available at **http://localhost:8000/docs** once the backend is running.

| Prefix | Description |
|---|---|
| `/api/auth` | Login, current user |
| `/api/incidents` | CRUD, close-out checklist, close |
| `/api/units` | List, GPS update, route preview |
| `/api/alerts` | List, acknowledge, clear |
| `/api/dispatch` | Approve dispatch, alert dispatch |
| `/api/recommendations` | AI unit recommendations, feedback |
| `/api/dispatch-advice` | Claude loadout assessment |
| `/api/dispatch/loadout` | Per-unit loadout configuration |
| `/api/intelligence` | Spread risk cone, fire behavior, composite risk |
| `/api/intelligence/fire-growth` | Time-based growth projections |
| `/api/intelligence/evac-zones` | Evacuation zone polygons |
| `/api/routes` | Saved routes, safety scoring |
| `/api/water-sources` | OSM water sources with unit assignments |
| `/api/multi-incident` | Priority ranking, resource allocation |
| `/api/briefing` | Operational briefing (streaming), shift handoff |
| `/api/chat` | SITREP chat (streaming) |
| `/api/review` | Post-incident AAR (streaming) |
| `/api/heatmap` | Risk heatmap data |
| `/api/perimeters` | NIFC fire perimeters |
| `/api/report` | PDF incident report |
| `/api/audit` | Audit log |
| `/api/ingestion` | Manual hotspot ingestion, job status |

---

## Background Jobs

| Job | Interval | What it does |
|---|---|---|
| Simulation | 2 s | Advance unit positions, update containment, vary weather, generate alerts |
| Route builder | 10 s | Build OSRM routes for en-route units |
| Weather | 5 min | Fetch wind + humidity from Open-Meteo |
| NASA FIRMS | 10 min | Sync satellite hotspots, create/update incidents |
| AQI | 30 min | Fetch air quality index from Open-Meteo AQ |
| Terrain | 1 hr | Enrich incidents with slope, aspect, elevation |
| Road data | 2 hr | Seed access routes from OpenStreetMap |

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `C` | Toggle Command Panel (multi-incident priority) |
| `M` | Toggle satellite layer |
| `Esc` | Close detail panel / clear routes |

---

## Project Structure

```
pyra/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI route handlers
│   │   ├── core/         # Config, auth, DB, scheduler
│   │   ├── ext/          # External API clients (FIRMS, Overpass, elevation)
│   │   ├── intelligence/ # Recommendation engine, spread risk, fire behavior
│   │   ├── models/       # SQLAlchemy ORM models
│   │   ├── schemas/      # Pydantic schemas
│   │   ├── services/     # Simulation, routing, weather, movement, AQI
│   │   └── scripts/      # seed_data.py
│   ├── alembic/          # Database migrations
│   └── tests/            # pytest integration tests
├── frontend/
│   └── src/
│       ├── api/          # Centralized API client
│       ├── components/   # React components (map, panels, overlays)
│       ├── context/      # Auth context
│       ├── services/     # routeEngine.js (client-side routing logic)
│       └── utils/        # timeUtils
├── docker-compose.yml
└── Makefile
```

---

## Running Tests

```bash
cd backend
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=app --cov-report=term-missing
```

Tests cover auth and roles, incident CRUD, unit management, dispatch flow, alerts, ingestion, multi-incident ranking, route safety, and close-out checklist.

---

## Disclaimer

Pyra is a development project for exploring AI-assisted wildfire response coordination. It is designed to provide **decision support** to trained professionals, not to replace their judgment. Do not use in real emergency operations without thorough validation and certification.
