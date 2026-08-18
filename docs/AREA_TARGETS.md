# Target areas

A **target area** is a part of a municipality with a goal attached to it. You draw
it on the map, say what you want to achieve there, and OpenMobility OS works out
which streets to rebuild, what that rebuild costs in parking and carriageway, and
how much harm is still expected once it is done.

It answers the question a story view raises but cannot settle: *we can see where
cyclists are being hurt — now what exactly do we build, and is it enough?*

---

## Contents

- [The workflow](#the-workflow)
- [Ethics: why there is no “90 % fewer deaths” option](#ethics-why-there-is-no-90--fewer-deaths-option)
- [Indicators](#indicators)
- [The data you need](#the-data-you-need)
- [How the space budget works](#how-the-space-budget-works)
- [How the projection works](#how-the-projection-works)
- [Effect factors and their sources](#effect-factors-and-their-sources)
- [Overriding the assumptions for your city](#overriding-the-assumptions-for-your-city)
- [API](#api)
- [Limits](#limits)

---

## The workflow

1. Open `/<workspace>/map/` and activate a story view, e.g. **Cycling gap analysis**.
2. In the **Target areas** panel, sign in as admin and choose **Define target area**.
3. Either click corners on the map to draw a polygon (double-click to close), or
   click an existing polygon on any visible area layer to adopt its shape.
4. Name the area. The indicator is pre-filled from the story view you are in.
   Set a deadline year.
5. **Create and plan.** You land on the area page with the plan.

From the command line:

```bash
python manage.py generate_area_plan <workspace-slug> [<area-slug>]
```

The command is idempotent — re-running rebuilds the plan in place without
creating duplicates.

---

## Ethics: why there is no “90 % fewer deaths” option

For indicators that count people **killed or seriously injured**, the only target
OpenMobility OS will store is **zero**.

A target of “90 % fewer road deaths” contains a second, unstated claim: that the
remaining 10 % is acceptable. Nobody can name which of their neighbours that is,
and a planning tool should not ask them to. So this is enforced structurally, not
by convention:

| Rule | Where it lives |
|---|---|
| Percentage or non-zero targets on severe-harm indicators are rejected | `AreaTarget.clean()` — a `ValidationError`, so the API, the seed loader, and the Django admin all hit it |
| The target form shows no percentage field for those indicators | `map.html`, `areaTargets()` |
| The residual is always reported as an absolute number, never only as a percentage | `AreaPlan.projection["residual_absolute"]`, surfaced first on the area page |
| No “target reached” state while the residual is above zero | `AreaPlan.reaches_target` |
| Segments with people killed or seriously injured rank ahead of higher-volume slight-injury segments | `measures/area_engine.py`, `_rank()` |
| A segment stays in the plan when it is expensive, does not fit, or has unknown width | `measures/area_engine.py`, `street_space.plan_space()` |

The last row matters as much as the first. Dropping a difficult segment would
quietly convert *“this is hard”* into *“this is not a problem”*.

These rules are covered by regression tests in `backend/goals/tests.py` and
`backend/measures/test_area_engine.py`, so a later refactor cannot relax them
silently.

---

## Indicators

Defined in `backend/goals/indicators.py`. Each says what it counts, over what
window, and which layers it needs.

| Key | Counts | Target |
|---|---|---|
| `cyclist_fatal_serious` | Cyclists killed or seriously injured, per year | zero only |
| `vru_fatal_serious` | People walking or cycling, killed or seriously injured | zero only |
| `all_fatal_serious` | All road users killed or seriously injured | zero only |
| `cyclist_accidents_all` | Cyclist collisions of all severities | free |
| `all_accidents` | Road collisions of all severities | free |

The baseline pools the **three most recent years** present in the data and
reports the rate per year, together with the years used and the case count, so it
can be reproduced. Below five recorded cases the projection is flagged as
statistically fragile.

An indicator only appears in the UI when the workspace has the layers it needs —
the same gating rule the story views use.

---

## The data you need

| Layer kind | Needed for | OSM template |
|---|---|---|
| `accidents` | the baseline and every finding | Unfallatlas / accident CSV connectors |
| `streets_with_speed` or `streets` | snapping crashes to segments | `streets_with_speed` |
| `dedicated_bike_network` | telling a gap from an existing lane | `dedicated_bike_network` |
| `street_parking` | *what the rebuild costs in parking* | `street_parking` |
| `car_lanes` | *lane count and carriageway width* | `car_lanes` |
| `obstacles` | tram rails, bridges, crossings in the profile | `obstacles` |

The last three are what make the plan honest. Without them a plan can still say
“a protected lane belongs here”, but not where the space comes from — and it will
say so rather than pretend.

Normalised properties:

```jsonc
// street_parking (LineString along the carriageway)
{"parking_present": true, "side": "left|right|both",
 "orientation": "parallel|diagonal|perpendicular",
 "parking_type": "lane|street_side|on_kerb|half_on_kerb",
 "length_m": 210.0, "restriction": "…"}

// car_lanes (LineString)
{"lanes": 2, "lanes_forward": 1, "lanes_backward": 1, "oneway": false,
 "width_m": 6.5, "width_source": "tagged|estimated|unknown", "highway": "secondary"}

// obstacles (Point | LineString)
{"obstacle_type": "tram_track|level_crossing|bus_stop_in_lane|barrier|bridge|tunnel|narrow_section|construction",
 "affects": "cycling|walking|both", "note": "…"}
```

`width_source` is the honesty flag. `"tagged"` means OSM states a width;
`"estimated"` means it can only be derived from the lane count; `"unknown"` means
neither, and the plan asks for an on-site check instead of producing a number.

Obstacles are matched to a street by OSM way id only. A proximity guess would
send a planner to the wrong street, so the list is labelled *recorded* obstacles
and is knowingly incomplete rather than padded.

---

## How the space budget works

For each proposed segment, `measures/street_space.py` compares the width the
intervention needs against the width available, and takes the shortfall in a
fixed order:

1. **Kerbside parking** — cheapest and most reversible.
2. **A motor-traffic lane** — never the last one; a street has to stay passable.
3. **Narrowing the remaining carriageway** — down to the stated minimum.

The verdict is one of:

| `space_source` | Meaning |
|---|---|
| `not_needed` | the intervention needs no extra width (e.g. a speed limit) |
| `parking_removal` / `lane_reallocation` / `carriageway_narrowing` | the largest contributor; the parking-space and lane totals carry the rest |
| `unknown` | the data does not state a width — check on site |
| `insufficient` | it does not fit even after removing parking and a lane; a larger rebuild is needed |

`unknown` and `insufficient` segments stay in the plan. They are counted
separately in the area's space budget so the difficult parts are visible rather
than absent.

The space budget also feeds the `feasibility` and `political` scores, which for
these measures are computed rather than constant: a rebuild costing eighty
parking spaces really is politically harder than one that fits in spare
carriageway.

---

## How the projection works

```
share_i        = harm on segment i ÷ area baseline
reduction      = Σ (share_i × effect_i)          for low / central / high
projected      = baseline × (1 − reduction)
residual       = projected at the LOW effect     ← the number reported
```

Each segment gets **one** primary intervention, so the shares are disjoint and
the reductions add without double-counting the same crash.

The headline residual uses the **low** end of every effect band — the pessimistic
reading — so a plan is never oversold. The central figure is shown alongside as a
planning value.

`goal_attainment_pct` exists for progress display, but it is explicitly not a
completion signal: `AreaPlan.reaches_target` is true only when the residual is at
or below the target, which for a Vision Zero target means zero.

---

## Effect factors and their sources

Defined in `backend/measures/effects.py`. Each factor is a range with a
confidence and a cited source, printed in full on `/<workspace>/methodology/`.

> **Status: the shipped factors are conservative placeholders.** They follow the
> direction of the road-safety literature (separated cycling infrastructure and
> lower motor-traffic speeds reduce injury risk) but the exact bands have not yet
> been reconciled against a specific figure in the cited work. They carry
> `needs_review: true`, and both the methodology page and every measure
> description say so. **Do not present them as validated evidence, and do not
> remove the flag without checking the source and recording the figure.**

Anything that cannot be evidenced gets a wide band and a low confidence rather
than a confident-looking midpoint.

---

## Overriding the assumptions for your city

Nothing here should require a fork. Both catalogues are overridable per workspace
through `Workspace.settings`:

```json
{
  "effect_factors": {
    "protected_bike_lane": {
      "low": 0.30, "central": 0.42, "high": 0.55,
      "confidence": "high",
      "source": {"title": "Local before/after evaluation 2019–2024", "url": "https://…"}
    }
  },
  "street_space": {
    "car_lane_width_m": 3.25,
    "parking_space_length_m": {"parallel": 6.0},
    "required_width_m": {"protected_bike_lane": 2.5},
    "min_remaining_carriageway_m": 3.5
  },
  "area_engine": { "speed_threshold_kmh": 40 }
}
```

A workspace that supplies its own factor clears the `needs_review` flag for it —
supplying a number is an act of review.

---

## API

Both endpoints are public, like every read endpoint.

```
GET /api/v1/workspaces/<slug>/focus-areas/
GET /api/v1/workspaces/<slug>/focus-areas/<area-slug>/plan/
```

The first returns the areas as GeoJSON with their target status. The second
returns the plan's segments as GeoJSON plus a `plan` block carrying the baseline,
the projection, the space budget, the assumptions and every source — so the whole
argument travels with the data instead of living only in the HTML page.

`residual_absolute` is exposed next to the percentage, so a consumer of the API
cannot render progress without the number of people still expected to be harmed.

---

## Limits

- The projection applies published evidence to local data. It is **not** a
  traffic simulation and says nothing about any individual crash.
- OSM width and lane tagging is patchy in most cities. Segments without a stated
  width are reported as needing a site check, and are counted in the area's space
  budget so the size of that gap is visible.
- Small areas with few recorded cases are statistically fragile; below five cases
  in the window the plan carries a visible warning.
- Regression to the mean is not corrected for.
- The space budget shows the scale of the conflict. It does not replace detailed
  design, and it does not model junction geometry.
- Obstacle lists are matched by OSM way id and are knowingly incomplete.
