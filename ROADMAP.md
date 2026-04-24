# OpenMobility OS — Roadmap

This document tracks the development phases of OpenMobility OS from the initial
prototype through to a full open-source release and beyond.

Every phase is independently deployable — `docker compose up --build` produces a
working platform at the end of each one.

See [CHANGELOG.md](CHANGELOG.md) for what has already shipped.

---

## MVP Phases (0–7)

### ✅ Phase 0 — Foundation
> Governance, Docker skeleton, Django boots with PostGIS.

- [x] `CLAUDE.md` — binding contributor guide (philosophy, versioning, changelog policy)
- [x] `VERSION` file (`0.1.0`) as single source of truth
- [x] `CHANGELOG.md` in Keep a Changelog format
- [x] `README.md` with working quickstart
- [x] `Dockerfile` + `docker-compose.yml` + `entrypoint.sh`
- [x] `.env.example` — all config documented
- [x] Django project skeleton with seven apps: `workspaces`, `datasets`, `connectors`,
      `measures`, `goals`, `maps`, `api`
- [x] Split settings (`base` / `development` / `production`)
- [x] GeoDjango + PostGIS database backend
- [x] Internationalization infrastructure (German + English)

---

### ✅ Phase 1 — Workspace Core + Landing
> Multi-workspace architecture visible, Leipzig as first demo.

- [x] `Workspace`, `WorkspaceGoal`, `District` models + migrations
- [x] Platform landing page listing all workspaces with demo badges
- [x] Workspace dashboard with KPIs, goals, and top measures
- [x] Path-based multi-tenancy (`/<workspace-slug>/...`)
- [x] Three deployment modes via env var: `public-demo`, `single-city`, `multi-city`
- [x] `seed_demo` management command reading from `config/workspaces/*.yaml`
- [x] Three demo workspaces: **Leipzig** (rich data), **Musterstadt** (sparse/small-town),
      **Muster-Landkreis** (region, empty — illustrates multi-city concept)
- [x] Language switcher (DE / EN)

---

### ✅ Phase 2 — Map + GeoJSON API
> Interactive MapLibre GL JS map with dynamic layers.

- [x] `NormalizedFeatureSet` model
- [x] GeoJSON feature API `/api/v1/<slug>/features/<layer>/`
- [x] Workspace map view `/<slug>/map/` with MapLibre GL JS
- [x] Layer selector (Alpine.js toggles)
- [x] Auto-fit to `workspace.bounds`
- [x] Configurable tile URL via `MAP_TILE_URL` env var (swap OSM for self-hosted tiles)
- [x] Measures GeoJSON endpoint `/api/v1/<slug>/measures.geojson`

---

### ✅ Phase 3 — Connectors (deep on three)
> Real data in, normalized GeoJSON out.

- [x] `BaseConnector` interface with JSON-Schema–based config (drives UI form automatically)
- [x] **`CSVConnector`** — URL fetch, auto-detection of coordinate columns, WKT geometry,
      configurable encoding and delimiter
- [x] **`GeoJSONConnector`** — URL fetch, property remapping, geometry-type filtering
- [x] **`OSMOverpassConnector`** — 8 built-in query templates (bike network, streets,
      transit stops, schools, parking, trees, parks & green, custom) + configurable
      Overpass endpoint
- [x] **`ManualConnector`** — accepts pre-normalized GeoJSON in config; for data-poor places
- [x] Typed stubs with clear `NotImplementedError` messages: `GTFSConnector`,
      `CKANConnector`, `WFSConnector`, `RESTConnector`
- [x] Data hub UI `/<slug>/data/` — source list, sync status, error display
- [x] Add-source form `/<slug>/data/add/`
- [x] Sync + test-connection endpoints (admin-token protected)

---

### ✅ Phase 4 — Measures Engine + Scoring
> Rule-based measure generation with fully transparent scores.

- [x] `Measure` + `MeasureScore` models
- [x] Nine scoring dimensions: `climate`, `safety`, `quality_of_life`, `social`,
      `feasibility`, `cost`, `visibility`, `political`, `goal_alignment`
- [x] Configurable dimension weights per workspace
- [x] Four strategy presets: Quick Wins, Vision Zero, Maximum Climate Impact,
      Fair Citywide Distribution
- [x] Four initial rules: missing bike lanes, transit coverage gap, accident hotspot,
      school routes
- [x] `generate_measures` management command + admin-token–protected trigger endpoint
- [x] Measures list `/<slug>/measures/` with filter by strategy, category, effort level
- [x] Shareable measure detail page `/<slug>/measures/<slug>/` with score breakdown,
      rationale, and raw evidence

---

### ✅ Phase 5 — Methodology & Transparency
> Every number traceable to its source.

- [x] Global methodology page `/methodology/` — scoring formula, weight table,
      strategy explanations, connector overview
- [x] Per-workspace methodology `/<slug>/methodology/` — data sources with license,
      attribution, record count, last synced
- [x] Each `MeasureScore` exposes its rationale and source links
- [x] `/about/` — self-hosting guide, deployment modes, current version

---

### ✅ Phase 6 — New-Workspace Wizard + Single-City Mode
> Any municipality in the world can be added.

- [x] Wizard `/workspaces/new/` — name, slug, country, language, kind, bounding box,
      descriptions
- [x] Slug auto-generation from name (Alpine.js)
- [x] Single-city deployment: landing redirects to `DEFAULT_WORKSPACE_SLUG`
- [x] Admin login / logout (`ADMIN_TOKEN`-based session)
- [x] Public REST API `/api/v1/` — workspaces list, workspace detail, measures list,
      platform meta (`/api/v1/meta/`)

---

### ✅ Phase 7 — Open-Source Release Readiness
> Repo is ready for public discovery and contributions.

- [x] `CONTRIBUTING.md` with first-contribution guide
- [x] `CODE_OF_CONDUCT.md`
- [x] `SECURITY.md` — responsible disclosure process
- [x] GitHub Actions CI: lint (Ruff), `manage.py check`, Docker build check
- [x] Issue templates (bug report, feature request, new-connector proposal)
- [x] PR template referencing CLAUDE.md governance rules
- [x] License attribution for third-party dependencies (OSM, MapLibre, Tailwind, HTMX, ...) — `NOTICE` file
- [x] Screenshots placeholder in README (to be replaced with real screenshots on first public deployment)
- [x] Public demo deployment guide in README

---

## Post-MVP Phases (8+)

These features are **not in the MVP**, but the architecture is already prepared for them.

---

### ✅ Phase 8 — Accidents as a First-Class Layer
> Full accident data with mode classification.

- [x] `accidents` layer kind with standardized property schema:
  ```json
  {
    "severity": "fatal|serious|minor",
    "date": "ISO-8601",
    "time_of_day": "morning|day|evening|night",
    "weather": "dry|wet|snow|fog|...",
    "involved_modes": ["pedestrian", "cyclist", "car", "truck", "bus", "motorbike", "scooter", "tram"],
    "vulnerable_road_user": true,
    "intersection_type": "t_junction|crossing|roundabout|none",
    "speed_limit": 30,
    "street_category": "residential|main|highway|..."
  }
  ```
- [x] Admin filter UI: severity + involved-mode checkboxes on the map page
- [x] Map layer with severity color-coded circle markers (fatal=dark red, serious=orange, minor=yellow)
- [x] Extended `accident_hotspot` rule — weighted by severity (fatal×3, serious×2, minor×1)
      and generates a second VRU-specific measure when cyclist/pedestrian involvement is high
- [x] `UnfallatlasConnector` — Germany-specific; reads Destatis Unfallatlas CSV format
- [x] `AccidentCSVConnector` — generic international accident CSV importer with configurable column mapping
- [x] Cluster heatmap / density visualization — severity-weighted heatmap layer with Circles/Heatmap toggle

---

### Phase 9 — Public Transit Network as a First-Class Layer
> Full GTFS support, transit coverage analysis.

- [ ] Full `GTFSConnector` implementation (static GTFS zip — routes, stops, trips, calendar)
- [ ] New layer kinds: `transit_routes`, `transit_coverage` (300m / 500m buffer polygons)
- [ ] `transit_stops` enriched with: accessibility status, average headway, night service
- [ ] New measure categories: `transit_frequency`, `transit_accessibility`, `transit_gap`
- [ ] KPIs: average headway, population coverage %, night connections, barrier-free stops %
- [ ] GTFS-RT adapter for live delay visualization (see Phase 11)

---

### Phase 10 — Extended Admin Visibility
> Operators see health and quality across all workspaces.

- [ ] Admin dashboard `/admin/` with:
  - All workspaces + data quality traffic-light indicator
  - Connector health (last sync, error rate per source)
  - Measures generated per workspace
  - Audit log
- [ ] Accident filter builder (all properties as combinable filters)
- [ ] Side-by-side workspace comparison view
- [ ] Export: measures as PDF report or CSV

---

### Phase 10b — Climate Adaptation: Sponge City & Heat Resilience
> Make cities more water-absorbent and heat-resistant.

- [ ] New layer kinds:
  - `trees` — tree cadastre (CSV, GeoJSON, Overpass `natural=tree`)
  - `green_areas` — parks, meadows, gardens (OSM `landuse=grass/park/meadow`, WFS)
  - `sealed_surfaces` — sealing data from aerial analysis or open datasets
  - `heat_corridors` — cold-air / fresh-air corridors (GeoJSON from climate assessments)
  - `water_bodies` — rivers, retention areas, rainwater management
- [ ] Standardized property schema:
  ```json
  {
    "type": "tree|green_area|sealed_surface|open_corridor|water_body|permeable_pavement",
    "canopy_area_m2": 12.5,
    "sealed_pct": 0.85,
    "heat_island_score": 0.72,
    "flood_risk": "low|medium|high",
    "last_measured": "2024-06-01"
  }
  ```
- [ ] New measure categories:
  - `tree_planting` — new plantings, replacements after tree loss
  - `desealing` — removing asphalt from car parks, schoolyards, brownfields
  - `green_corridor` — protect and create green axes and fresh-air channels
  - `bioswale` — swale-infiltration systems, rainwater management
  - `cool_spot` — shaded seating, drinking fountains, cooled public spaces
- [ ] New scoring dimension: `heat_resilience`
- [ ] Rule engine: `rule_heat_island_greening` — finds heavily sealed, tree-less areas
- [ ] Map layers: heat-risk overlay, tree cadastre, desealing potential map
- [ ] OSM Overpass templates: `trees`, `parks_and_green` (already in codebase)

---

### Phase 11 — Further Extensions
> Long-term community-driven additions.

- [ ] GTFS-RT adapter for live transit data
- [ ] Before / after map slider for measures
- [ ] Citizen feedback on measures (comment thread per measure)
- [ ] Languages beyond DE/EN (FR, IT, PL, CZ, NL, ...)
- [ ] Full user and role system (django-allauth or OIDC) — optional upgrade from ADMIN_TOKEN
- [ ] Federation: instances share measure best-practices across installations
- [ ] Full `CKANConnector`, `WFSConnector`, `RESTConnector` implementations
- [ ] Air quality monitoring (integration with UBA API, Luftdaten.info / Sensor.Community)
- [ ] openCode / DE-Government platform integration and mirroring

---

## Contributing to the Roadmap

Found a use case not covered here? Open an issue with the label `roadmap`.

Items marked `[ ]` are open for contribution. Read [CLAUDE.md](CLAUDE.md) and
[CONTRIBUTING.md](CONTRIBUTING.md) before starting work on a phase.
