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

### Light and dark basemaps

Each of the light and dark basemaps is drawn either from raster tiles or from a
[MapLibre style](https://maplibre.org/maplibre-style-spec/) (vector tiles). The
operator picks one per mode in `.env`; visitors see a single Light and Dark
button either way.

| Setting | Values | Default |
|---|---|---|
| `MAP_LIGHT_STYLE` | `raster` (`MAP_TILE_URL`), `vector` (`MAP_VECTOR_STYLE_URL_LIGHT`) | `raster` |
| `MAP_DARK_STYLE` | `vector` (`MAP_VECTOR_STYLE_URL_DARK`), `filter` (`MAP_TILE_URL` darkened in the browser), `raster` (`MAP_TILE_URL_DARK`) | `vector` |

The vector styles default to [OpenFreeMap](https://openfreemap.org): free, no
API key, no registration, open source. Its styles are `positron` (the light
default), `liberty` and `bright` for light, and `dark` for dark:

```
MAP_LIGHT_STYLE=vector
MAP_VECTOR_STYLE_URL_LIGHT=https://tiles.openfreemap.org/styles/positron
MAP_DARK_STYLE=vector
MAP_VECTOR_STYLE_URL_DARK=https://tiles.openfreemap.org/styles/dark
```

For a fully self-hosted setup, run [OpenFreeMap](https://github.com/hyperknot/openfreemap)
yourself and point both URLs at it. A style's credit line comes from its own
tile sources, so there is no attribution setting for vector styles.

If a vector style can't be loaded (the service is down or blocked), the map
falls back to raster tiles: light shows `MAP_TILE_URL`, dark shows it through
the dark filter. The filter needs nothing beyond `MAP_TILE_URL`, so
`MAP_DARK_STYLE=filter` is the choice for an installation that must not call
any tile service except its own.

To use a dedicated dark raster tileset (e.g. a tileserver-gl dark style):

```
MAP_DARK_STYLE=raster
MAP_TILE_URL_DARK=http://tileserver:8080/styles/dark-matter/{z}/{x}/{y}.png
MAP_TILE_ATTRIBUTION_DARK=© OpenMapTiles © OpenStreetMap contributors
```

If `MAP_DARK_STYLE` is not set at all, an installation that sets
`MAP_TILE_URL_DARK` keeps using it and every other installation gets `vector`.
The keyless CARTO dark URL that earlier versions shipped is ignored, because
CARTO now answers it with "API key required" tiles.

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
