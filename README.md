<img width="1248" height="832" alt="OMOS_e1" src="https://github.com/user-attachments/assets/96b2105a-cbf2-4324-bbc0-2f86815f8ae6" />


# OpenMobility OS

**Version:** 0.23.0 (pre-release) — see [CHANGELOG.md](CHANGELOG.md)
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

Leipzig (Germany) and Utrecht (Netherlands) are the two real-city demo
workspaces — one developing its cycling infrastructure, the other a
world-leading cycling city. The platform is **city-agnostic** from day one.
Any city, small town, municipality, or region worldwide can be added
through open data, APIs, and configuration — regardless of country,
language, data source, or administrative structure.

## Table of Contents

- [Deployment Modes](#deployment-modes)
- [Screenshots](#screenshots)
- [Quickstart](#quickstart)
- [Core Features (MVP)](#core-features-mvp)
- [Using the Platform](#using-the-platform)
  - [Landing page](#landing-page)
  - [Workspace dashboard](#workspace-dashboard)
  - [Interactive map](#interactive-map)
  - [Measures list and detail](#measures-list-and-detail)
  - [Admin: logging in](#admin-logging-in)
  - [Admin: adding a workspace](#admin-adding-a-workspace)
  - [Admin: data hub and syncing data](#admin-data-hub-and-syncing-data)
  - [Browsing catalogs from the UI](#browsing-catalogs-from-the-ui)
  - [Adding Unfallatlas accident data](#adding-unfallatlas-accident-data)
  - [Mobilithek catalog browser](#mobilithek-catalog-browser)
  - [Django admin (alternative)](#django-admin-alternative)
  - [Admin: generating measures](#admin-generating-measures)
- [Architecture](#architecture)
- [Production Deployment](#production-deployment)
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
- **Data hub** — browser-based connector management:
  - Add, edit, sync, enable/disable, and delete data sources from the UI
  - Upload local CSV or GeoJSON files directly (no remote URL required)
  - Connector description and config-field reference shown inline when adding a source
  - Activate / deactivate toggle: disabled sources disappear from the map without being deleted
- **Data connectors** (fully implemented):
  - CSV (URL or direct file upload) with column mapping and encoding detection
  - GeoJSON URL with property remapping
  - OpenStreetMap via Overpass API — thirteen built-in templates
    (`streets`, `streets_with_speed`, `bike_network`, `transit_stops`,
    `schools`, `parking`, `trees`, `parks_and_green`, `districts`,
    `kindergartens`, `hospitals`, `public_buildings`,
    `pedestrian_crossings`, `ev_chargers_osm`) plus a custom-query
    escape hatch
  - Static GTFS zip (transit stops, routes, coverage) — enriches stops with
    average headway, night service, and barrier-free status from the schedule
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
- **Transit KPIs** — stop count, average headway, population coverage, night
  service share, barrier-free share (shown when transit data is synced).
- **Traffic safety KPIs** — accident record count, severity breakdown
  (fatal/serious/minor), year range, and a **data sufficiency indicator** that
  compares the actual record count against a population-derived expectation
  (~3 accidents per 1,000 residents/year). Rated "Good", "Thin", or
  "Placeholder" so operators know at a glance whether the dataset is thick
  enough for meaningful analysis.
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
| Infrastructure | Streets, streets with speed limits, bike network, dedicated bike lanes / paths, parking |
| Public transit | Transit stops (with headway / night / barrier-free enrichment), transit routes, transit coverage (300–500 m buffers) |
| Safety | Accidents |
| Community | Schools, districts |
| Environment | Trees, green areas, parks, heat corridors, water bodies, air quality, sealed surfaces, land use |

Each layer is fetched as GeoJSON from `/api/v1/workspaces/<slug>/features/<layer_kind>/`
and cached for 30 seconds on the server.

**Accident view modes:**

When the Accidents layer is enabled, the filter panel offers three ways to read
the same data:

- **Circles** — one dot per accident, colour-coded by severity.
- **Heatmap** — a severity-weighted density surface for a quick overview.
- **Density lines** — streets coloured blue→red by a severity-weighted accident
  score (fatal×3 + serious×2 + minor×1), in the style of the German Unfallatlas.
  Instead of thousands of overlapping dots, whole streets light up by how
  dangerous they are. This view requires a synced streets layer; if none is
  present, the toggle is hidden and the panel explains how to add one.

The year, severity, and **involved-mode** filters drive the density aggregation,
so you can filter to *cyclist* accidents, see which streets glow red, then toggle
the **Dedicated bike lanes / paths** layer on top to spot corridors with high
cyclist-accident counts and no real cycling infrastructure. That layer renders
each segment by quality — *protected* (separated paths/tracks) vs *painted lane*
(on-street) — so you see not just whether infrastructure exists but whether it's
safe. (The looser **Bike network** layer also exists, but it includes roads
where cycling is merely permitted, so it hides gaps rather than revealing them.)
The density lines are recomputed
server-side per filter combination via
`/api/v1/workspaces/<slug>/accident-density/` (cached for 5 minutes); click any
line to see its accident count, score breakdown, and per-mode totals.

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
An alternative full-featured management interface is available at
`/django-admin/datasets/datasource/` (see [Django admin](#django-admin-alternative) below).

**Database-readiness signals.** The top of the hub mirrors the dashboard's
transit and accident KPI cards (including the green/amber/red sufficiency
rating) so admins can judge coverage without leaving the page. Each row in
the source list also shows a *Ready / Thin / Stale / No data / Error*
badge derived from the source's status, record count, and last-sync time.

**Two ways to add a source:**

- **Browse catalog** (`/<slug>/data/catalog/`) — search a connector's
  upstream catalogue and add a dataset with one click. Used for
  connectors that expose a genuinely searchable library, such as
  Mobilithek's DCAT-AP feed. See [Browsing catalogs from the UI](#browsing-catalogs-from-the-ui).
- **Add source** — the generic form below for everything else, including
  Unfallatlas (one nationwide dataset, no per-city catalogue to browse):
  paste a CSV/ZIP URL or upload a file.

1. Click **Add data source**.
2. Choose the **connector type** (the form shows a description and the expected
   config fields for the selected connector):

   | Connector | What to provide |
   |---|---|
   | **CSV** | URL or upload a local file; delimiter, encoding, lat/lon column names |
   | **GeoJSON URL** | URL to any GeoJSON FeatureCollection; optional property remapping |
   | **OSM Overpass** | Pick a built-in template (streets, bike network, dedicated bike network, transit stops, schools, parking, trees, districts, …) or write a custom QL query; workspace bbox injected automatically |
   | **GTFS static** | URL to a GTFS zip; pick output layer (`transit_stops`, `transit_routes`, `transit_coverage`) |
   | **Unfallatlas (Destatis)** | URL to the Destatis CSV *or* upload the file directly — see [Adding Unfallatlas accident data](#adding-unfallatlas-accident-data) |
   | **Mobilithek (German NAP)** | `distribution_url`, `format_hint` (`gtfs`/`geojson`/`csv`/`json`), `mode` (`open`/`subscriber`) — see [Mobilithek catalog browser](#mobilithek-catalog-browser) |
   | **BikeMaps.org** | Workspace bbox is used automatically; no config required |
   | **CKAN portal** | `portal_url` + `resource_id` (or `package_id`); works with GovData, opendata.leipzig.de, daten.berlin.de, and any other CKAN instance |
   | **OGC WFS** | `url`, `type_name`; workspace bbox applied automatically |
   | **Generic REST/JSON** | `url`, `list_path` (dot-notation into the JSON), `lat_field`/`lon_field` |
   | **German federal presets** | `BNetzA EV charging`, `UBA air quality`, `DWD climate`, `BASt traffic` — no config; URL and column mapping are built in |
   | **Zensus 2022 grid** | `url` to the Destatis 100 m CSV; clips to workspace bbox |
   | **Manual** | For hand-entered KPI values; no network fetch |

3. Select the **layer kind** that best describes what this data represents
   (e.g. `bike_network`, `schools`, `accidents`).
4. Optionally upload a local CSV, GeoJSON, or ZIP file — the file is stored on
   disk and its path is auto-filled into `config["url"]` so the connector picks
   it up. ZIP archives are auto-extracted at sync time: the first matching
   `.csv` / `.geojson` member is read, including nested layouts like
   `UnfaelleMitPersonenschaden_2024/CSV/Unfaelle_2024.csv`.
5. Click **Add data source**.

**Enabling and disabling sources:**

Each row in the data hub list has an **Enable / Disable** toggle button. Disabled
sources are hidden from the map and excluded from measure scoring, but their data
is not deleted. Use this to temporarily hide a layer without losing the sync
history. The Django admin's list view has an inline checkbox for the same toggle.

**Testing a connection:**

On the data source detail page click **Test connection**. The platform fetches a
small preview from the source and reports the number of features found, any
errors, and a sample of the returned properties. No data is written to the
database during a test.

**Syncing:**

Click **Sync** to pull fresh data. The platform:

1. Calls the connector's `fetch()` method.
2. Writes the returned GeoJSON into a `NormalizedFeatureSet` record.
3. Updates the status badge: `active` (OK), `error` (see error message), or `pending` (in progress).

**Bulk sync from the command line:**

```bash
# Sync all sources for one workspace
docker compose exec web python manage.py sync_datasources your-city-slug

# Sync all workspaces
docker compose exec web python manage.py sync_datasources
```

> **Getting to a usable map.** `seed_demo` auto-syncs the manual demo data plus
> the OSM Overpass **streets**, **streets with speed limits**, and **bike
> network** sources, because the accident **Density lines** view and the cycling
> infrastructure gap analysis need a street network to snap onto. Run
> `seed_demo --no-network` to skip the Overpass calls for a fully offline boot
> (the Density lines toggle then stays hidden until you sync a streets layer).
> For a full demo of the cyclist-gap workflow, also import accident data
> (`seed_unfallatlas`) and generate measures (`generate_measures`).

---

### Browsing catalogs from the UI

`/<slug>/data/catalog/` lists the connectors backed by a genuinely
searchable upstream catalogue. Currently:

- **Mobilithek** — search the DCAT-AP feed by keyword, filter by format
  (GTFS / GeoJSON / CSV / JSON / DATEX II), and click *Add to workspace*
  on any supported entry. The platform builds the DataSource with the
  right `distribution_url` and `format_hint` and runs an initial sync.
  If BMDV rotates the feed URL, override it inline via the *Catalog URL*
  field at the top of the Mobilithek catalog page — it is remembered per
  workspace. A deployment-wide default lives in `MOBILITHEK_CATALOG_URL`.
  You can also use the **Add a custom entry** form to paste a single
  distribution URL directly.

Single-source datasets like **Unfallatlas** are *not* in the catalogue
browser — there is no per-city library to search; it is one nationwide
dataset clipped to your workspace. Add it from the standard **Add data
source** form (see [Adding Unfallatlas accident data](#adding-unfallatlas-accident-data)).

The matching `browse_mobilithek` and `seed_unfallatlas` management
commands still work for scripting and CI.

---

### Adding Unfallatlas accident data

The **Unfallatlas** connector reads Destatis accident CSVs (semicolon- or
comma-delimited; auto-detected). The file is **nationwide** — it covers every
German municipality, and the connector clips it to your workspace bounds on
sync. There is no per-city version to hunt for.

**Easiest — paste the nationwide URL:**

The authoritative annual files are mirrored at stable paths on the NRW
open-geodata portal (each file is the full Germany dataset):

```
https://www.opengeodata.nrw.de/produkte/transport_verkehr/unfallatlas/Unfallorte2023_EPSG25832_CSV.zip
```

1. Go to `/<slug>/data/add/`, choose connector **Unfallatlas**, layer kind **Accidents**.
2. Put the URL in the config: `{"url": "https://www.opengeodata.nrw.de/.../Unfallorte2023_EPSG25832_CSV.zip"}`
3. Click **Add data source**, then **Sync**. The ZIP is auto-extracted and clipped to your workspace.

These URLs are also pre-filled per year in `config/unfallatlas.yaml`, so the
CLI works without any setup:

```bash
docker compose exec web python manage.py seed_unfallatlas your-city-slug --years 2023
```

**Alternative — upload a file:** download a CSV/ZIP yourself (e.g. from
[unfallatlas.statistikportal.de](https://unfallatlas.statistikportal.de)) and
attach it via "Upload local file" on the Add-source form. ⚠️ Make sure it's a
*nationwide* or *your-state* export — some third-party mirrors ship only a
single region (e.g. Berlin), which won't contain your city.

The connector clips rows to the workspace bounding box by default
(`clip_to_workspace: true`). Set `"clip_to_workspace": false` to import all
rows. If a clip would drop every row, the sync imports unclipped and warns you,
so you never get a silent empty result.

**Bootstrapping via command line:**

```bash
docker compose exec web python manage.py seed_unfallatlas your-city-slug \
  --file /path/to/unfallatlas.csv
```

---

### Mobilithek catalog browser

The **Mobilithek** connector accesses Germany's National Access Point for mobility
data. To discover dataset titles, publishers, and distribution URLs without
manually searching the portal, use the built-in catalog browser:

```bash
# Search for datasets related to Leipzig
docker compose exec web python manage.py browse_mobilithek -k "Leipzig" --formats

# Show only directly parseable datasets (GTFS, GeoJSON, CSV, JSON)
docker compose exec web python manage.py browse_mobilithek -k "GTFS" --supported-only

# Browse everything (first 20 results)
docker compose exec web python manage.py browse_mobilithek
```

The output shows the dataset UID, title, publisher, tags, and the distribution
URL(s). Copy the distribution URL into a Mobilithek data source config:

```json
{
  "distribution_url": "https://mobilithek.info/offers/…",
  "format_hint": "gtfs",
  "mode": "open"
}
```

For subscriber-mode datasets (X.509 client certificate required), mount the cert
and key files into the container and add `cert_path` / `key_path` to the config.

---

### Django admin (alternative)

All data source management is also available at `/django-admin/` (requires the
same `ADMIN_TOKEN` as the workspace UI — log in with `admin` / `<ADMIN_TOKEN>`).

The Django admin offers:

- **List view** — all data sources across all workspaces, with an inline
  `is_enabled` checkbox, status badge, record count, and last-sync timestamp
- **Bulk actions** — *Enable selected*, *Disable selected*, *Sync now*
- **Change form** — upload or replace a source file; view the connector's
  config schema as a table; see the last sync's feature collection preview
- **Filter / search** — by workspace, status, connector type, layer kind

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
   - *Cycling infrastructure gaps* — streets that carry many cyclist accidents
     yet have no bike infrastructure nearby (the gap geometry is drawn on the
     map's Measures layer)
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
