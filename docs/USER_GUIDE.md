# OpenMobility OS — User Guide

A walkthrough of the platform from a user's and an operator's perspective.
For setup, see the [Quickstart in the README](../README.md#quickstart); for
production hosting, see [docs/DEPLOYMENT.md](DEPLOYMENT.md).

## Contents

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

## Landing page

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
- **Data basis** — a summary of how many layers are live sources, official
  snapshots, or illustrative demo data, so visitors know at a glance how real
  the workspace's data is.
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
XYZ tile server you configure via `MAP_TILE_URL`). A **Base map** switcher on
the map lets you flip between Light, Dark, and Satellite imagery independently
of the UI theme, and a **legend** below the map always shows which colour and
marker means which active layer. A **full-screen** button (below the base-map
switcher) expands the map together with its on-map controls and the legend to
fill the whole screen — handy for presentations and council meetings; press it
again or hit Escape to return. Browsers without native full-screen support
(e.g. iPhone Safari) get the same mode via a built-in fallback.

**Layer panel (left sidebar):**

Toggle individual data layers on and off. Each layer that is not a live source
is flagged with a small badge (*snapshot* or *demo*) so placeholder data is
never shown silently. Available layer kinds include:

| Category | Layers |
|---|---|
| Infrastructure | Streets, streets with speed limits, bike network, dedicated bike lanes / paths, parking |
| Public transit | Transit stops (with headway / night / barrier-free enrichment), transit routes, transit coverage (300–500 m buffers) |
| Safety | Accidents |
| Community | Schools, districts |
| Environment / climate | Trees, green areas, parks, heat / fresh-air corridors, water bodies & retention, flood hazard zones, drought / heat-stress areas, sealed surfaces, air quality, land use |

Each layer is fetched as GeoJSON from `/api/v1/workspaces/<slug>/features/<layer_kind>/`
and cached for 30 seconds on the server.

**Accident view modes:**

When the Accidents layer is enabled, the filter panel offers three ways to read
the same data:

- **Circles** — one dot per accident, colour-coded by severity.
- **Heatmap** — a severity-weighted density surface for a quick overview. Tuned
  so isolated accidents stay faint and only genuine clusters build to red, which
  keeps hotspots legible when zoomed out.
- **Density lines** — streets coloured blue→red by a severity-weighted accident
  score (fatal×3 + serious×2 + minor×1), in the style of the German Unfallatlas.
  Instead of thousands of overlapping dots, whole streets light up by how
  dangerous they are. This view requires a synced streets layer; if none is
  present, the toggle is hidden and the panel explains how to add one.

The year, severity, and **involved-mode** filters apply to all three views — so
you can render, for example, a cyclist-only crash heatmap for the last three
years. The same filters drive the density aggregation,
so you can filter to *cyclist* accidents, see which streets glow red, then toggle
the **Dedicated bike lanes / paths** layer on top to spot corridors with high
cyclist-accident counts and no real cycling infrastructure. That layer renders
each segment by quality — *protected* (separated paths/tracks) vs *painted lane*
(on-street) — so you see not just whether infrastructure exists but whether it's
safe. Lanes built *after* the latest accident year (from OSM `start_date` /
`opening_date` tags, or a `year` / `start_date` / `opening_date` property on
imported data) are drawn with a white dashed overlay, so a flagged cluster sitting
under a dashed lane has likely already been addressed. (The looser **Bike network**
layer also exists, but it includes roads
where cycling is merely permitted, so it hides gaps rather than revealing them.)
The density lines are recomputed
server-side per filter combination via
`/api/v1/workspaces/<slug>/accident-density/` (cached for 5 minutes); click any
line to see its accident count, score breakdown, and per-mode totals.

**Story views (compound presets):**

One-click presets arrange several layers (and the right accident view mode) for a
recurring planning or journalism question, each accompanied by a plain-language
"reading the map" key. A view only appears when the workspace has the data it
needs:

- **Cycling gap analysis** — dedicated bike infrastructure (teal = protected,
  amber = painted lane), a cyclist-crash heatmap for the last three years (red
  where cycling crashes cluster), and cycling count stations shown together.
  Dense red areas with no teal or amber lane underneath are priority
  intervention zones.
- **Safe routes to school** — school locations against a nearby-crash heatmap
  and posted speed limits, so a school ringed by fast streets with crashes
  nearby stands out as a candidate for safe crossings and traffic calming.
- **Traffic safety overview** — a city-wide crash heatmap with speed
  limits and traffic-count points, highlighting the worst areas.
- **Urban heat & shade** — sealed (heat-trapping) surfaces and the heat /
  fresh-air corridor layer (heat islands in a warm colour, fresh-air corridors
  in a cool one) against the green cover and trees that offset them; a heavily
  sealed area with little green is a priority for depaving and greening.
- **Flood & water resilience** — water bodies and statutory flood-hazard zones
  (the Leipzig demo ships real Saxony LfULG flood zones) against the impervious,
  sealed ground where rain cannot soak away, surfacing where runoff concentrates.
- **Cooling green network** — parks, trees and fresh-air corridors against the
  population grid, showing which densely populated areas lack a cool refuge
  within easy reach.

The traffic story views show accidents as a heatmap; the year, severity, and
involved-mode filters still apply, so each preset reads as a clean density
surface over its supporting layers.

Each produces a publication-ready view for a planning meeting or a social-media
post in a single click. Activating a story view resets its layers to their
standard display look (so a custom per-layer display mode never undermines the
preset), and manually changing layers afterwards dismisses the "reading the
map" key — your changes are kept, the stale explanation is not.

**Measure Pipeline (status-coded measures):**

Toggle "Measures" in the layer panel to see all interventions colour-coded by
status — amber (proposed), blue (planned), orange (in progress), green (done),
slate (rejected). The filter panel below lets you narrow by status, category (15
types), and effort level. Clicking any marker shows title, status, effort, and a
link to the full measure detail page. This view tells the political story of a
city at a glance.

**District Score Board:**

When district boundaries are loaded, a "District scores" toggle appears in the
layer panel. It fills each district with a priority-score choropleth (light blue
= low → deep red = high). A dimension selector lets you isolate a single scoring
dimension (Climate, Safety, Social equity, or Quality of life) so planners can
see which neighborhoods need the most attention for each policy goal. Hover over
a district to see its aggregate score and measure count; the endpoint is
`/api/v1/workspaces/<slug>/district-scores/?dimension=<dim>`.

**Measures overlay:**

Toggle "Measures" to display auto-generated interventions as colour-coded point
or polygon markers on the map. Clicking a marker opens a summary popup with a
link to the full measure detail page, including its priority score.

**Save PNG:**

The "Save PNG" button (header, next to "Back to dashboard") downloads the
current map canvas as a PNG file named `<workspace>-map-<date>.png`. The
download captures whatever layers and zoom level are currently visible and
composites the on-screen legend (bottom-left) and the basemap attribution
(bottom-right) into the image, so the file is publication-ready for city
council slides or social-media posts without further editing.

**Saved views:**

The "Saved views" panel at the bottom of the sidebar saves and restores named
map states — zoom level, centre, and the full layer-visibility snapshot — to
`localStorage`. No login required. Useful for bookmarking the cycling-gap view,
a specific district, or any custom layer combination before sharing the URL or
exporting a screenshot.

---

### Measures list and detail

**List (`/<slug>/measures/`):**

All measures are shown in a filterable table. Measures generated by the rules
engine carry a "✨ Suggested by OMOS" badge to set them apart from hand-curated
entries, and the page header reminds reviewers that they are data-derived
suggestions to review rather than finished decisions. Use the filter bar to
narrow by:

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
   - **Find your place** — type a city, town, municipality, or region and the
     wizard geocodes it via OpenStreetMap (Nominatim), filling in the bounding
     box and country for you. No need to look up coordinates by hand; you can
     still adjust any field afterwards. The geocoder endpoint is configurable
     via `OSM_NOMINATIM_API`, so you can point it at your own Nominatim instance.
   - **Name** (required) and **Slug** (auto-derived from name, must be unique)
   - **Kind** — city, town, municipality, county, or state
   - **Country code** (ISO 3166-1 alpha-2, e.g. `DE`, `FR`, `US`)
   - **Language code** (BCP-47, e.g. `de`, `en`, `fr`)
   - **Timezone** (e.g. `Europe/Berlin`)
   - **Bounding box** — `minx`, `miny`, `maxx`, `maxy` in WGS 84, filled in by
     the place search above (or by hand). Used by the OSM connector to scope
     Overpass queries.
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
badge derived from the source's status, record count, and last-sync time,
plus a **provenance** badge (*live source* / *official snapshot* /
*illustrative demo*) so it is obvious which sources are real.

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
   | **OGC WFS** | `url`, `layer_name`; workspace bbox applied automatically (set `bbox_axis_order: yx` for EPSG:4326 servers that expect lat/lon, e.g. ArcGIS / state geoportals) |
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

Measures are **suggestions generated by OpenMobility OS**, not decisions: the
engine derives them from your synced data using transparent, rule-based scoring
you can inspect and override. **Generate** only re-runs that engine over data
already in the workspace — it never fetches anything from the internet itself.
To get suggestions from real data, add and sync a data source first.

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
