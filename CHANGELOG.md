# Changelog

All notable changes to OpenMobility OS will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
