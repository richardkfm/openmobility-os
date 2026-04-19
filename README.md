```
  ███████╗███╗   ███╗ ██████╗ ███████╗
  ██╔════╝████╗ ████║██╔═══██╗██╔════╝
  ███████╗██╔████╔██║██║   ██║███████╗
  ╚════██║██║╚██╔╝██║██║   ██║╚════██║
  ███████║██║ ╚═╝ ██║╚██████╔╝███████║
  ╚══════╝╚═╝     ╚═╝ ╚═════╝ ╚══════╝
```

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

## Screenshots

| Platform landing | Workspace dashboard | Interactive map |
|---|---|---|
| _(coming soon)_ | _(coming soon)_ | _(coming soon)_ |

| Measures list | Measure detail | Data hub |
|---|---|---|
| _(coming soon)_ | _(coming soon)_ | _(coming soon)_ |

> Screenshots will be added once a public demo instance is running.
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

- Full GTFS static connector + `transit_routes` / `transit_coverage` layers
- Accident data layer with mode classification
  (pedestrian, cyclist, car, truck, bus, tram, motorbike, scooter)
- Climate adaptation layer: trees, green areas, heat corridors, desealing
- Before/after map slider for measures
- Citizen feedback on measures

See [ROADMAP.md](ROADMAP.md) for the full phase-by-phase breakdown.
