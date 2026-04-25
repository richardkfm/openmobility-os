```
   ██████╗  ███╗   ███╗  ██████╗  ███████╗
  ██╔═══██╗ ████╗ ████║ ██╔═══██╗ ██╔════╝
  ██║   ██║ ██╔████╔██║ ██║   ██║ ███████╗
  ██║   ██║ ██║╚██╔╝██║ ██║   ██║ ╚════██║
  ╚██████╔╝ ██║ ╚═╝ ██║ ╚██████╔╝ ███████║
   ╚═════╝  ╚═╝     ╚═╝  ╚═════╝  ╚══════╝
```

# OpenMobility OS

**Version:** 0.3.0 (pre-release) — see [CHANGELOG.md](CHANGELOG.md)
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

Leipzig is the first demo workspace, but the platform is **city-agnostic**
from day one. Any city, small town, municipality, or region worldwide can
be added through open data, APIs, and configuration — regardless of
country, language, data source, or administrative structure.

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
| <img width="1293" height="890" alt="grafik" src="https://github.com/user-attachments/assets/7427c722-1633-4c8e-abac-444e78b84450" /> | <img width="1271" height="1033" alt="grafik" src="https://github.com/user-attachments/assets/ef2cebb8-5547-4748-953e-88e2e169dd58" /> | <img width="1289" height="1055" alt="grafik" src="https://github.com/user-attachments/assets/75a0b55f-17c7-4def-84d4-86f4cd26abb5" /> |


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
three demo workspaces: **Leipzig**, **Musterstadt**, and **Muster-Landkreis**.

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
   - You should see three demo workspaces immediately
   - To add a new workspace: click "New workspace" (requires ADMIN_TOKEN from `.env`)

7. **To stop**, press `Ctrl+C` in the terminal. Data persists in the
   `postgres_data` volume until you run `docker compose down -v`.

## Core Features (MVP)

- **Multi-workspace** — arbitrary number of cities per installation
- **Interactive maps** — MapLibre GL JS with configurable tile sources
- **Data connectors** (fully implemented):
  - CSV (upload or URL) with column mapping and encoding detection
  - GeoJSON URL with property remapping
  - OpenStreetMap via Overpass API (eight built-in templates + custom queries)
  - Static GTFS zip (transit stops, routes, coverage) — enriches stops with
    average headway, night service, and barrier-free status from the schedule
  - Accident CSV (Destatis Unfallatlas + generic international)
- **Planned connectors** (interface defined, implementation pending):
  CKAN, WFS, generic REST
- **Rule-based measures engine** — generates prioritized interventions
  from available data
- **Transparent scoring** — nine dimensions, every value traceable to its source
- **Public shareable URLs** for every measure
- **Methodology pages** — every formula and data source documented
- **New-workspace wizard** — add any city in three steps
- **Internationalization** — German and English out of the box, extensible
  to any language
- **Admin-token protection** for write actions

## Using the Platform

### Landing page

When you open the platform you land on the workspace list. Each card shows the
city name, kind (city / town / county / …), country, population, the number of
active data sources, and the number of generated measures. Click a card to open
that workspace.

**Deployment-mode variations:**

| Mode | Landing behaviour |
|---|---|
| `public-demo` | All workspaces listed; "New workspace" button visible to admins |
| `multi-city` | All workspaces listed |
| `single-city` | Redirects immediately to the workspace set in `DEFAULT_WORKSPACE_SLUG` |

At the bottom of the page you can reach `/methodology/` (scoring formulas and
connector reference) and `/about/` (self-hosting guide, current version).

---

### Workspace dashboard

Clicking a workspace takes you to its dashboard at `/<slug>/`. You will see:

- **KPI strip** — number of measures, goals, active data sources, and population.
- **Goals** — each policy goal shows its target value, current value, unit, and
  a progress bar. Goals are loaded from the workspace configuration (YAML seed
  or the Django admin).
- **Top measures** — the five highest-priority interventions, ranked by a
  weighted score across nine dimensions (climate, safety, quality of life,
  social equity, feasibility, cost, visibility, political viability, and goal
  alignment). Click any row to open the full measure detail.
- **Quick-access cards** — direct links to the interactive map, the full
  measures list, and the data hub.

---

### Interactive map

The map at `/<slug>/map/` uses MapLibre GL JS with OSM vector tiles (or any
XYZ tile server you configure via `MAP_TILE_URL`).

**Layer panel (left sidebar):**

Toggle individual data layers on and off. Available layer kinds include:

| Category | Layers |
|---|---|
| Infrastructure | Streets, streets with speed limits, bike network, parking |
| Public transit | Transit stops (with headway / night / barrier-free enrichment), transit routes, transit coverage (300–500 m buffers) |
| Safety | Accidents |
| Community | Schools, districts |
| Environment | Trees, green areas, parks, heat corridors, water bodies, air quality, sealed surfaces, land use |

Each layer is fetched as GeoJSON from `/api/v1/workspaces/<slug>/features/<layer_kind>/`
and cached for 30 seconds on the server.

**Measures overlay:**

Toggle "Show measures" to display auto-generated interventions as point or
polygon markers on the map. Clicking a marker opens the measure detail.

---

### Measures list and detail

**List (`/<slug>/measures/`):**

All generated and hand-curated measures are shown in a filterable table. Use
the filter bar to narrow by:

- **Strategy** — changes the weighting applied to the priority score:
  - *Default* — balanced weights
  - *Quick wins* — boosts feasibility and low cost
  - *Vision Zero* — triples safety weight
  - *Max climate* — triples climate weight
  - *Fair distribution* — emphasises social equity
- **Category** — e.g. bike infrastructure, transit, traffic calming
- **Effort level** — low / medium / high

Filters update the list in place via HTMX without a full page reload.

**Detail (`/<slug>/measures/<measure-slug>/`):**

Each measure page shows:

- Title, summary, full description (markdown)
- Category, effort level, current status
- **Scoring table** — all nine dimensions with raw value (0–1), display value
  (0–100), confidence level, rationale, and the data sources each score is
  derived from. Nothing is hidden; every number is traceable.
- The priority score formula: `Σ(display_value × weight) / Σ(weights)`, where
  weights come from the active strategy.
- A permanent URL suitable for sharing with stakeholders or the public.

---

### Admin: logging in

All write actions require the `ADMIN_TOKEN` from your `.env` file.

1. Visit `/workspaces/admin-login/` (or click "Admin login" in the nav).
2. Enter your `ADMIN_TOKEN`.
3. Click **Log in** — a session cookie is set and you are redirected back.

To log out, visit `/workspaces/admin-logout/`.

Alternatively, pass the token as a Bearer header for API calls:

```
Authorization: Bearer <your-ADMIN_TOKEN>
```

---

### Admin: adding a workspace

1. On the landing page, click **New workspace** (visible only when logged in as admin).
2. Fill in the wizard form:
   - **Name** (required) and **Slug** (auto-derived from name, must be unique)
   - **Kind** — city, town, municipality, county, or state
   - **Country code** (ISO 3166-1 alpha-2, e.g. `DE`, `FR`, `US`)
   - **Language code** (BCP-47, e.g. `de`, `en`, `fr`)
   - **Timezone** (e.g. `Europe/Berlin`)
   - **Bounding box** (optional) — `minx`, `miny`, `maxx`, `maxy` in WGS 84.
     Used by the OSM connector to scope Overpass queries.
   - Short descriptions in German and/or English (optional)
3. Click **Create workspace**. You are taken straight to the data hub to add
   your first data sources.

You can also create a workspace from the command line by adding a YAML file
under `config/workspaces/` and running:

```bash
docker compose exec web python manage.py seed_demo --only your-city-slug
```

---

### Admin: data hub and syncing data

The data hub at `/<slug>/data/` is the control centre for all data sources.

**Adding a data source:**

1. Click **Add data source**.
2. Choose the **connector type**:
   - **CSV** — provide a URL, delimiter, encoding, and the column names for
     latitude/longitude (or a WKT geometry column).
   - **GeoJSON URL** — provide a URL to any GeoJSON FeatureCollection.
     Optionally remap or filter properties.
   - **OSM Overpass** — pick one of eight built-in templates (streets,
     streets-with-speed, bike network, transit stops, schools, parking,
     trees, parks-and-green) or write a custom Overpass QL query. The
     workspace bounding box is injected automatically.
   - **GTFS static** — provide a URL to a GTFS zip and pick the output layer
     (`transit_stops`, `transit_routes`, or `transit_coverage`). Stops are
     enriched with average headway, night service flag, and barrier-free
     status; coverage emits configurable buffer polygons (default 400 m).
   - **Manual** — for hand-entered KPI values (no network fetch).
3. Select the **layer kind** that best describes what this data represents
   (e.g. `bike_network`, `schools`, `accidents`).
4. Click **Save**.

**Testing a connection:**

On the data source detail page click **Test connection**. The platform fetches a
small preview from the source and reports the number of features found, any
errors, and a sample of the returned properties. No data is written to the
database during a test.

**Syncing:**

Click **Sync** (or run `python manage.py sync_datasources <slug>` from the
command line) to pull fresh data. The platform:

1. Calls the connector's `fetch()` method.
2. Writes the returned GeoJSON into a `NormalizedFeatureSet` record linked to
   this data source.
3. Updates the status badge:
   - `active` — sync succeeded
   - `error` — sync failed; the error message is shown in red below the row
   - `pending` — sync is in progress

The status table shows record count and the timestamp of the last successful
sync for each source.

**Bulk sync from the command line:**

```bash
# Sync all sources for one workspace
docker compose exec web python manage.py sync_datasources your-city-slug

# Sync all workspaces
docker compose exec web python manage.py sync_datasources
```

---

### Admin: generating measures

Once at least one data source has been synced, click **Generate measures** on
the workspace dashboard (admin only). The rule engine:

1. Loads all `NormalizedFeatureSet` records for the workspace.
2. Runs each built-in rule against the data:
   - *Missing protected bike lane* — high-speed streets without adjacent bike
     infrastructure
   - *Transit coverage gap* — areas more than a set distance from any transit
     stop
   - *Accident cluster* — spatial hotspots with elevated accident frequency
   - *Unsafe school route* — schools lacking a safe pedestrian/cycle approach
3. Creates or updates `Measure` records, each with a full set of nine
   `MeasureScore` entries and the raw evidence used to calculate them.
4. Reports the number of measures generated, updated, and skipped.

From the command line:

```bash
docker compose exec web python manage.py generate_measures your-city-slug
```

---

## Architecture

- **Backend:** Django 5 + GeoDjango + PostGIS + Django REST Framework
- **Frontend:** Django templates + Tailwind CSS + HTMX + Alpine.js + MapLibre GL JS
- **Database:** PostgreSQL 16 with PostGIS 3
- **Multi-tenancy:** path-based URLs (`/<workspace-slug>/...`)

See [CLAUDE.md](CLAUDE.md) for the full architecture overview, contribution
workflow, versioning policy, and code style.

## Production Deployment

For a production instance exposed to the internet, follow these steps after
the quickstart works locally:

### 1. Harden `.env`

```bash
SECRET_KEY=<long-random-string>        # python -c "import secrets; print(secrets.token_hex(50))"
ADMIN_TOKEN=<long-random-string>
DEBUG=False
ALLOWED_HOSTS=yourdomain.example.com
DEPLOYMENT_MODE=single-city            # or multi-city / public-demo
DEFAULT_WORKSPACE_SLUG=your-city       # single-city mode only
```

### 2. Run behind a reverse proxy with TLS

Use **Nginx** or **Caddy** in front of the Gunicorn container.
The web container listens on port 8000. Example Caddy snippet:

```
yourdomain.example.com {
    reverse_proxy web:8000
}
```

Make sure the `db` service port is **not** exposed externally.

### 3. Persist data

The `docker-compose.yml` uses a named volume `postgres_data`. For
backups, mount a host directory or use `pg_dump` via a cron job:

```bash
docker compose exec db pg_dump -U openmobility openmobility > backup_$(date +%Y%m%d).sql
```

### 4. Use a custom map tile server (optional)

Set `MAP_TILE_URL` to any XYZ tile endpoint. For a fully self-hosted
setup, use [tileserver-gl](https://github.com/maptiler/tileserver-gl)
with a downloaded OpenMapTiles extract and set:

```
MAP_TILE_URL=http://tileserver:8080/styles/osm-bright/{z}/{x}/{y}.png
MAP_TILE_ATTRIBUTION=© OpenMapTiles © OpenStreetMap contributors
```

### 5. Use a custom Overpass endpoint (optional)

For offline or high-volume use, set `OSM_OVERPASS_API` to your own
[Overpass instance](https://overpass-api.de/no_frills.html).

### Environment variables reference

See `.env.example` for the complete list with descriptions.

---

## Documentation

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
