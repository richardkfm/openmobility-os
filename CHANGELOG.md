# Changelog

All notable changes to OpenMobility OS will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Measure Pipeline display mode** — toggling the Measures layer now colours
  every spatial intervention by its status (proposed = amber, planned = blue,
  in progress = orange, done = green, rejected = slate). A new filter panel
  below the layers card lets planners and journalists narrow by status,
  category (15 types), and effort level. Clicking any measure opens a rich
  popup with title, status badge, effort, summary, and a link to the detail
  page, including the computed priority score.
- **District Score Board** — when district boundaries are loaded a new
  "District scores" toggle fills each district with a priority-score
  choropleth (light blue → deep red). A dimension selector isolates a single
  scoring lens (Climate, Safety, Social equity, Quality of life). Hovering a
  district shows its aggregate score and measure count. Backed by a new
  API endpoint `/api/v1/workspaces/<slug>/district-scores/?dimension=<dim>`.
- **Cycling gap analysis preset** — a one-click "Story views" panel that
  activates the dedicated bike network, cyclist-accident density lines, and
  cycling count stations together. Red streets without any teal or amber bike
  infrastructure overlay are visually identified as priority intervention zones.
  The accident filter auto-syncs to cyclist-density mode when the preset is
  activated; "Clear preset" restores the previous layer state.
- **Save PNG button** — downloads the current map canvas as
  `<workspace>-map-<date>.png` using `MapLibre.getCanvas().toDataURL()`.
  Works for all display modes and layer combinations; useful for city council
  slides and social-media posts.
- **Saved views** — a localStorage-backed sidebar panel that saves and restores
  named map states (zoom, centre, full layer-visibility snapshot). No login
  required. Multiple views per workspace.

### Added
- **Dedicated bike-infrastructure layer** — a new, stricter cycling data source
  (`OSM — Dedizierte Radinfrastruktur`) that returns *only* dedicated cycling
  infrastructure: separated cycleways/tracks, bicycle roads, and on-street
  painted bike lanes. Unlike the existing "Radnetz" layer it excludes ordinary
  roads tagged `cycleway=no`/`shared_lane` or where cycling is merely permitted,
  so it shows where safe bike infrastructure actually exists. On the map each
  feature is coloured by quality — **protected** (separated paths/tracks, teal)
  vs **painted lane** (on-street, amber) — with a legend explaining the
  difference. The cycling-gap analysis now prefers this layer, so streets with
  only sharrows (or nothing) correctly count as gaps.

### Changed
- **Unfallatlas moved out of the catalog browser** — it's a single
  nationwide dataset clipped to your workspace, not a searchable library,
  so the catalogue page was confusing (a "search" box that searched
  years, and an empty/Berlin-only "release"). Add it from the standard
  **Add data source** form now: paste a CSV/ZIP URL or upload a file. The
  catalogue browser is reserved for connectors with a genuinely
  searchable upstream (Mobilithek).
- **Unfallatlas now ships working nationwide download URLs** —
  `config/unfallatlas.yaml` is pre-filled with the NRW open-geodata
  mirror links (2020–2023), which host the full Germany files at stable
  paths and cover every municipality (incl. Leipzig/Sachsen). The
  previously-suggested MFDZ `body.zip` mirror turned out to be a partial
  (Berlin-only) copy and has been removed.

### Fixed
- **`seed_unfallatlas your-city --years 2023` works out of the box** —
  the shipped config now contains real, nationwide per-year URLs instead
  of empty placeholders.

### Added
- **"Density lines" accident map view** — a third way to read accident data,
  next to Circles and Heatmap. Streets are coloured blue→red by a
  severity-weighted accident score (fatal×3 + serious×2 + minor×1), in the
  style of the German Unfallatlas, so dangerous corridors stand out instead of
  drowning in overlapping dots. The year, severity, and involved-mode filters
  drive the aggregation: filter to cyclist accidents, see which streets glow
  red, then toggle the Bike network layer to find infrastructure gaps. Requires
  a synced streets layer; the panel explains how to add one when it's missing.
  Served by the new `/api/v1/workspaces/<slug>/accident-density/` endpoint.
- **Cycling infrastructure gap analysis** — a new measure rule flags streets
  that carry many cyclist accidents yet have no bike infrastructure nearby, and
  draws the affected streets on the map's Measures layer with a transparent
  score breakdown.
- **`seed_demo` now loads enough data to use these features out of the box** —
  it auto-syncs the demo street and bike-network layers (use `--no-network` to
  skip for an offline boot).
- **Unfallatlas catalog ships a one-click default release** — the
  catalog browser now offers the MobilityData Foundation combined mirror
  (all years, a stable URL that doesn't rotate like the Destatis
  per-year links) as a ready-to-add entry. "Browse catalog →
  Unfallatlas" is no longer an empty dead end: click *Add to workspace*
  and it syncs, auto-clipped to your workspace. Configured in
  `config/unfallatlas.yaml` under a new `catalog:` list, so operators
  can add their own curated releases too.

### Changed
- **Catalog pages now explain themselves per connector** — Unfallatlas
  shows an intro making clear it's a *nationwide* dataset clipped to the
  workspace (there is no per-city version to search for), and its
  misleading free-text "search the catalog" box is hidden in favour of a
  short curated list. Connectors backed by a real keyword catalogue
  (Mobilithek) keep the search box via a new `catalog_searchable` flag.
- **Mobilithek catalogue-fetch failures are now actionable** — instead
  of a bare `Catalog fetch failed: 404`, the page explains the BMDV feed
  URL may have changed or need authentication, points to the feed-URL
  override field, and reminds you that pasting a distribution URL
  directly always works.

### Added
- **Upload a file directly in the catalog quick-add** — the
  Unfallatlas catalog page now offers an "…or upload a CSV / ZIP file"
  field alongside the URL box. Since Destatis publishes accident data
  through a JavaScript download portal with no stable per-city URL, you
  can now download the CSV/ZIP and drop it straight into the catalog
  form — it's stored, the config points at it, and an initial sync
  runs. Quick-add forms render an upload control for any connector that
  declares a `file`-type field.

### Changed
- **Friendlier Unfallatlas empty state** — when no preset years are
  configured, the catalog no longer shows the developer-facing "edit
  config/unfallatlas.yaml" note. It now points you to the "Add a custom
  entry" form and explains you can paste a URL or upload a downloaded
  file.

### Added
- **Data-hub Test panel is now a rich diagnostic view** — clicking
  *Test* on a data source no longer dumps raw JSON; it renders a panel
  showing which file was read from the ZIP, how many rows parsed, the
  CSV delimiter and encoding picked, the data's coordinate bounding
  box, the workspace bounding box, and the % of points inside. A
  MapLibre mini-map overlays the workspace polygon and a sample of the
  data so geographic mismatches are visible at a glance.

### Changed
- **ZIP archives now extract the *largest* matching member, not the
  first** — Destatis mirrors like `body.zip` from mfdz.de ship a small
  `metadata.csv` next to the multi-million-row `body.csv`, so the
  previous "first member in archive order" rule silently picked the
  wrong file and produced apparent ~2k-row imports of the metadata.
  The new picker uses uncompressed size as the tiebreaker. The Test
  panel surfaces the picked filename so operators can verify.
- **Unfallatlas falls back to unclipped import when workspace bounds
  drop every row** — previously, a workspace bbox mismatch caused a
  silent 0-row sync. The connector now imports the full dataset and
  attaches a warning (visible on the source detail page) so operators
  see the data immediately and know to adjust their bounds.

### Added
- **Unfallatlas connector accepts mirrored layouts** — the Mobility Data
  Foundation mirror at data.mfdz.de re-publishes Destatis accident files
  as comma-delimited CSV with renamed columns (`LON`/`LAT` instead of
  `XGCSWGS84`/`YGCSWGS84`, `IstSonstig` instead of `IstSonstige`,
  `STRZUSTAND` instead of `USTRZUSTAND`). Both layouts now work
  out-of-the-box. Delimiter is auto-detected from the header (`,` vs
  `;`); an explicit `delimiter` field is available in the connector
  config for edge cases.

### Fixed
- **Literal `{# connectors_json is injected via a` text leaking on the
  Add-source page** — Django's `{# … #}` is single-line only, so two
  multi-line comments (one in `data_source_add.html`, one in
  `about.html`) were rendering as literal text. Replaced with
  `{% comment %}{% endcomment %}`.
- **Add-source form lost everything on JSON parse error** — submitting
  invalid JSON in the *Configuration* field used to flash a generic
  "Config must be valid JSON" toast and redirect away, discarding the
  operator's input. The form now re-renders with all fields preserved
  (name, connector, layer, license, attribution, source URL, and the
  raw config text) and the error message includes the parser line and
  column.

### Added
- **ZIP upload + URL support** — admins can now upload a ZIP archive (or
  point a URL at one) in the CSV, Unfallatlas, and GeoJSON connectors.
  The first matching file inside the archive is auto-extracted — handles
  Destatis-style nested layouts like `UnfaelleMitPersonenschaden_2024/
  CSV/Unfaelle_2024.csv` without manual unpacking. The accept-attribute
  on the upload widgets is extended accordingly.

### Added
- **Catalog quick-add** — both Mobilithek and Unfallatlas now expose an
  inline "Add a custom entry" form on their catalog page so admins can
  enter a year + URL (Unfallatlas) or name + distribution URL + format
  (Mobilithek) directly from the UI. Removes the previous requirement to
  pre-seed `config/unfallatlas.yaml` before any year shows up; the YAML
  still works as the curated default catalog when present.
- **Configurable Mobilithek catalog URL** — BMDV occasionally rotates the
  DCAT-AP feed URL, which previously broke discovery with no UI recourse.
  Admins can now override the URL inline on the Mobilithek catalog page;
  the override is remembered per workspace. A new
  `MOBILITHEK_CATALOG_URL` env var provides a deployment-wide default.

### Added
- **Data hub catalog browser** — admins can now browse and add
  Mobilithek (German NAP) datasets and Unfallatlas (Destatis) yearly
  accident files end-to-end from the Data hub UI. A new "Browse catalog"
  page (`/<workspace>/data/catalog/`) lists every connector that exposes
  an upstream catalog, with search, format filters, and one-click "Add to
  workspace" that materialises a DataSource and runs the initial sync.
  Replaces the previous CLI-only workflow (`browse_mobilithek`,
  `seed_unfallatlas`) for routine additions; the management commands
  remain available for scripting.
- **Database-readiness signals on the Data hub** — the workspace transit
  and accident KPI cards (with the existing traffic-light sufficiency
  rating) now also render at the top of the Data hub so admins can judge
  coverage without leaving the page. Each source row gains a "Ready /
  Thin / Stale / No data / Error" badge derived from its status, record
  count, and last-sync timestamp.

### Changed
- **Connector interface gains optional `discover()`** — `BaseConnector`
  now defines `supports_discovery()` and `discover(query, facets,
  workspace) -> CatalogPage` as opt-in methods, allowing connectors
  with an upstream catalog to drive a UI without bespoke wiring. CSV,
  GeoJSON, and Overpass connectors are unchanged (they continue to use
  the plain "Add source" form).

### Fixed
- **Map container simplified** — removed the `{# ... #}` Django template comment
  (it was appearing as literal text in the browser, indicating a Docker layer
  cache issue where old templates were served alongside a new VERSION file) and
  collapsed the two-div structure (`#map-wrapper` + `#map`) into a single
  `<div id="map">`. The `overflow-hidden` on the wrapper that was collapsing the
  MapLibre canvas in earlier attempts is gone. `#map` is now the direct flex
  child and the MapLibre container.

### Changed
- **README: data hub documentation expanded** — the "Admin: data hub" section
  now covers all 17 connectors in a reference table, with dedicated step-by-step
  guides for adding Unfallatlas accident data (file upload and remote URL paths)
  and for using the Mobilithek catalog browser CLI. Added a new "Django admin
  (alternative)" section documenting `/django-admin/` as a second management
  interface. Version badge updated to current release.

### Fixed
- **Map canvas renders reliably (JS height)** — CSS `calc(100vh - 220px)` in a
  `<style>` block was still not guaranteeing a non-zero `clientHeight` for the
  MapLibre container on the live deployment. The height is now set via a
  JavaScript inline style (`element.style.height`) immediately before
  `new maplibregl.Map(...)` initializes, which has the highest possible CSS
  priority and is evaluated at script-execution time when the DOM is fully
  ready. A `window.resize` handler keeps the map sized correctly after
  viewport changes.

### Fixed
- **Map canvas reliably renders** — the previous fix moved the height to
  `#map-wrapper` and used `height: 100%` on `#map`, but `height: 100%` silently
  resolves to zero when no ancestor in the flex chain has a concrete pixel/
  viewport height. The height rule is now placed directly on `#map` itself
  (`calc(100vh - 220px); min-height: 480px`) so MapLibre always reads a
  non-zero `clientHeight` at initialisation time, regardless of the surrounding
  flex layout.

### Added
- **Django admin: full DataSource management** — the `/django-admin/` interface
  now provides complete connector management without leaving the admin:
  - Inline `is_enabled` checkbox in the list view (`list_editable`) for
    quick activation/deactivation without opening the change form
  - Bulk actions: "Enable selected", "Disable selected", "Sync now"
  - Custom change form with a file-upload field that auto-injects the stored
    path into `config["url"]` so CSV/GeoJSON/Unfallatlas connectors pick it up
  - "Connector schema hint" read-only panel on the change page shows the
    connector description and a table of all expected config keys/types
  - `NormalizedFeatureSet` inline with feature preview (first 3 features as
    pretty-printed JSON) for quick sanity-checking without API calls
  - `NormalizedFeatureSet` list is read-only (auto-generated, must not be
    hand-edited)

### Fixed
- **Map not rendering (blank canvas)** — the `#map` div was inside an
  `overflow-hidden` flex container that had no explicit height. At certain
  viewport sizes the container height collapsed to zero, clipping the
  MapLibre canvas away. Fixed by moving the explicit height to a
  `#map-wrapper` div and letting `#map` fill 100% of it.
- **Add data source form broken (Alpine.js silent failure)** — the
  `connectors_json` payload was rendered with `{{ connectors_json }}` directly
  inside an HTML double-quoted `x-data` attribute. The JSON's own double-quote
  characters terminated the attribute early, leaving Alpine.js unable to parse
  its component definition. Fixed by injecting the JSON into a
  `<script>window._CONNECTOR_REGISTRY = …</script>` tag and referencing
  `window._CONNECTOR_REGISTRY` from the `x-data` attribute instead.


- **Data hub: activate / deactivate data sources** — admins can now toggle any
  data source on or off via the "Enable / Disable" buttons in the data hub list
  and on the source detail page. Disabled sources are hidden from the map and
  excluded from layer queries without being deleted. Visual badge clearly marks
  disabled sources in the list with reduced opacity.
- **Data hub: direct file upload for CSV, GeoJSON and Unfallatlas connectors**
  — operators can now upload a local file (`.csv`, `.geojson`, `.json`) directly
  from the browser instead of providing a remote URL. The uploaded file is stored
  in `MEDIA_ROOT` and its path is auto-injected into the connector config. Files
  are served via Django at `/media/` (suitable for self-hosted Docker Compose;
  replace with nginx/Caddy proxy in high-traffic deployments).
- **Data hub: connector description and config-schema panel** — when adding a
  data source, selecting a connector type now shows its description and a table
  of all configuration fields (key, type, required, label) so operators no
  longer need to consult external docs to fill in the JSON config. The same
  schema table appears on the source detail page.
- **Connectors: local-file support for CSV, GeoJSON and Unfallatlas** — all
  three connectors now transparently handle local filesystem paths in `config.url`
  (absolute Unix paths or `file://` URIs). The new `_http.fetch_bytes` helper
  abstracts HTTP vs. local-file reads so adding local-file support to future
  connectors is a one-liner.

### Fixed
- **`/about` self-hosting terminal invisible** — the `components.css` `.prose
  pre` rule overrode the dark terminal block background with `#f1f5f9`, making
  the light-coloured text invisible (same background and foreground colour).
  Fixed by wrapping the terminal in `not-prose` and using inline styles that
  cannot be overridden by the cascade; the `.prose pre` rule is now scoped to
  `.measure-description` to avoid future collisions.
- **`/<workspace>/methodology` 500 error** — the template used a `|split`
  filter that does not exist in the custom template-tag library, causing
  `TemplateSyntaxError` on every page load. The broken (and empty) for-loop
  has been removed; the weights table was already rendered correctly by the
  lines below it.
- **Map default state: all layers now start unchecked** — previously every
  layer checkbox was `checked` on load, flooding the map with all data at once.
  Layers now start hidden; users opt in by ticking the checkboxes they need.

### Changed
- **Utrecht (Netherlands) demo workspace** — second real-city demo showing
  international use of the platform. Configured with OSM layers, Dutch
  national GTFS via OVapi (commented, ready to enable), BikeMaps.org,
  illustrative accident data, six Utrecht-specific mobility goals
  (Fietsvisie, Autoluwe Binnenstad, SPV Vision Zero, Fietsersbond score),
  and five pre-scored measures covering car-free zone expansion, cycling
  corridors, fietsstraten school zones, tram frequency, and P+R expansion.
  Demonstrates that the platform works outside Germany without code changes
- **Accident data sufficiency indicator** on the workspace dashboard — compares
  accident record count against a population-derived expectation (~3 per 1,000
  residents/year) and rates the dataset as "Good", "Thin", or "Placeholder".
  Shows severity breakdown, year range, expected volume, and coverage
  percentage. Surfaced on the dashboard and the public API
  (`/api/v1/workspaces/<slug>/` → `accident_kpis`)

### Fixed
- Export view (`/<slug>/admin/export/`) crashed with `AttributeError` for all
  export formats — measures export referenced non-existent model fields
  (`name_de`, `benefit`, `cost_eur`, `co2_avoided_tons`, `measure_scores`);
  goals export referenced `name_de`/`name_en` instead of `title_de`/`title_en`
  and used wrong related manager `workspace_goals` instead of `goals`
- `@admin_required` decorator now works on class-based view methods — previously
  it received `self` instead of `request` when applied to CBV methods, bypassing
  the admin token check on the health dashboard, comparison, and export views
- Health dashboard "Sync now" button raised `NoReverseMatch` due to incorrect
  URL name `sync_data_source` (correct name: `data_source_sync`)
- Health dashboard "Passing" percentage displayed the sum of active + error
  counts instead of a real percentage
- Workspace comparison view always showed 0 goals because it looked up the
  non-existent `workspace_goals` related manager instead of `goals`
- Workspace comparison view did not pass `layer_choices` to the template,
  causing layer kind labels to render as empty strings
- Map popup XSS vulnerability — GeoJSON property keys and values were injected
  as raw HTML; now escaped via `textContent`
- Hardcoded Leipzig coordinates (12.37, 51.34) used as map fallback center;
  replaced with neutral (0, 0) to avoid city-specific defaults per project
  principles
- Map measures GeoJSON endpoint hardcoded `title_de` instead of using
  language-aware `title_localized()`
- N+1 query on dashboard and measures list — each measure triggered a separate
  DB query for its scores; now uses `prefetch_related("scores")`
- Accident CSV, Unfallatlas, and BikeMaps connectors did not pass
  `request_kwargs(config)` to HTTP requests, preventing mutual-TLS client
  certificate authentication

### Changed
- README now includes a clickable table of contents with links to all
  major sections and sub-sections

### Added
- **Extended admin dashboard** — workspace operators now have visibility into:
  - **Workspace health dashboard** (`/<slug>/admin/health/`) — data source
    status cards, sync audit log, data freshness indicators, and sync
    actions. Enables operators to diagnose sync failures and track when
    data was last updated
  - **Workspace comparison view** (`/workspaces/admin/compare/`) — side-by-side
    configuration comparison across workspaces for planning purposes
  - **Export functionality** (`/<slug>/admin/export/`) — measures, data
    sources, and goals export as CSV, JSON, or PDF (basic table layout)
    for stakeholder reports and external analysis
- **Connector audit log** — every data source sync is now logged with
  timestamp, status (success/error), duration, record count, and error
  message (if any). Enables operators to diagnose sync failures and track
  data freshness
- **ADFC Fahrradklimatest KPI importer** — parses the biennial ADFC
  cycling-satisfaction survey CSV (school grades 1–6 per city) into
  ``WorkspaceGoal.current_value`` entries. Handles German decimal commas,
  configurable column names, and optional sub-category grades (safety,
  comfort, etc.). Goal code: ``adfc_fahrradklima``
- **MiD 2017 modal-split KPI importer** — parses the federal household
  travel survey (Mobilität in Deutschland) CSV into four workspace goals
  per city: ``mid_walking_share``, ``mid_cycling_share``,
  ``mid_transit_share``, ``mid_car_share`` (all in %). Handles percentage
  symbols, configurable column names, and semicolon/comma delimiters
- **``import_kpis`` management command** — ``python manage.py import_kpis
  adfc|mid --file <csv> [--workspace <slug>] [--dry-run]`` reads an
  ADFC or MiD CSV, matches cities to workspaces by name (case-insensitive,
  accent-folded), and upserts the corresponding ``WorkspaceGoal`` records.
  Supports ``--col key=name`` overrides for non-standard CSV layouts
- Leipzig demo workspace now ships ADFC Fahrradklimatest (grade 3.8,
  target 3.0) and MiD 2017 modal-split goals (cycling 19 → 25 %, car
  43 → 30 %) as baseline KPIs on the dashboard

### Changed
- `CLAUDE.md` now codifies a binding **Per-Commit Update Rule**: every
  commit pushed to the repo must include a `CHANGELOG.md` entry, update
  `README.md` when user-visible behaviour changes, and bump `VERSION` per
  Semantic Versioning. Tightens the previously per-PR rule to per-commit
  so the changelog reflects history as it happens

### Added
- **Mobilithek catalog browser** — operators can now search the Mobilithek
  DCAT-AP metadata feed by keyword and discover dataset titles, publishers,
  and distribution URLs without manually hunting for them in the portal.
  New `connectors.mobilithek_catalog` module exposes `browse_catalog(keyword)`
  and `get_distribution_url(uid, format_preference)` for use from a Django shell
  or scripts. A new management command `python manage.py browse_mobilithek`
  provides a CLI interface with `--keyword`, `--limit`, `--formats`, and
  `--supported-only` flags. The parser handles both top-level `dcat:Dataset`
  elements and catalog-wrapped datasets, prefers German-language titles,
  and maps raw format labels / IANA media-type URIs to the
  `MobilithekConnector` `format_hint` values (`gtfs`, `geojson`, `json`,
  `csv`). Feeds with unsupported formats (DATEX II, NeTEx, GBFS) are still
  catalogued with a recognized hint so operators know what they are finding.
- **German federal data-source presets** — four thin connector wrappers
  that encode format-specific quirks (column names, encodings, JSON
  paths) of key German open-data APIs so operators only supply a URL:
  - **BNetzA Ladesäulenregister** (`bnetza_charging`) — every public EV
    charger in Germany (weekly CSV, DL-DE BY 2.0)
  - **UBA Luftqualität** (`uba_air`) — official air-quality monitoring
    stations (REST API, DL-DE BY 2.0, default URL pre-filled)
  - **DWD Klimastationen** (`dwd_climate`) — climate stations with
    temperature / heat-day indicators (CSV, free reuse)
  - **BASt Dauerzählstellen** (`bast_counts`) — automatic traffic count
    stations on federal roads (annual aggregate CSV, DL-DE BY 2.0)
- **Zensus 2022 population grid connector** (`zensus_grid`) — reads the
  Destatis Zensus 2022 100 m grid-cell CSV, converts INSPIRE grid IDs
  (EPSG:3035) to WGS84 polygons via `pyproj`, and emits a GeoJSON
  FeatureCollection with demographic indicators (population, under 18,
  65+) per cell. Workspace-bbox-aware: only cells overlapping the
  workspace are emitted. License: DL-DE BY 2.0
- **Population-equity-gap measure rule** — reads the `population_grid`
  layer and identifies 100 m cells where the share of children (<18) or
  elderly (65+) exceeds the workspace average by ≥50 %. Generates an
  "Equity-focused infrastructure investment" measure that quantifies
  how many residents live in high-vulnerability clusters, so every
  other measure can be argued with "this serves X residents, Y % of
  whom are vulnerable." Evidence object carries total population,
  cluster cell counts, and per-group population breakdowns

### Added (previous)
- **Mobilithek subscriber mode** — X.509 client certificates are now
  plumbed through the inner GTFS / CSV / GeoJSON parsers, so Mobilithek
  distributions that require a subscriber cert (e.g. DATEX II realtime,
  restricted GTFS-RT) can be fetched end-to-end. The Mobilithek connector
  copies the configured `cert_path` and `key_path` into the inner
  connector's config under the shared `client_cert_path` /
  `client_key_path` keys, which every HTTP-fetching connector now reads
  through the new `connectors._http.request_kwargs` helper. Open-mode
  feeds continue to work without sending a cert
- **Shared HTTP helper** (`connectors._http`) — single source of truth for
  optional client-cert plumbing. Available to any future connector that
  needs to talk to a mutual-TLS endpoint (state-level DATEX II,
  corporate-firewalled WFS, etc.)

### Removed
- The `NotImplementedError` previously raised by Mobilithek subscriber-mode
  `fetch()` is gone; calls now succeed when both `cert_path` and
  `key_path` are configured

### Added (previous Unreleased block)
- **Decision-support layer kinds** — seven new `DataSource.LayerKind`
  values (`ev_charging`, `traffic_counts`, `cycling_counts`, `noise`,
  `public_buildings`, `population_grid`, `demographics`) so connectors
  and the map can carry the data needed to argue for measures, not just
  to draw the existing transport layers
- **OSM template extensions** — five new Overpass templates wired into
  the OSM connector: `kindergartens`, `hospitals`, `public_buildings`
  (libraries / town halls / community centres / post offices / places of
  worship), `pedestrian_crossings`, and `ev_chargers_osm`. Each is
  workspace-bbox-aware out of the box
- **EV-charging-gap measure rule** — compares the number of public
  charging points in a workspace against the EU AFIR 2030 reference of
  ≈100 residents per charging point (with a 0.5-chargers-per-km² floor
  when population is unknown). Generates a transparent
  "Public EV charging buildout" measure with the gap quantified in the
  evidence object
- **`electrification` measure category** for EV / charging /
  decarbonisation rules
- Leipzig demo workspace ships five new OSM data sources (kindergartens,
  hospitals, public amenities, pedestrian crossings, EV chargers) and
  documents drop-in CKAN / REST / Mobilithek presets for Bundesnetzagentur,
  Umweltbundesamt, opendata.leipzig.de, and the DELFI nationwide GTFS feed

### Added (previous Unreleased block)
- **CKAN connector** — fetches resources from any CKAN-based open-data
  portal (GovData.de, opendata.leipzig.de, daten.berlin.de, the EU Open
  Data Portal, …). Resolves the best-matching distribution by format
  preference (GeoJSON → JSON → CSV → TSV) and delegates parsing to the
  existing GeoJSON or CSV connector
- **WFS connector** — fetches a layer from any OGC WFS service (federal
  BKG WFS, state geoportals such as Geoportal Sachsen / NRW / Bayern,
  Umgebungslärm noise maps, …) and returns GeoJSON. Automatically adds
  the workspace bounding box as a BBOX filter so requests stay small
- **Generic REST/JSON connector** — pulls a feature list out of any JSON
  endpoint (UBA Luftqualität, Sensor.Community, OpenChargeMap, BNetzA
  Ladesäulenregister, ADAC, municipal APIs). Config picks the dotted
  path to the list and the geometry mapping (lat+lon or embedded
  GeoJSON geometry)
- **Mobilithek connector** — gateway to the German National Access Point
  for mobility data (BMDV, successor to mCLOUD). Pass a Mobilithek
  distribution URL plus a format hint (`gtfs`, `geojson`, `json`, `csv`)
  and the connector dispatches to the matching parser. Open
  distributions work today; subscriber mode (X.509 client cert) is
  scaffolded and planned
- **BikeMaps.org connector** — pulls global crowdsourced cycling collisions,
  near-misses, and hazards from `bikemaps.org`, normalized to the standard
  accident schema. Reports are tagged with `incident_type` and
  `data_origin: crowdsourced` so the UI / scoring layer can clearly
  distinguish citizen-science data from authoritative police records.
  Addresses the well-documented under-reporting of vulnerable road users in
  official accident statistics. License: CC BY 4.0.
- **`seed_unfallatlas` management command** — bootstraps a German workspace
  with real Destatis Unfallatlas accident data clipped to the workspace
  bounding box, replacing the illustrative demo accident layer. Reads
  per-year download URLs from `config/unfallatlas.yaml` (or a per-workspace
  override at `config/unfallatlas/<slug>.yaml`), or accepts a
  `--url-pattern "https://…/{year}.csv"` for one-off imports
- Unfallatlas connector now supports a `bbox` config option and, when a
  workspace with bounds is supplied at sync time, automatically clips rows
  outside the workspace bounding box. Makes importing the national CSV
  feasible for a single municipality
- Leipzig demo workspace ships a BikeMaps.org data source by default
  (collisions and near-misses; hazards opt-in)

### Changed
- Leipzig demo: GTFS data sources now point at the gtfs.de nationwide local
  transit feed (`nv_free`, CC BY 4.0) instead of empty placeholder URLs, so
  the three transit layers (stops, routes, coverage) sync out of the box
  for the Leipzig demo. The same zip feeds all three layers — only the
  derived `layer` view differs

### Fixed
- Syncing a data source with an incomplete configuration (e.g. the GTFS
  example sources shipped with an empty `url`) used to surface the raw
  `requests.MissingSchema: Invalid URL ''` traceback. The sync runner now
  validates the connector config before fetching and stores a clear
  "Configuration incomplete: …" message instead

### Fixed (Map filtering pass)
- Layer toggles in the workspace map now actually take effect on first render:
  layers are added with the visibility implied by the sidebar checkbox state
  instead of always defaulting to "visible"
- Switching the accidents view between Circles and Heatmap no longer leaves the
  inactive sub-layer ghosted on; the layer-toggle checkbox and view-mode buttons
  now share state and restore the correct sub-layer when re-enabled
- The map's GeoJSON endpoint (`/api/v1/workspaces/<slug>/features/<layer>/`) now
  aggregates features across every data source publishing the same layer kind.
  Workspaces with multiple sources for one layer (e.g. one Unfallatlas source
  per year) used to return HTTP 500 with `MultipleObjectsReturned`
- Layer sidebar labels now use the translated `LayerKind` choices (e.g.
  "Streets with speed limits", "Districts / neighborhoods") instead of a
  string built from the slug, which previously read as e.g.
  "streets_with_speed" or "streets with speed"
- "Measures" overlay no longer renders before its checkbox is ticked

### Added (Map filtering pass)
- Accidents layer: per-year filter checkboxes in the accidents sidebar.
  Years are auto-discovered from the loaded data; only the most recent year
  is selected by default to keep the map readable. Older years can be toggled
  on individually
- `streets_with_speed` layer is now color-coded by speed limit
  (≤30 km/h green → 40–50 orange → 60–70 red → ≥80 dark red), so it is
  visually distinct from the generic streets layer
- New `districts` Overpass template plus relation-to-polygon assembly in the
  OSM connector — produces proper administrative-boundary polygons from
  `boundary=administrative` relations (admin_level 9 / 10). Falls back to a
  MultiLineString of outer ways when rings cannot be closed
- Both accident connectors (`UnfallatlasConnector`, `AccidentCSVConnector`)
  now emit a top-level `year` property on each feature so the year filter
  works without parsing the date string

### Changed
- Leipzig demo workspace: the accidents data source now spans 2021–2025
  (≈40 illustrative points), and the districts data source now uses the OSM
  connector instead of three hardcoded polygons. The static fallback YAML
  blocks are documented inline as commented examples for operators who need
  fully offline demo data

### Added (Phase 9 — Public Transit Network as a First-Class Layer)
- Full `GTFSConnector` (`gtfs`) — reads a static GTFS zip (stops, routes,
  trips, stop_times, calendar, shapes) and emits one of three normalized
  layers depending on the `layer` config field:
  - `transit_stops` — stops enriched with `wheelchair_boarding`
    (yes/no/unknown), `modes` (bus/tram/rail/subway/…), `daily_trips`,
    `avg_headway_min`, and `night_service` (any trip 22:00–05:00)
  - `transit_routes` — LineString per route, using `shapes.txt` when
    available and falling back to the stop sequence otherwise
  - `transit_coverage` — buffer polygons (default 400 m, configurable via
    `coverage_buffer_m`) around every active stop for catchment analysis
- Optional `agency_filter` and `route_type_filter` config fields restrict the
  output to a specific agency or to selected GTFS route types
- New layer kind `transit_coverage` added to `DataSource.LayerKind`
- New measure categories: `transit_frequency`, `transit_accessibility`,
  `transit_gap` (the existing coverage rule now files under `transit_gap`)
- Two new measure rules:
  - `rule_transit_frequency` — flags workspaces where ≥25 % of stops have an
    average daytime headway above 20 min
  - `rule_transit_accessibility` — flags workspaces where ≥20 % of rated stops
    are not wheelchair-accessible
- Workspace dashboard now shows a "Public transit" KPI strip when transit
  data is present: stop count, average headway (min), population coverage %
  (with absolute resident estimate), night-service share, and barrier-free
  share
- `/api/v1/workspaces/<slug>/` now returns a `transit_kpis` object with the
  same numbers, so dashboards consuming the API can re-render the strip
- Map: `transit_routes` rendered as blue lines, `transit_coverage` as
  translucent buffer polygons; both layers honour the existing layer toggle
### Fixed
- Demo accidents layer now visible on the Leipzig map out of the box:
  added 15 illustrative accident points (mix of severities and modes) to the
  Leipzig seed workspace, and `seed_demo` now auto-syncs `manual` data sources
  on first boot so districts and accidents appear on the map without a manual
  sync step

### Added (Phase 8 — Accidents as a First-Class Layer, complete)
### Fixed
- Workspace map view now sets `Referrer-Policy: strict-origin-when-cross-origin`
  on its response. Django's project-wide default of `same-origin` strips the
  `Referer` header from cross-origin tile requests, which the OpenStreetMap
  volunteer tile servers reject with an "access blocked" tile (per their
  [tile usage policy](https://operations.osmfoundation.org/policies/tiles/)).
  Sending the origin (no path or query) on cross-origin requests satisfies the
  check without leaking the workspace URL to the tile provider.
- Workspace map page now renders correctly under non-English locales (e.g. German).
  Map center coordinates and default zoom embedded in the inline `<script>` are now
  passed through Django's `unlocalize` filter, so floats like `12.3731` are no longer
  formatted as `12,3731` — which previously produced a JavaScript `SyntaxError`
  (`const CENTER_LON = 12,3731;`) and prevented MapLibre from initializing, leaving
  `/<workspace>/map/` blank.
- `OSMOverpassConnector` now sends a descriptive `User-Agent` header
  (`OpenMobilityOS/<version> (+<repo-url>)`) and an explicit `Accept: application/json`
  header when calling the Overpass API. The public Overpass endpoint rejects requests
  with the default `python-requests` User-Agent with `HTTP 406 Not Acceptable`,
  which broke all OSM dataset syncs.

### Added (Phase 8 — Accidents as a First-Class Layer)
- `UnfallatlasConnector` (`unfallat`) — reads German Destatis Unfallatlas CSV format
  (semicolon-delimited, UKATEGORIE severity key, XGCSWGS84/YGCSWGS84 coordinates) and
  normalizes to the standard accident schema
- `AccidentCSVConnector` (`accident_csv`) — generic international accident CSV importer
  with freely configurable column mapping for severity, involved modes, date, and coordinates
- Standard accident property schema enforced by both connectors:
  `severity` (fatal/serious/minor), `date`, `time_of_day`, `weather`, `involved_modes`,
  `vulnerable_road_user`, `speed_limit`, `intersection_type`
- Map: accident layer rendered with severity-coded circle markers
  (dark red = fatal, orange = serious, yellow = minor) using MapLibre GL JS paint expressions
- Map: accident filter panel — filter visible accidents by severity level and involved mode
  (cyclist, pedestrian, car, truck) without a page reload
- Extended `accident_hotspot` measure rule: weighted severity scoring (fatal×3, serious×2,
  minor×1); generates a second VRU-specific measure candidate when ≥3 accidents involve
  cyclists or pedestrians
- Map: heatmap density view for the accidents layer with severity-weighted intensity
  (fatal=1×, serious=0.67×, minor=0.33×) and a yellow→orange→dark-red colour ramp;
  toggled via a Circles/Heatmap segmented control in the accident filter panel

### Added
- Version badge in the public footer and on `/about/` now links directly to the matching GitHub release (`…/releases/tag/v<version>`); footer also gains a persistent "GitHub" link to the source repository
- Django admin screens now display the OpenMobility OS version below the branding, linked to the matching GitHub release, plus a "Source on GitHub" shortcut and the current deployment mode
- `PROJECT_REPO_URL` setting (overridable via `.env`) exposes the canonical source repository URL to templates and the public meta API
- `/api/v1/meta/` now returns `repo_url` and `release_url` so downstream dashboards can link back to the running version's source

### Changed
- Django admin: localized site title and header ("OpenMobility OS · Administration") replace the default "Django administration" chrome
- `README` quickstart: automatic `SECRET_KEY` and `ADMIN_TOKEN` generation via Python one-liner
- `README`: expanded step-by-step setup guide for novice users (Docker installation, each step explained)
- Extracted a shared `core.utils.get_active_workspace` helper; `datasets`, `workspaces`, `measures`, `maps`, and `api` views now use it instead of each app maintaining its own copy of the lookup
- Simplified the scoring strategy override logic into a single `STRATEGY_OVERRIDES` dict instead of an if/if/if chain
- Hardcoded GitHub URL removed from the `/about/` self-hosting snippet — it now interpolates `PROJECT_REPO_URL` so forks and mirrors render the correct clone command

### Fixed
- Stray `>>` characters after the global stylesheet `<link>` in the base template (visible as duplicate markup in some browsers)
- Workspace wizard form: labels now use `for=` bindings to their inputs, and static placeholder examples (`"DE"`, `"Europe/Berlin"`, bounding-box coordinates) are either translated or wrapped in `{% trans %}` so they stay city-agnostic in every locale
- Data source detail screen: action buttons (test, sync, delete) now carry `aria-label`s, explicit `type="submit"`/`"button"`, and visible focus rings; result + spinner regions use `role="status"` + `aria-live="polite"` for screen readers
- `README`: replaced ASCII header logo that rendered as "SMOS" with a correct "OMOS" wordmark
- Custom domains now work: `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are both configurable via `.env`, preventing `DisallowedHost` 400 errors when deployed behind a reverse proxy on a public domain
- Added `.dockerignore` so the host `.env` file is no longer baked into the Docker image; environment variables are now exclusively supplied at runtime via `env_file` in `docker-compose.yml`

### Added
- `ROADMAP.md` — public phased development plan covering Phases 0–11
- `CONTRIBUTING.md` — first-contribution guide with quickstart, PR checklist, and project structure overview
- `CODE_OF_CONDUCT.md` — Contributor Covenant v2.1
- `SECURITY.md` — responsible disclosure process and self-hosting hardening checklist
- `NOTICE` — third-party license attributions for all backend and frontend dependencies
- GitHub Actions CI workflow: Ruff lint, Django system check + test suite, Docker build check
- GitHub issue templates: bug report, feature request, new connector proposal
- GitHub pull request template referencing CLAUDE.md governance rules
- Production deployment guide in README (reverse proxy, TLS, backups, custom tile server, Overpass endpoint)
- Screenshots placeholder section in README

### Added (initial prototype)
- Initial project scaffold for OpenMobility OS — an open, free, self-hostable
  decision platform for municipal mobility transition.
- `CLAUDE.md` with binding contributor guidelines, project philosophy, and
  governance rules (versioning, changelog, README policies).
- `VERSION` file as the single source of truth for the current semantic
  version.
- Docker Compose setup with PostgreSQL 16 + PostGIS 3 and a Django web
  container. `docker compose up --build` brings up the full stack.
- `.env.example` covering database URL, admin token, deployment mode
  (`public-demo` / `single-city` / `multi-city`), map tile URL, and
  Overpass API endpoint.
- Django project skeleton with apps `workspaces`, `datasets`, `connectors`,
  `measures`, `goals`, `maps`, and `api`.
- Split settings (`base`, `development`, `production`) with GeoDjango,
  internationalization (German + English), and DRF configured.
- Tailwind CSS pipeline (pre-compiled, no runtime Node dependency).
- Workspace data model supporting arbitrary cities, municipalities, regions,
  and administrative units worldwide — path-based multi-tenancy via
  `/<workspace-slug>/` URLs.
- Platform landing page listing all workspaces with demo badges.
- Workspace dashboard with KPIs, goals, and top measures.
- Interactive MapLibre GL JS map view per workspace with configurable layers.
- GeoJSON feature API for consumption by the map frontend.
- Three fully implemented data connectors: CSV upload/URL, GeoJSON URL, and
  OSM Overpass with six built-in query templates.
- Stub connector interfaces for GTFS, CKAN, WFS, and generic REST.
- Data hub UI with per-workspace data source listing, test connection, and
  sync trigger (admin-token protected).
- Rule-based measures engine generating prioritized interventions from
  available datasets.
- Transparent scoring across nine dimensions (climate, safety, quality of
  life, social impact, feasibility, cost, visibility, political viability,
  goal alignment) with fully explained rationales and source links.
- Prioritization view with strategy presets (Quick Wins, Vision Zero,
  Maximum Climate Impact, Fair Citywide Distribution).
- Public shareable measure detail pages with evidence and score breakdown.
- Methodology pages (global + per-workspace) explaining every calculation.
- New workspace wizard for adding any city or municipality in three steps.
- Seed data for three demo workspaces: Leipzig (rich data), Musterstadt
  (small town, sparse data), and Muster-Landkreis (regional, empty profile).
- German and English locale files for all UI strings.
- Language switcher with path-based locale prefix (`/de/`, `/en/`).
- Admin-token middleware protecting write actions.
- README quickstart covering single-city, multi-city, and public-demo
  deployments.

[Unreleased]: https://github.com/richardkfm/openmobility-os/compare/v0.1.0...HEAD
