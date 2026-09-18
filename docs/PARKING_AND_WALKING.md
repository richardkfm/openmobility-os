# Parking vs walking

Two opposed readings of the same street, on one map. **Parked cars** fills the
kerbs and car parks of a city with one symbol per car, so the space given to
cars at rest can be counted instead of asserted. **Walking quality** colours
every street by what it is like on foot. The two halves are linked by a fact the
data already carries: a street whose walking score is dragged down by cars
parked *on the kerb* is the same street the parking layer has just filled.

Neither half is a routing tool and neither produces a ranking of cities. They
describe one municipality's own streets, from that municipality's own data, with
every number's method and source exposed.

---

## Contents

- [Turning it on](#turning-it-on)
- [What the parked-car layer claims](#what-the-parked-car-layer-claims)
- [What the walking score claims](#what-the-walking-score-claims)
- [The ten factors](#the-ten-factors)
- [The classes](#the-classes)
- [Coverage, confidence and silence](#coverage-confidence-and-silence)
- [Matching a pavement to its street](#matching-a-pavement-to-its-street)
- [Who gets the space](#who-gets-the-space)
- [Overriding the assumptions for your city](#overriding-the-assumptions-for-your-city)
- [API](#api)
- [Limits](#limits)

---

## Turning it on

Both layers are derived: they are computed from layers you have already synced,
so there is nothing extra to import and no migration to run.

1. In the workspace's **Data hub**, add OpenStreetMap sources using the
   templates `streets_with_speed`, `footways`, `pedestrian_crossings`,
   `street_parking` and `parking_lots`, and sync them. `footways` and
   `parking_lots` are heavy, which is why they are not synced automatically.
2. Open `/<workspace>/map/`.
3. Either tick **Parked cars (estimated)** and **Walking quality** in the layer
   panel, or activate the **Parking vs walking** story view, which brings both
   on together with the pedestrian layers underneath.

A street network alone is enough to draw parked cars. Walking quality needs a
street network plus at least one pedestrian layer; with no `footways` layer it
will honestly report most streets as *not enough data*, which is the argument
for syncing it rather than a fault.

---

## What the parked-car layer claims

Each symbol is one car space. **Solid** symbols are surveyed: OpenStreetMap
records parking there. **Dashed outlines** are modelled: nobody surveyed the
street, but a residential street usually has a kerb people park on, so the space
is filled with an assumption and counted separately. The panel and the legend
always state which is which, and the two are never added into one undifferentiated
total.

A street that was surveyed and found to have **no** parking is left empty. That
is evidence, and overwriting it with an assumption would be the worst thing this
layer could do.

It reports **capacity, not occupancy** — how many cars fit, not how many are
parked right now. Occupancy would be a second layer of fiction on top of the
first.

Zoomed out, twenty thousand overlapping symbols say nothing, so the estimate
falls back onto the geometry it came from: the kerb keeps its street, the car
park keeps its footprint, each drawn by how many cars it holds. Where a city has
more cars than can be drawn one by one, the server thins them deterministically
and every remaining symbol carries a `represents` count that the legend prints —
a thinned map that claimed one symbol per car would be a lie.

---

## What the walking score claims

Every street is rated on how it is to walk along: **comfortable**, **usable**,
**tight**, **hostile**, or **not enough data**. The rating comes from ten
factors in two components:

- **Safety** — how exposed a person on foot is to motor traffic.
- **Comfort** — whether the walk is pleasant, and possible at all.

The headline is a weighted mean of the two (60 % safety, 40 % comfort by
default). Behind the class is an auditable 0–100 score, which travels in the API
and is printed on the workspace's `/methodology/` page.

**The map never draws the number.** A score printed over a street implies a
precision that banded OpenStreetMap inputs cannot support, and on a network of
thousands of streets it is noise before it is information. Tick **Show numeric
scores** in the panel and the numbers appear in the popup — nowhere else.

The score describes a street's own qualities. It says nothing about where that
street leads, how far the nearest shop is, or whether a junction is survivable.

---

## The ten factors

Each factor returns a value between 0 and 1, the name of the formula it used,
the inputs it read, and its own confidence. Default weights within each
component:

| Component | Factor | Weight | Reads |
|---|---|---|---|
| Safety | `footway_separation` | 0.30 | `footway_present`, `sides`, `foot_scheme`, `highway=living_street/pedestrian` |
| Safety | `traffic_speed` | 0.30 | `maxspeed_kmh`, `maxspeed_source`, `maxspeed_zone` |
| Safety | `lane_count` | 0.15 | `lanes` |
| Safety | `crossings` | 0.15 | `pedestrian_crossings` snapped to the street, against a target spacing |
| Safety | `obstacles` | 0.10 | `obstacles` with `affects` of `walking` or `both`, matched by OSM way id |
| Comfort | `footway_width` | 0.35 | `width_m`, but only where `width_source` is `tagged` |
| Comfort | `kerb_parking` | 0.20 | `parking_type` — `on_kerb`, `half_on_kerb`, `lane`, `street_side` … |
| Comfort | `step_free` | 0.20 | `is_steps`, `incline_pct`, a matched crossing's `kerb` |
| Comfort | `surface` | 0.15 | `surface`, with `smoothness` overriding it where tagged |
| Comfort | `lit` | 0.10 | `lit` |

Two of these are worth spelling out.

**`traffic_speed` never invents a speed limit.** A tagged `50` or `30 mph` is
read as a survey. `maxspeed=none` scores zero, because an unrestricted road is
the worst case for a person on foot, not a gap in the data. An implicit zone
(`DE:urban`, `NZ:urban`, `GB:nsl`, …) is **not** resolved to a number: what
*urban* means is a question of national law, and a table of country defaults in
core code would wire the software to one country's legal system. The zone string
is kept, and your workspace supplies the local numbers if you want them.

**`footway_width` never estimates.** A carriageway can be inferred from a lane
count; a pavement cannot. Only a tagged width counts, and an untagged pavement
leaves the factor silent.

---

## The classes

Thresholds on the 0–100 headline, all overridable:

| Class | Score | Colour | What it means |
|---|---|---|---|
| Comfortable | ≥ 70 | dark green | A pavement, calm traffic, and a surface and width that work |
| Usable | ≥ 50 | lime | Walkable, with something clearly worse than it should be |
| Tight | ≥ 30 | amber | A walk that most people will find unpleasant or difficult |
| Hostile | < 30 | red | Exposed to fast traffic with little or no pedestrian space |
| Not enough data | — | pale grey | Too few of the ten factors are known to say anything |

*Not enough data* is a class, not an absence. Those streets are **drawn**, in
their own colour, with their own legend row. A map that quietly omitted them
would let a city nobody has surveyed pass for a city with nothing wrong, and the
survey gap is usually the most actionable thing the layer can show.

---

## Coverage, confidence and silence

The rule the whole score rests on: **a factor the data cannot speak to returns
nothing.** It is dropped from the weighted mean rather than substituted with a
neutral middling value, and it is named in that street's `unknowns` list, which
the popup reads out as *"not enough data on: footway width, lighting"*.
Substituting a middle value would silently turn *nobody has surveyed this* into
*it is average*.

**Coverage** is the share of the weight that was actually known. Below
`min_coverage` (0.5 by default) no class is given at all.

**Confidence** — high, medium or low — follows coverage, and is capped at medium
for a pavement matched by proximity. On the map it is drawn as **opacity**: a
class resting on thin data literally looks faint.

A layer that is not synced and a layer that is synced but holds nothing here are
different claims, and only the second may score a street. With no
`pedestrian_crossings` source the crossings factor stays silent; with one synced
that genuinely records no crossing on this street, the street is scored for
having none.

---

## Matching a pavement to its street

OpenStreetMap records pedestrian space two incompatible ways, and coverage
differs wildly by city, so both are read:

1. A `sidewalk` tag on the street itself, matched by OSM way id.
2. A footway mapped as its own line beside the street.

For the second, the join is **guided proximity**: the nearest standalone footway
within 25 m, but **only** where the street's own record says `sidewalk=separate`
— an explicit pointer to a pavement mapped elsewhere — or where the street
carries no pavement record at all.

A street surveyed as having **no** pavement is never rescued by a line that
happens to run nearby. Evidence outranks proximity.

A match made by nearness is flagged `footway_match: "proximity"`, capped at
medium confidence, and stated in the popup, because a pavement 20 m away may
belong to the parallel street.

A footway mapped as its own way counts as **one** pavement, not two. The
connector records such a way as walkable end to end, which says nothing about
the other kerb — crediting the street with two pavements would invent one.

---

## Who gets the space

The second display mode, **Who gets the space**, colours each street by how its
width divides between parked cars and people on foot:

```
space_balance = (footway width − parking width) / (footway width + parking width)
```

−1 is all cars (purple, the same purple the parked-car layer uses), +1 is all
pedestrian space (green), 0 is an even split. It is a diverging scale because
"who gets the space?" has a meaningful midpoint.

Both widths have to be real. The pedestrian side comes from tagged footway
widths only, and the parking side from the bay geometry in the space budget. A
street missing either is drawn grey rather than assumed balanced, and the panel
states what share of the network that leaves — which, in most cities today, is
the majority.

---

## Overriding the assumptions for your city

Every weight, threshold and distance is a parameter under
`Workspace.settings["walkability"]`, merged over the defaults one key at a time,
and every one of them is printed on `/<workspace>/methodology/` with a badge
saying whether it is still the shipped default or your local value.

```jsonc
{
  "walkability": {
    // Raise one weight without restating the other four.
    "weights_safety": {
      "footway_separation": 0.35, "traffic_speed": 0.30,
      "lane_count": 0.15, "crossings": 0.15, "obstacles": 0.05
    },
    "headline_weights": { "safety": 0.6, "comfort": 0.4 },
    "class_thresholds": { "comfortable": 70, "usable": 50, "tight": 30 },
    "min_coverage": 0.5,
    "comfortable_width_m": 2.5,
    "minimum_width_m": 1.5,
    "speed_comfort_kmh": 30.0,
    "speed_hostile_kmh": 70.0,
    // Empty by default: no country's legal defaults are shipped. Supply your
    // own and implicit zones start scoring; leave it and they stay unknown.
    "implicit_maxspeed_kmh": { "DE:urban": 50, "DE:zone30": 30 },
    "snap_m": 25.0,
    "crossing_snap_m": 40.0,
    "crossing_target_spacing_m": 150.0
  },
  "parking_estimate": {
    "lot_area_per_space_m2": { "surface": 25.0, "multi-storey": 27.5 },
    "modelled_street_types": ["residential", "living_street", "unclassified"],
    "kerb_coverage_factor": 0.8,
    "min_modelled_length_m": 20.0
  }
}
```

The shipped numbers are plausible planning defaults, not measurements from your
city. They are flagged `needs_review` in the API and on the methodology page for
exactly that reason.

---

## API

Both layers are public, read-only and need no login.

```
GET /api/v1/workspaces/<slug>/parked-cars/?include=surveyed,modelled&format=symbols
GET /api/v1/workspaces/<slug>/walkability/?mode=classes
```

`/walkability/` returns a GeoJSON FeatureCollection. Every street carries its
`walk_class`, the `safety_band` and `comfort_band` the popup reads, its
`confidence`, `coverage` and `unknowns`, how its pavement was matched, the space
split, **and** the 0–100 `score`, `safety` and `comfort` plus a `factors` block
giving every factor's value, method, inputs and confidence. The numbers are in
the API because the calculation has to be auditable; the map simply never draws
them.

The collection itself reports `counts` per class, the network's `coverage` and
`space_split_coverage`, which `layers_used` were available, the `params_used`,
whether the parameters still `needs_review`, and a `note` explaining the
conservative reading. `?classes=hostile,tight` filters the features returned
while leaving `counts` describing the whole network, so a filtered view can
still say how much it is hiding.

---

## Limits

- OpenStreetMap sidewalk coverage is patchy in most cities. This is the single
  biggest constraint on both halves.
- `footway_present: null` is silence, not absence. A street with no pavement
  record is not a street without a pavement.
- Capacity is not occupancy, and modelled cars are an assumption, not a count.
- Tagged footway widths are rare, so **Who gets the space** describes a minority
  of streets in most cities.
- A proximity-matched pavement may belong to the parallel street. It is flagged
  and drawn fainter, but it can still be wrong.
- Implicit speed zones stay unresolved unless the workspace supplies its local
  numbers, so a city that tags speeds only by zone will see the speed factor
  silent until it does.
- Obstacle lists are matched by OSM way id and are knowingly incomplete.
- No routing, no detour modelling, no junction geometry, no crossing wait times,
  and nothing about personal safety after dark beyond whether a street is lit.
- The score describes streets, not networks. A comfortable street that ends at a
  motorway slip road still scores comfortable.
