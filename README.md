# OpenMobility OS

**Version:** 0.1.0 (pre-release) — see [CHANGELOG.md](CHANGELOG.md)
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

## Quickstart

Requirements: Docker and Docker Compose.

```bash
git clone https://github.com/richardkfm/openmobility-os.git
cd openmobility-os
cp .env.example .env
# edit .env — at minimum set ADMIN_TOKEN and SECRET_KEY to random values
docker compose up --build
```

Open http://localhost:8000 — you should see the platform landing page with
three demo workspaces: **Leipzig**, **Musterstadt**, and **Muster-Landkreis**.

## Core Features (MVP)

- **Multi-workspace** — arbitrary number of cities per installation
- **Interactive maps** — MapLibre GL JS with configurable tile sources
- **Data connectors** (fully implemented):
  - CSV (upload or URL) with column mapping and encoding detection
  - GeoJSON URL with property remapping
  - OpenStreetMap via Overpass API (six built-in templates + custom queries)
- **Planned connectors** (interface defined, implementation pending):
  GTFS, CKAN, WFS, generic REST
- **Rule-based measures engine** — generates prioritized interventions
  from available data
- **Transparent scoring** — nine dimensions, every value traceable to its source
- **Public shareable URLs** for every measure
- **Methodology pages** — every formula and data source documented
- **New-workspace wizard** — add any city in three steps
- **Internationalization** — German and English out of the box, extensible
  to any language
- **Admin-token protection** for write actions

## Architecture

- **Backend:** Django 5 + GeoDjango + PostGIS + Django REST Framework
- **Frontend:** Django templates + Tailwind CSS + HTMX + Alpine.js + MapLibre GL JS
- **Database:** PostgreSQL 16 with PostGIS 3
- **Multi-tenancy:** path-based URLs (`/<workspace-slug>/...`)

See [CLAUDE.md](CLAUDE.md) for the full architecture overview, contribution
workflow, versioning policy, and code style.

## Documentation

- [CLAUDE.md](CLAUDE.md) — project philosophy, architecture, contributor guide
- [CHANGELOG.md](CHANGELOG.md) — release notes
- `/methodology/` (inside a running instance) — scoring methodology, data
  sources, connector reference
- `/about/` (inside a running instance) — self-hosting guide

## Contributing

Contributions are welcome from anyone — municipalities, developers, data
journalists, planners, and researchers. Please read [CLAUDE.md](CLAUDE.md)
first for project principles and the contribution workflow.

## Roadmap

Near-term (post-MVP):

- Full GTFS static connector + `transit_routes` / `transit_coverage` layers
- Full `UnfallatlasConnector` for accident data with mode classification
  (pedestrian, cyclist, car, truck, bus, tram, motorbike, scooter)
- Before/after map slider for measures
- Full user/role system (optional, for municipalities needing editorial workflows)
- GTFS-RT for live transit data
- Citizen feedback on measures

See [CHANGELOG.md](CHANGELOG.md) and the project plan for the full phase
breakdown.
