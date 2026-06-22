# Shared Mobility (GBFS) & Availability Gap Analysis

OpenMobility OS integrates shared-mobility fleets — bike share, e-scooters,
mopeds, car sharing — through **GBFS** (the [General Bikeshare Feed
Specification](https://gbfs.org/)), the open, vendor-neutral standard most
operators publish. This is a **planner's** tool, not a rider app: the goal is
to show where shared vehicles are actually available for pick-up and where the
persistent gaps are.

## 1. Adding a shared-mobility source

Any operator that publishes a GBFS auto-discovery feed works — anywhere in the
world, any vehicle type. There is nothing city- or vendor-specific in the
connector.

1. Find the operator's GBFS auto-discovery URL (`gbfs.json`). The
   [MobilityData systems catalog](https://github.com/MobilityData/gbfs/blob/master/systems.csv)
   lists known public feeds.
2. In the **Data hub → Add data source**, choose **GBFS shared mobility** and
   set:
   - `discovery_url` — the `gbfs.json` URL
   - `layer` — `shared_vehicles` (free-floating vehicles) or `shared_stations`
     (docking hubs)
   - `default_form_factor` *(optional)* — e.g. `bicycle`, for feeds that don't
     publish `vehicle_types`
3. Pick the matching **layer kind** (`shared_vehicles` / `shared_stations`)
   and sync.

GBFS **v2** and **v3** discovery layouts are both supported. The connector
joins `vehicle_types` (form factor, propulsion) and merges
`station_information` with live `station_status` automatically.

### Vehicle types: bikes, scooters, cars

Each vehicle carries a `form_factor` (`bicycle`, `cargo_bicycle`, `scooter`,
`moped`, `car`, `other`). The system displays **cars exactly like bikes** — no
code change is needed to show a car-sharing fleet. The only requirement is that
the operator publishes a GBFS feed. Some car-sharing operators expose GBFS
directly; others sit behind proprietary backends (e.g. Cantamen IXSI) and only
appear once they (or a regional aggregator such as MobiData / the national
Mobilithek) publish a feed.

> **Leipzig note:** nextbike (bikes) and Dott (e-scooters) publish public GBFS
> feeds for Leipzig and are ready to use. teilAuto/cityFlitzer (the local
> car-sharing fleet) does **not** currently publish a public GBFS feed for
> Leipzig — when one appears it is a one-line data-source addition.

## 2. Where are vehicles concentrated, where are the gaps?

A single sync is a real-time snapshot. On the map, switch a shared-mobility
layer to **Heatmap** mode to see, at that instant, where vehicles cluster and
where the holes are.

For station feeds, each station also carries an `availability_ratio`
(available ÷ capacity). A value near 0 marks a station that runs empty; a value
above 1 marks one that overflows — both are rebalancing candidates.

## 3. Temporal gap analysis (availability over time)

GBFS has no history, so to answer *"where is a bike or car usually available on
a weekday morning?"* OpenMobility OS records snapshots over time and aggregates
them.

### 3.1 Collecting snapshots

**From the UI (quick start):** open the data source in the **Data hub** and
click **Collect snapshot now**. The card shows how many snapshots are stored
and when the last one was taken. This is the fastest way to start a history and
try the overlay, but a single snapshot only captures one instant — gaps become
meaningful once you have many across different times of day.

**On a schedule (recommended for real signal).** A single snapshot is one
instant; meaningful gaps need many over time. Pick whichever fits your setup —
no external service is required either way.

The command itself is:

```bash
python manage.py collect_mobility_snapshots --prune-days 35
```

Options:

- `--workspace <slug>` — limit to one workspace (default: all)
- `--cell-size <metres>` — analysis grid resolution (default 400)
- `--prune-days <n>` — delete snapshots older than *n* days after collecting

Each run fetches every enabled `shared_vehicles` / `shared_stations` source,
bins the vehicles into a fixed spatial grid, and stores one compact snapshot
per source.

#### Option A — Docker Compose sidecar (easiest)

A ready-made, opt-in `snapshots` service ships in `docker-compose.yml`. It
reuses the web image and re-runs the collector on a loop. Plain
`docker compose up` is unchanged; start the collector alongside your stack with:

```bash
docker compose --profile snapshots up -d
```

Tune it in `.env` (see `.env.example`):

- `SNAPSHOT_INTERVAL_SECONDS` — how often to collect (default `900` = 15 min)
- `SNAPSHOT_PRUNE_DAYS` — history to keep (default `35`)

#### Option B — host cron

If you'd rather schedule it yourself, add a line to the host crontab
(`crontab -e`). For a Docker Compose deployment, call into the running web
container:

```cron
*/15 * * * * cd /path/to/openmobility-os && docker compose exec -T web python manage.py collect_mobility_snapshots --prune-days 35
```

For a non-Docker install, run `manage.py` from the `backend/` directory in your
virtualenv instead.

### 3.2 Viewing the gap overlay (map)

Once a source has snapshots, an **Availability gaps** toggle appears in the
map's layer panel. Switch it on to colour the city by how reliably vehicles are
available:

- **green** — a vehicle was almost always there (low gap)
- **red** — the area was usually empty (high gap; a candidate for more vehicles
  or rebalancing)

Use the dropdowns to focus the question:

- **time window** — last 24 h / 7 days / 4 weeks / 90 days
- **time of day** — any / morning peak / evening peak / night
- **day** — any / weekdays / weekend
- **vehicle type** — all / bicycles / scooters / cars / …

Hover any cell to see how often it ran empty, plus average and peak
availability. If multiple shared sources have history, pick which fleet to show.

### 3.3 Reading the gap grid (API)

```
GET /api/v1/workspaces/<slug>/shared-mobility-gaps/
```

Query parameters (all optional):

| Param          | Meaning                                                        |
|----------------|---------------------------------------------------------------|
| `source`       | DataSource id (defaults to the most recently sampled source)  |
| `days`         | look-back window in days (default 7, max 90)                   |
| `hours`        | hour-of-day filter, local time, e.g. `7-9` (morning peak)     |
| `weekdays`     | ISO weekday filter, 1=Mon … 7=Sun, e.g. `1-5` (weekdays)      |
| `form_factors` | comma list, e.g. `car` or `bicycle,scooter`                   |

The response is a GeoJSON `FeatureCollection` of grid cells. Each cell carries:

- `availability_rate` — fraction of snapshots in the window where the cell had
  at least one available vehicle
- `gap_rate` — `1 − availability_rate`; **the headline planner signal**. A high
  `gap_rate` means a place that is usually empty — a candidate for more
  vehicles or active rebalancing.
- `mean_count`, `max_count`, `samples`, `present_samples`

Example — *"where do free cars run out on weekday mornings, last 4 weeks?"*:

```
GET /api/v1/workspaces/leipzig/shared-mobility-gaps/?days=28&hours=7-9&weekdays=1-5&form_factors=car
```

Colour the cells by `gap_rate` to map persistent shortfalls.

> The grid only contains cells that held a vehicle at least once in the window,
> so it highlights *under-served* areas (usually empty) rather than areas with
> no service history at all.
