<img width="1248" height="832" alt="OMOS_e1" src="https://github.com/user-attachments/assets/96b2105a-cbf2-4324-bbc0-2f86815f8ae6" />


# OpenMobility OS

**Version:** 0.46.0 (pre-release) — see [CHANGELOG.md](CHANGELOG.md)
**License:** See [LICENSE](LICENSE)

> The open, free, self-hostable operating system between open mobility data
> and political decisions. For any municipality. In any country.

OpenMobility OS is a decision, prioritization, and transparency platform
for the mobility transition. It is **not** a consumer routing tool. It is
built for municipalities, city planning departments, mobility and climate
offices, local politics, civic initiatives, journalists, and researchers.

It answers questions like:

- Which measures should a municipality prioritize first?
- Where are the biggest levers for climate, safety, and quality of life?
- Which streets, corridors, or neighborhoods need intervention first?
- Which measures are quick to implement, politically viable, and
  data-backed?
- How can these decisions be explained to the public?

<img width="240" height="240" alt="omos2_heaptmap" src="https://github.com/user-attachments/assets/5c9ebc1c-b87b-484d-a5fe-6e1dfe1411ac" />

Leipzig (Germany) and Utrecht (Netherlands) are the two real-city demo
workspaces — one developing its cycling infrastructure, the other a
world-leading cycling city. Both ship real data connectors out of the box
(Leipzig adds a live UBA air-quality feed; Utrecht adds the OVapi
Netherlands transit GTFS), and any remaining placeholder layer is clearly
labelled *illustrative demo* so it is never mistaken for real data. The
platform is **city-agnostic** from day one.
Any city, small town, municipality, or region worldwide can be added
through open data, APIs, and configuration — regardless of country,
language, data source, or administrative structure.

## Table of Contents

- [Deployment Modes](#deployment-modes)
- [Screenshots](#screenshots)
- [Quickstart](#quickstart)
- [Core Features (MVP)](#core-features-mvp)
- [Using the Platform](#using-the-platform) → [full guide in docs/USER_GUIDE.md](docs/USER_GUIDE.md)
- [Architecture](#architecture)
- [Production Deployment](#production-deployment) → [full guide in docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [Roadmap](#roadmap)

## Deployment Modes

OpenMobility OS supports three realistic operating models from the same
codebase:

1. **Single-city** — one municipality self-hosts its own instance. Set
   `DEPLOYMENT_MODE=single-city` and `DEFAULT_WORKSPACE_SLUG=<your-city>`.
2. **Multi-city** — a county, region, transport association, or federal
   state hosts one instance for many places as separate workspaces. Set
   `DEPLOYMENT_MODE=multi-city`.
3. **Public demo** — an open public instance showcasing example workspaces.
   Set `DEPLOYMENT_MODE=public-demo`. This is the default.

## Screenshots

| Platform landing | Workspace dashboard | Interactive map |
|---|---|---|
| <img width="1293" height="890" alt="grafik" src="https://github.com/user-attachments/assets/7427c722-1633-4c8e-abac-444e78b84450" /> | <img width="1271" height="1033" alt="grafik" src="https://github.com/user-attachments/assets/ef2cebb8-5547-4748-953e-88e2e169dd58" /> | <img width="1293" height="1275" alt="grafik" src="https://github.com/user-attachments/assets/e1a5cfdb-8c90-4e88-a062-6a7bfe43185a" /> |


| Measures list | Measure detail | Data hub |
|---|---|---|
| <img width="1301" height="963" alt="grafik" src="https://github.com/user-attachments/assets/61d8ce69-d792-4a27-914a-2eb82c4cd391" /> | <img width="1306" height="1159" alt="grafik" src="https://github.com/user-attachments/assets/8140c9d5-7eae-4b13-8e40-e0e3296cf474" /> | <img width="1323" height="922" alt="grafik" src="https://github.com/user-attachments/assets/05cb7c24-af08-4915-b320-333c54db5af3" /> |
 


> Run `docker compose up --build` locally to see the full platform today.

## Quickstart

**Requirements:** Docker and Docker Compose (see
[docker.com](https://www.docker.com/products/docker-desktop) for installation).

### One-command setup (automatic secrets)

```bash
git clone https://github.com/richardkfm/openmobility-os.git
cd openmobility-os
cp .env.example .env
# Auto-generate secure random values for SECRET_KEY and ADMIN_TOKEN
python3 -c "import secrets; print(f'SECRET_KEY={secrets.token_hex(50)}'); print(f'ADMIN_TOKEN={secrets.token_hex(32)}')" >> .env
docker compose up --build
```

Open **http://localhost:8000** — you should see the platform landing page with
four demo workspaces: **Leipzig**, **Utrecht**, **Musterstadt**, and **Muster-Landkreis**.

### Step-by-step (for novice users)

1. **Install Docker** (if not already installed)
   - Download [Docker Desktop](https://www.docker.com/products/docker-desktop)
   - Run it and follow the installer

2. **Clone the repository**
   ```bash
   git clone https://github.com/richardkfm/openmobility-os.git
   cd openmobility-os
   ```

3. **Create `.env` with secure secrets**
   ```bash
   cp .env.example .env
   ```

4. **Fill in random values** (copy-paste the entire command below)
   ```bash
   python3 << 'EOF'
   import secrets
   with open('.env', 'a') as f:
       f.write(f'\nSECRET_KEY={secrets.token_hex(50)}\n')
       f.write(f'ADMIN_TOKEN={secrets.token_hex(32)}\n')
   print("✓ Secrets added to .env")
   EOF
   ```

5. **Start the platform**
   ```bash
   docker compose up --build
   ```

6. **Open in your browser**
   - Visit http://localhost:8000
   - You should see four demo workspaces immediately
   - To add a new workspace: click "New workspace" (requires ADMIN_TOKEN from `.env`)

7. **To stop**, press `Ctrl+C` in the terminal. Data persists in the
   `postgres_data` volume until you run `docker compose down -v`.

## Core Features (MVP)

- **Multi-workspace** — arbitrary number of cities per installation
- **Interactive maps** — MapLibre GL JS with configurable tile sources
- **Map legend & distinct markers** — an always-on legend below the map lists
  every active layer with a swatch shaped like how it is drawn; place-type point
  layers (schools, parking, transit stops, EV chargers, public buildings) use
  recognisable glyph icons instead of identical dots
- **Per-layer display controls** — each layer has a display-mode switch (dots /
  icons / heatmap for points, normal / thick / dotted lines, filled / outline
  areas), an opacity slider, and a "focus" toggle that dims every other layer so
  one stands out. All choices are remembered in the browser
- **Base map switcher** — pick a Light, Dark, or Satellite base map from a
  control on the map, independent of the UI theme; the choice is remembered
- **Full-screen map mode** — expand the map, its on-map controls, and the
  legend to the whole screen for presentations; Escape returns to the page
- **Light & dark mode** — a header toggle switches the whole UI between light and
  dark; the choice is remembered and defaults to the visitor's OS preference.
  The map base map follows the theme until you pick one explicitly
- **Data hub** — browser-based connector management:
  - Add, edit, sync, enable/disable, and delete data sources from the UI
  - Upload local CSV or GeoJSON files directly (no remote URL required)
  - Connector description and config-field reference shown inline when adding a source
  - Activate / deactivate toggle: disabled sources disappear from the map without being deleted
- **Data connectors** (fully implemented):
  - CSV (URL or direct file upload) with column mapping and encoding detection
  - GeoJSON URL with property remapping
  - OpenStreetMap via Overpass API — seventeen built-in templates
    (`streets`, `streets_with_speed`, `bike_network`,
    `dedicated_bike_network`, `transit_stops`, `schools`, `parking`,
    `trees`, `parks_and_green`, `water_bodies`, `sealed_surfaces`,
    `districts`, `kindergartens`, `hospitals`,
    `public_buildings`, `pedestrian_crossings`, `ev_chargers_osm`) plus a
    custom-query escape hatch
  - Static GTFS zip (transit stops, routes, coverage) — enriches stops with
    average headway, night service, and barrier-free status from the schedule
  - **GBFS shared mobility** — reads any operator's GBFS auto-discovery feed
    (bike share, e-scooters, mopeds, car sharing) and emits either available
    vehicles (free-floating, with form factor and propulsion) or stations
    (capacity, available vehicles, free docks, availability ratio). A
    planner's tool, not a rider app: pair with the map's heatmap mode to spot
    where shared vehicles cluster and where the pick-up gaps are. GBFS v2/v3.
    Optional **availability gap analysis over time** records snapshots (one
    click in the data hub, or on a schedule) and shows them as a **map overlay**
    colouring areas from "always available" to "usually empty", filterable by
    time window, hour of day, weekday and form factor — e.g. where do free cars
    run out on weekday mornings (see [docs/SHARED_MOBILITY.md](docs/SHARED_MOBILITY.md))
  - Accident CSV — Destatis Unfallatlas (Germany) and generic international,
    both with optional bounding-box clipping to the workspace
  - **BikeMaps.org** — global crowdsourced cycling collisions, near-misses,
    and hazards. Closes the well-documented under-reporting of vulnerable
    road users in police accident records (CC BY 4.0)
  - **CKAN open-data portal** — pulls resources from any CKAN-based portal
    (GovData.de, opendata.leipzig.de, daten.berlin.de, EU Open Data Portal,
    …) and delegates parsing to the GeoJSON or CSV connector by format
    preference
  - **OGC WFS service** — fetches a layer from any WFS endpoint (federal
    BKG WFS, state geoportals such as Geoportal Sachsen / NRW / Bayern,
    Umgebungslärm noise maps, …); auto-applies the workspace bbox
  - **Generic REST/JSON** — pulls a feature list out of any JSON endpoint
    (UBA Luftqualität, Sensor.Community, OpenChargeMap, BNetzA
    Ladesäulenregister, ADAC, municipal APIs) with configurable list path
    and geometry mapping
  - **Mobilithek (German NAP)** — gateway to the federal mobility-data
    access point (BMDV, successor to mCLOUD); dispatches to the matching
    parser based on a format hint. Supports both open distributions and
    subscriber mode with an X.509 client certificate (DATEX II realtime,
    restricted GTFS-RT). Built-in catalog browser (`browse_catalog()` /
    `python manage.py browse_mobilithek --keyword GTFS --formats`) parses
    the Mobilithek DCAT-AP feed so operators can discover dataset titles,
    publishers, and distribution URLs without manually searching the portal
  - **German federal presets** — one-URL onboarding for four key German
    open-data sources: Bundesnetzagentur EV charging register, UBA
    air-quality stations, DWD climate stations, and BASt traffic counts.
    Each preset encodes the source's column names, encoding, and
    geometry mapping so operators don't need to configure them manually
  - **Zensus 2022 population grid** — reads the Destatis 100 m grid-cell
    CSV (INSPIRE grid IDs in EPSG:3035), converts to WGS84 polygons, and
    emits demographic indicators per cell (population, under 18, 65+).
    Workspace-bbox-aware. Powers the equity-overlay rule that turns
    mobility measures into political arguments ("this serves 18 000
    residents, 22 % of whom are children")
- **KPI importers** — ``python manage.py import_kpis adfc|mid`` reads survey
  CSVs and writes results into workspace goals:
  - **ADFC Fahrradklimatest** — biennial cycling satisfaction grades (1–6)
    per city, matched to workspaces by name
  - **MiD 2017 modal-split** — walking, cycling, transit, and car share (%)
    per city/Kreis from the federal household travel survey
- **`seed_unfallatlas` command** — bootstraps a German workspace with real
  Destatis accident data clipped to the workspace bounds, replacing the
  illustrative demo layer
- **Rule-based measures engine** — generates prioritized interventions
  from available data
- **Transparent scoring** — nine dimensions, every value traceable to its source
- **Honest data provenance** — every layer is labelled **live source**,
  **official snapshot**, or **illustrative demo**, shown publicly on the
  dashboard ("Data basis"), the map layer list, and the methodology page, so
  visitors always know when a number is real versus an example
- **Public shareable URLs** for every measure
- **Methodology pages** — every formula and data source documented
- **New-workspace wizard** — add any city in three steps; search for the place
  by name and the bounding box is filled in for you (geocoded via OpenStreetMap)
- **Internationalization** — German and English out of the box, extensible
  to any language
- **Admin-token protection** for write actions
- **Modern, sober UI** — an emerald-accented design with the Inter typeface and
  the **OMOS** brand mark, kept professional for a public-sector audience. The
  web font is loaded from a privacy-friendly CDN with a system-font fallback, so
  offline self-hosted installs render correctly with no proprietary dependency.

## Using the Platform

OpenMobility OS has a public read layer (no login) and an admin layer protected
by `ADMIN_TOKEN`. In short, you can:

- **Explore** workspaces from the landing page, dashboards (KPIs, goals, top
  measures, and a "Data basis" provenance summary), and the **interactive map**
  with toggleable layers, accident view modes, one-click story views, district
  score choropleths, PNG export, and saved views.
- **Read measures** — a filterable list and a fully transparent detail page where
  every score exposes its inputs, formula, confidence, and data sources.
- **Administer** (with the admin token) — log in, add a workspace via the
  geocoding wizard, manage and sync data sources in the data hub, browse upstream
  catalogs, import Unfallatlas accident data, and generate rule-based measures.

📖 **The full step-by-step walkthrough lives in
[docs/USER_GUIDE.md](docs/USER_GUIDE.md)** — landing page, dashboard, map,
measures, and every admin task (workspaces, data hub, connectors, catalogs,
Unfallatlas, Mobilithek, Django admin, generating measures).

## Architecture

- **Backend:** Django 5 + GeoDjango + PostGIS + Django REST Framework
- **Frontend:** Django templates + Tailwind CSS + HTMX + Alpine.js + MapLibre GL JS
- **Database:** PostgreSQL 16 with PostGIS 3
- **Multi-tenancy:** path-based URLs (`/<workspace-slug>/...`)

See [CLAUDE.md](CLAUDE.md) for the full architecture overview, contribution
workflow, versioning policy, and code style.

## Production Deployment

For a production instance exposed to the internet: harden `.env`
(`DEBUG=False`, strong `SECRET_KEY`/`ADMIN_TOKEN`, `ALLOWED_HOSTS`), run behind
an Nginx or Caddy reverse proxy with TLS (the web container listens on 8000;
keep the `db` port private), persist the `postgres_data` volume with regular
`pg_dump` backups, and optionally point the map at self-hosted tile and Overpass
servers.

🚀 **The full step-by-step guide — including reverse-proxy snippets, backups,
and all map-tile / Overpass environment variables — lives in
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).** See
[`.env.example`](.env.example) for the complete environment-variable reference.

## Documentation

This README is the concise entry point. **Longer, detailed guides live as
separate Markdown files under [`docs/`](docs/)** — keep the README scannable and
move any in-depth content into a `docs/*.md` file with a short summary and link
back here.

- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — full walkthrough of every page and
  admin task (dashboard, map, measures, data hub, connectors, generating measures)
- [docs/SHARED_MOBILITY.md](docs/SHARED_MOBILITY.md) — connecting GBFS feeds
  (bikes/scooters/cars) and running availability gap analysis over time
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — production hosting: reverse proxy,
  TLS, backups, tile servers, environment variables
- [CLAUDE.md](CLAUDE.md) — project philosophy, architecture, contributor guide
- [CONTRIBUTING.md](CONTRIBUTING.md) — first-contribution guide
- [ROADMAP.md](ROADMAP.md) — development phases and upcoming features
- [CHANGELOG.md](CHANGELOG.md) — release notes
- [NOTICE](NOTICE) — third-party license attributions
- `/methodology/` (inside a running instance) — scoring methodology, data
  sources, connector reference
- `/about/` (inside a running instance) — self-hosting guide, version info

## Contributing

Contributions are welcome from anyone — municipalities, developers, data
journalists, planners, and researchers. Read [CONTRIBUTING.md](CONTRIBUTING.md)
for the quickstart and workflow, and [CLAUDE.md](CLAUDE.md) for project
principles.

## Roadmap

Near-term (post-MVP):

- Climate adaptation layer: trees, green areas, heat corridors, desealing
- Before/after map slider for measures
- Citizen feedback on measures
- GTFS-RT adapter for live transit delays (extends the Phase 9 static GTFS
  layers with realtime data)

See [ROADMAP.md](ROADMAP.md) for the full phase-by-phase breakdown.
