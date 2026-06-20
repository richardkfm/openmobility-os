# OpenMobility OS — Production Deployment

For a production instance exposed to the internet, follow these steps after
the [Quickstart](../README.md#quickstart) works locally.

## 1. Harden `.env`

```bash
SECRET_KEY=<long-random-string>        # python -c "import secrets; print(secrets.token_hex(50))"
ADMIN_TOKEN=<long-random-string>
DEBUG=False
ALLOWED_HOSTS=yourdomain.example.com
DEPLOYMENT_MODE=single-city            # or multi-city / public-demo
DEFAULT_WORKSPACE_SLUG=your-city       # single-city mode only
```

## 2. Run behind a reverse proxy with TLS

Use **Nginx** or **Caddy** in front of the Gunicorn container.
The web container listens on port 8000. Example Caddy snippet:

```
yourdomain.example.com {
    reverse_proxy web:8000
}
```

Make sure the `db` service port is **not** exposed externally.

## 3. Persist data

The `docker-compose.yml` uses a named volume `postgres_data`. For
backups, mount a host directory or use `pg_dump` via a cron job:

```bash
docker compose exec db pg_dump -U openmobility openmobility > backup_$(date +%Y%m%d).sql
```

## 4. Use a custom map tile server (optional)

Set `MAP_TILE_URL` to any XYZ tile endpoint. For a fully self-hosted
setup, use [tileserver-gl](https://github.com/maptiler/tileserver-gl)
with a downloaded OpenMapTiles extract and set:

```
MAP_TILE_URL=http://tileserver:8080/styles/osm-bright/{z}/{x}/{y}.png
MAP_TILE_ATTRIBUTION=© OpenMapTiles © OpenStreetMap contributors
```

The **dark-mode basemap** is configured the same way via `MAP_TILE_URL_DARK`
and `MAP_TILE_ATTRIBUTION_DARK`. It defaults to CARTO's free, keyless OSM dark
tiles; point it at your own dark style (e.g. a tileserver-gl dark style) for a
fully self-hosted setup:

```
MAP_TILE_URL_DARK=http://tileserver:8080/styles/dark-matter/{z}/{x}/{y}.png
MAP_TILE_ATTRIBUTION_DARK=© OpenMapTiles © OpenStreetMap contributors
```

The **satellite basemap** offered by the map's Base map switcher is configured
the same way via `MAP_TILE_URL_SATELLITE` and `MAP_TILE_ATTRIBUTION_SATELLITE`.
It defaults to Esri's keyless World Imagery so it works out of the box; point it
at your own aerial WMTS/XYZ layer, or leave it blank to hide the satellite
option entirely (the open OSM light/dark basemaps remain the default):

```
MAP_TILE_URL_SATELLITE=https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}
MAP_TILE_ATTRIBUTION_SATELLITE=Imagery © Esri, Maxar, Earthstar Geographics
```

## 5. Use a custom Overpass endpoint (optional)

For offline or high-volume use, set `OSM_OVERPASS_API` to your own
[Overpass instance](https://overpass-api.de/no_frills.html).

## Environment variables reference

See [`.env.example`](../.env.example) for the complete list with descriptions.
