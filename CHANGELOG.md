# Changelog

All notable changes to OpenMobility OS will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
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
