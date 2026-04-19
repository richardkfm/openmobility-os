# Changelog

All notable changes to OpenMobility OS will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
