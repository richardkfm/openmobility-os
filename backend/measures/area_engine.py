"""Area plan engine — turn a target for an area into a costed, sourced plan.

The output has to survive a council meeting, so it is built to be checked:

* the baseline says which years and which cases it counted;
* every proposed segment says how much of that harm it sits on;
* every effect says which source it came from and how wide the uncertainty is;
* every rebuild says whose parking or which lane pays for the space;
* and the residual — the harm still expected once everything is built — is
  reported as a number, not as a percentage that hides it.

Two rules are structural rather than cosmetic:

**Severity outranks volume.** Segments where someone was killed or seriously
injured are ranked ahead of segments with slight injuries only, whatever the case
counts are. The priority score orders segments *within* those two classes; it
never promotes a high-volume slight-injury street above a fatal one.

**Nothing drops out for being hard.** A segment where the space does not fit, or
where the street width is unknown, stays in the plan with that stated. Removing
it would quietly turn "this is difficult" into "this is not a problem".
"""

import json
from dataclasses import dataclass, field

from django.contrib.gis.geos import GEOSGeometry

from datasets.models import NormalizedFeatureSet
from goals.indicators import compute_baseline, get_indicator

from . import effects as effects_catalogue
from . import street_space
from .accident_density import _filter_accidents, _make_projector
from .area_clip import clip_by_layer
from .interventions import INTERVENTION_FINDERS
from .models import AreaPlan, AreaPlanItem, Measure, MeasureScore
from .rules._common import score

# Layers the engine reads. Missing ones simply yield an empty list — a workspace
# with no kerbside-parking data still gets a plan, it just cannot say where the
# space comes from, and says so.
INPUT_LAYERS = (
    "accidents",
    "streets_with_speed",
    "streets",
    "bike_network",
    "dedicated_bike_network",
    "street_parking",
    "car_lanes",
    "obstacles",
)

# How much a unit of effort is discounted when ordering segments within a
# severity class. Deliberately mild: this sequences work, it does not decide
# what is worth doing.
EFFORT_WEIGHT = {"quick_win": 1.0, "medium": 1.3, "major": 1.8}


@dataclass
class AreaContext:
    """Everything a finder needs, already restricted to the focus area."""

    workspace: object
    focus_area: object
    target: object
    layers: dict = field(default_factory=dict)
    indicator_accidents: list = field(default_factory=list)
    center_lonlat: tuple = (0.0, 0.0)

    def layer(self, kind):
        return self.layers.get(kind) or []

    @property
    def streets(self):
        return self.layer("streets_with_speed") or self.layer("streets")

    def street_props(self, idx):
        """Properties of the idx-th street, enriched from the car_lanes layer."""
        streets = self.streets
        if idx >= len(streets):
            return {}
        props = dict(streets[idx].get("properties") or {})
        enriched = self._lanes_by_id().get(props.get("osm_id"))
        if enriched:
            props = {**props, **enriched}
        return props

    def _lanes_by_id(self):
        if not hasattr(self, "_lanes_cache"):
            self._lanes_cache = {
                (f.get("properties") or {}).get("osm_id"): (f.get("properties") or {})
                for f in self.layer("car_lanes")
            }
        return self._lanes_cache

    def parking_for(self, street_props):
        osm_id = street_props.get("osm_id")
        if osm_id is None:
            return []
        return [
            f
            for f in self.layer("street_parking")
            if (f.get("properties") or {}).get("osm_id") == osm_id
            and (f.get("properties") or {}).get("parking_present")
        ]

    def obstacles_for(self, street_props):
        """Obstacles recorded on the same OSM way.

        Only exact way matches are reported. A proximity guess would send a
        planner to the wrong street, so an incomplete list is preferred and the
        UI labels it as "recorded obstacles", not "all obstacles".
        """
        osm_id = street_props.get("osm_id")
        if osm_id is None:
            return []
        return [
            {
                "obstacle_type": (f.get("properties") or {}).get("obstacle_type"),
                "affects": (f.get("properties") or {}).get("affects"),
                "note": (f.get("properties") or {}).get("note") or "",
            }
            for f in self.layer("obstacles")
            if (f.get("properties") or {}).get("osm_id") == osm_id
        ]

    def setting(self, key, default):
        return ((self.workspace.settings or {}).get("area_engine") or {}).get(key, default)

    def length_m(self, geometry):
        """Length of a GeoJSON line in metres, on the workspace's metric plane.

        Uses the same projector the accident snapping uses, so lengths and snap
        radii are expressed in one consistent local coordinate system.
        """
        return _length_on_plane(geometry, self.center_lonlat)


def _length_on_plane(geometry, center_lonlat):
    if not geometry:
        return None
    transform = _make_projector(center_lonlat)
    coords = geometry.get("coordinates") or []
    gtype = geometry.get("type")
    if gtype == "MultiLineString":
        return round(
            sum(
                _length_on_plane({"type": "LineString", "coordinates": c}, center_lonlat)
                or 0.0
                for c in coords
            ),
            1,
        )
    if gtype != "LineString" or len(coords) < 2:
        return None
    pts = [transform(c[0], c[1]) for c in coords if len(c) >= 2]
    total = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        total += ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    return round(total, 1)


def build_context(area_target) -> AreaContext:
    ws = area_target.workspace
    area = area_target.focus_area
    spec = get_indicator(area_target.indicator) or {}

    by_layer = {}
    for kind in INPUT_LAYERS:
        features = []
        for fs in NormalizedFeatureSet.objects.filter(
            workspace=ws, layer_kind=kind, source__is_enabled=True
        ):
            features.extend((fs.feature_collection or {}).get("features") or [])
        by_layer[kind] = features

    clipped = clip_by_layer(by_layer, area.geometry)

    # The years the baseline counted, so segment-level counts and the area
    # baseline are drawn from exactly the same set of cases.
    _value, meta = compute_baseline(area_target.indicator, clipped)
    indicator_accidents = _filter_accidents(
        clipped.get("accidents") or [],
        years=[str(y) for y in (meta.get("years") or [])] or None,
        severities=sorted(spec.get("severities") or []) or None,
        modes=sorted(spec.get("modes") or []) or None,
    )

    center = getattr(ws, "center", None)
    return AreaContext(
        workspace=ws,
        focus_area=area,
        target=area_target,
        layers=clipped,
        indicator_accidents=indicator_accidents,
        center_lonlat=(center.x, center.y) if center else (0.0, 0.0),
    )


def build_area_plan(area_target) -> AreaPlan:
    """Generate (or regenerate) the plan for one area target.

    Idempotent: measures are upserted on a deterministic slug and any measure
    from a previous run of this plan that is no longer proposed is removed.
    """
    ws = area_target.workspace
    context = build_context(area_target)

    baseline_value, baseline_meta = compute_baseline(area_target.indicator, context.layers)

    candidates = []
    for finder in INTERVENTION_FINDERS:
        try:
            candidates.extend(finder(context) or [])
        # A finder is third-party-ish extension code; one that raises must not
        # take the whole plan down with it, so the failure is recorded instead.
        except Exception as exc:
            baseline_meta.setdefault("finder_errors", []).append(
                {"finder": finder.__name__, "error": str(exc)}
            )

    candidates = _resolve_overlaps(candidates)
    factors = effects_catalogue.factors_for(ws)
    params = street_space.params_for(ws)

    # The baseline is a rate per year, but a finder counts the raw cases sitting
    # on a segment across the whole window. Dividing by the number of years
    # counted puts both on the same footing. Without this every segment would
    # claim several times its true share of the harm, and the plan would
    # overstate what it can deliver — the one error that must not happen here.
    years_counted = baseline_meta.get("years_counted") or 1

    items = []
    for cand in candidates:
        factor = factors.get(cand.intervention)
        budget = street_space.plan_space(
            cand.intervention,
            cand.street_props,
            parking_features=cand.parking_features,
            obstacles=cand.obstacles,
            segment_length_m=cand.quantity,
            params=params,
        )
        cases_per_year = cand.affected_cases / years_counted
        share = (cases_per_year / baseline_value) if baseline_value else 0.0
        # Disjoint shares can never exceed the whole, so a rounding artefact
        # must not be allowed to push a single segment past 100 %.
        share = min(share, 1.0)
        items.append({"candidate": cand, "factor": factor, "budget": budget, "share": share})

    items = _rank(items)

    reduction = effects_catalogue.combine(
        [(i["share"], i["factor"]) for i in items if i["factor"]]
    )
    projection = _project(baseline_value, reduction, area_target)
    space_budget = _summarize_space(items)

    plan, _created = AreaPlan.objects.update_or_create(
        area_target=area_target,
        defaults={
            "workspace": ws,
            "assumptions": {
                "effect_factors": {
                    k: {
                        band: v[band] for band in ("low", "central", "high")
                    }
                    | {
                        "confidence": v.get("confidence"),
                        "needs_review": v.get("needs_review", False),
                        "overridden": v.get("overridden", False),
                    }
                    for k, v in factors.items()
                },
                "street_space": params,
                "indicator": area_target.indicator,
                "overlap_rule": "one primary intervention per segment; shares disjoint",
                "ranking_rule": (
                    "segments with people killed or seriously injured are ranked "
                    "first; the priority score orders within that class only"
                ),
            },
            "baseline": {"value": baseline_value, **baseline_meta},
            "projection": projection,
            "space_budget": space_budget,
            "sources": _collect_sources(items),
        },
    )

    _persist_items(plan, items, area_target)
    return plan


def _resolve_overlaps(candidates):
    """Keep one primary intervention per segment so shares stay disjoint.

    Without this the same crash could be counted under a cycle lane *and* a
    speed limit on the same street, and the combined reduction would overstate
    what the plan can do. The intervention with the larger central effect wins;
    the other is dropped rather than applied to the residual, because a second
    treatment's marginal benefit is not something the source evidence supports
    estimating.
    """
    best: dict = {}
    for cand in candidates:
        key = cand.key.split("-", 1)[-1]  # the street index
        current = best.get(key)
        if current is None:
            best[key] = cand
            continue
        factors = effects_catalogue.EFFECT_FACTORS
        new_effect = (factors.get(cand.intervention) or {}).get("central", 0)
        old_effect = (factors.get(current.intervention) or {}).get("central", 0)
        if new_effect > old_effect:
            best[key] = cand
    return list(best.values())


def _rank(items):
    """Severity first, then expected benefit per unit of effort.

    The two-class split is the ethical part: no amount of slight-injury volume
    outranks a segment where someone was killed or seriously injured.
    """

    def sort_key(item):
        cand = item["candidate"]
        factor = item["factor"] or {}
        effort = EFFORT_WEIGHT.get(_effort_for(item), 1.3)
        benefit = item["share"] * float(factor.get("central", 0.0))
        return (0 if cand.severe else 1, -(benefit / effort))

    ordered = sorted(items, key=sort_key)
    for rank, item in enumerate(ordered, start=1):
        item["rank"] = rank
    return ordered


def _effort_for(item) -> str:
    """Effort class, driven by how invasive the space reallocation is."""
    source = item["budget"].space_source
    if source in ("not_needed",):
        return "quick_win"
    if source in ("parking_removal",):
        return "medium"
    return "major"


def _project(baseline_value, reduction, area_target) -> dict:
    """Turn the aggregated reduction into the numbers the UI reports.

    ``residual_absolute`` leads deliberately. For a Vision Zero target it is the
    only honest headline: the harm still expected after the entire plan is
    built. ``goal_attainment_pct`` is provided for progress display but is
    explicitly *not* a completion signal — see :attr:`AreaPlan.reaches_target`.
    """
    out = {}
    for band in ("low", "central", "high"):
        out[band] = round(baseline_value * (1 - reduction[band]), 3)
    # "low" reduction leaves the most harm behind. That pessimistic reading is
    # the one reported as the residual, so the plan is never oversold.
    out["residual_absolute"] = out["low"]
    out["residual_central"] = out["central"]
    out["reduction"] = reduction
    out["baseline"] = baseline_value

    target = area_target.target_value
    if target is not None and baseline_value > target:
        attained = (baseline_value - out["central"]) / (baseline_value - target) * 100
        out["goal_attainment_pct"] = round(max(0.0, min(attained, 100.0)), 1)
    else:
        out["goal_attainment_pct"] = None

    out["is_vision_zero"] = area_target.is_vision_zero
    out["meets_target"] = (
        target is not None and out["residual_absolute"] <= target
    )
    out["share_addressed"] = reduction.get("share_addressed", 0.0)
    return out


def _summarize_space(items) -> dict:
    parking = sum(i["budget"].parking_spaces_removed for i in items)
    lanes = sum(i["budget"].car_lanes_reallocated for i in items)
    unknown = [i for i in items if i["budget"].width_confidence == "unknown"]
    insufficient = [i for i in items if i["budget"].space_source == "insufficient"]
    return {
        "parking_spaces_removed": parking,
        "car_lanes_reallocated": lanes,
        "segments_total": len(items),
        "segments_width_unknown": len(unknown),
        "segments_insufficient_space": len(insufficient),
        "note": (
            "Parking-space counts are estimates derived from segment length and "
            "the bay length in this workspace's street-space parameters. "
            "Segments with unknown width need an on-site check."
        ),
    }


def _collect_sources(items) -> list:
    seen, out = set(), []
    for item in items:
        source = (item["factor"] or {}).get("source")
        if not source:
            continue
        key = source.get("url") or source.get("title")
        if key in seen:
            continue
        seen.add(key)
        out.append(source)
    return out


def _persist_items(plan, items, area_target):
    ws = area_target.workspace
    area = area_target.focus_area
    keep_slugs = set()

    # Remember what the previous run of *this* plan produced, so stale measures
    # can be cleaned up without touching measures belonging to another target
    # in the same area.
    previous_slugs = set(
        AreaPlanItem.objects.filter(plan=plan).values_list("measure__slug", flat=True)
    )
    AreaPlanItem.objects.filter(plan=plan).delete()

    for item in items:
        cand = item["candidate"]
        budget = item["budget"]
        factor = item["factor"] or {}
        slug = f"area-{area.slug}-{cand.intervention.replace('_', '-')}-{item['rank']}"[:120]
        keep_slugs.add(slug)

        measure = _upsert_measure(ws, area, slug, cand, budget, factor, item)
        AreaPlanItem.objects.create(
            plan=plan,
            measure=measure,
            rank=item["rank"],
            intervention=cand.intervention,
            quantity=cand.quantity,
            unit=cand.unit,
            width_required_m=budget.required_width_m,
            width_available_m=budget.available_width_m,
            width_confidence=budget.width_confidence,
            space_source=budget.space_source,
            parking_spaces_removed=budget.parking_spaces_removed,
            car_lanes_reallocated=budget.car_lanes_reallocated,
            obstacles=budget.obstacles,
            affected_baseline=round(item["share"], 4),
            affected_severity=(
                AreaPlanItem.AffectedSeverity.FATAL_SERIOUS
                if cand.severe
                else AreaPlanItem.AffectedSeverity.MINOR_ONLY
            ),
            effect_low=float(factor.get("low", 0.0)),
            effect_central=float(factor.get("central", 0.0)),
            effect_high=float(factor.get("high", 0.0)),
            confidence=factor.get("confidence", "low"),
            sources=[factor["source"]] if factor.get("source") else [],
        )

    # Drop measures from an earlier run of this plan that are no longer proposed.
    stale = previous_slugs - keep_slugs
    if stale:
        Measure.objects.filter(workspace=ws, focus_area=area, slug__in=stale).delete()


def _upsert_measure(ws, area, slug, cand, budget, factor, item):
    geometry = None
    if cand.geometry:
        try:
            geometry = GEOSGeometry(json.dumps(cand.geometry), srid=4326)
        except (ValueError, TypeError):
            geometry = None

    summary_de, summary_en = _summaries(cand, budget)
    measure, _created = Measure.objects.update_or_create(
        workspace=ws,
        slug=slug,
        defaults={
            "category": "bike_infra"
            if cand.intervention == "protected_bike_lane"
            else "safety",
            "title_de": cand.title_de,
            "title_en": cand.title_en,
            "summary_de": summary_de[:500],
            "summary_en": summary_en[:500],
            "description_de_md": _describe(cand, budget, factor, "de"),
            "description_en_md": _describe(cand, budget, factor, "en"),
            "effort_level": _effort_for(item),
            "is_auto_generated": True,
            "focus_area": area,
            "district": area.district,
            "geometry": geometry,
            "evidence": {
                **cand.evidence,
                "space_budget": {
                    "required_width_m": budget.required_width_m,
                    "available_width_m": budget.available_width_m,
                    "width_confidence": budget.width_confidence,
                    "space_source": budget.space_source,
                    "parking_spaces_removed": budget.parking_spaces_removed,
                    "car_lanes_reallocated": budget.car_lanes_reallocated,
                    "obstacles": budget.obstacles,
                },
                "share_of_area_baseline": round(item["share"], 4),
            },
        },
    )
    _score_measure(measure, cand, budget, factor, item)
    return measure


def _score_measure(measure, cand, budget, factor, item):
    """Attach the nine transparent dimensions.

    ``feasibility`` and ``political`` are computed from the space budget rather
    than set to a constant: a rebuild that costs eighty parking spaces is
    politically harder than one that fits in spare carriageway, and the platform
    should say so instead of pretending all segments are alike.
    """
    sources = [factor["source"]] if factor.get("source") else []
    severe = cand.severe

    feasibility = {
        "not_needed": 0.85,
        "carriageway_narrowing": 0.7,
        "parking_removal": 0.55,
        "lane_reallocation": 0.4,
        "unknown": 0.4,
        "insufficient": 0.2,
    }.get(budget.space_source, 0.4)
    if budget.obstacles:
        feasibility = max(0.15, feasibility - 0.1)

    political = feasibility
    if budget.parking_spaces_removed >= 50:
        political = max(0.15, political - 0.15)
    elif budget.parking_spaces_removed >= 20:
        political = max(0.2, political - 0.08)

    space_de, space_en = _space_rationale(budget)

    scores = {
        "safety": score(
            0.95 if severe else 0.7,
            "high" if severe else "medium",
            "Segment mit Getöteten oder Schwerverletzten."
            if severe
            else "Segment mit dokumentierten Unfällen ohne schwere Folgen.",
            "Segment where someone was killed or seriously injured."
            if severe
            else "Segment with recorded collisions, no severe outcomes.",
            sources,
        ),
        "climate": score(0.5 if cand.intervention == "protected_bike_lane" else 0.35),
        "quality_of_life": score(0.7),
        "social": score(0.7),
        "feasibility": score(feasibility, "medium", space_de, space_en),
        "cost": score(
            0.6 if budget.space_source in ("not_needed", "parking_removal") else 0.4
        ),
        "visibility": score(0.75),
        "political": score(political, "low", space_de, space_en),
        "goal_alignment": score(
            0.9,
            "high",
            "Direkt einem Gebietsziel zugeordnet.",
            "Directly attached to an area target.",
        ),
    }
    for dimension, payload in scores.items():
        MeasureScore.objects.update_or_create(
            measure=measure,
            dimension=dimension,
            defaults={
                "raw_value": payload["raw"],
                "display_value": payload["display"],
                "confidence": payload["confidence"],
                "rationale_de": payload["rationale_de"],
                "rationale_en": payload["rationale_en"],
                "sources": payload["sources"],
            },
        )


def _space_rationale(budget):
    if budget.space_source == "insufficient":
        return (
            "Der Querschnitt reicht auch nach Wegfall des Parkens nicht — "
            "größerer Umbau erforderlich.",
            "The cross-section is too narrow even without parking — a larger "
            "rebuild is required.",
        )
    if budget.space_source == "unknown":
        return (
            "Fahrbahnbreite in den Daten nicht angegeben — vor Ort prüfen.",
            "Carriageway width is not stated in the data — check on site.",
        )
    if budget.space_source == "parking_removal":
        return (
            f"Platz durch Wegfall von ca. {budget.parking_spaces_removed} Stellplätzen.",
            f"Space from removing approx. {budget.parking_spaces_removed} parking spaces.",
        )
    if budget.space_source == "lane_reallocation":
        return (
            f"Platz durch Umwidmung von {budget.car_lanes_reallocated} Kfz-Spur(en).",
            f"Space from reallocating {budget.car_lanes_reallocated} motor-traffic lane(s).",
        )
    if budget.space_source == "carriageway_narrowing":
        return (
            "Platz durch Verschmälerung der Restfahrbahn.",
            "Space from narrowing the remaining carriageway.",
        )
    return (
        "Kein zusätzlicher Querschnitt erforderlich.",
        "No additional cross-section required.",
    )


def _summaries(cand, budget):
    space_de, space_en = _space_rationale(budget)
    return (
        f"{int(cand.affected_cases)} Fälle im Zielindikator auf diesem Abschnitt. {space_de}",
        f"{int(cand.affected_cases)} cases of the target indicator on this segment. {space_en}",
    )


def _describe(cand, budget, factor, lang) -> str:
    de = lang == "de"
    space_de, space_en = _space_rationale(budget)
    source = factor.get("source") or {}
    src_line = (
        f"[{source.get('title', '—')}]({source.get('url')})"
        if source.get("url")
        else source.get("title", "—")
    )
    review = factor.get("needs_review")
    obstacles = ", ".join(
        o.get("obstacle_type") or "?" for o in (budget.obstacles or [])
    ) or ("keine erfasst" if de else "none recorded")

    if de:
        return (
            "## Befund\n"
            f"Auf diesem Abschnitt liegen **{int(cand.affected_cases)} Fälle** des "
            "Zielindikators.\n\n"
            "## Flächenbilanz\n"
            f"- Benötigte Breite: {budget.required_width_m or 0} m\n"
            f"- Verfügbare Breite: {_width_text(budget, 'unbekannt')} m "
            f"({budget.width_confidence})\n"
            f"- {space_de}\n"
            f"- Erfasste Zwangspunkte: {obstacles}\n\n"
            "## Erwartete Wirkung\n"
            f"{_effect_line(factor, de=True)}\n\n"
            f"Quelle: {src_line}\n"
            + (
                "\n> **Hinweis:** Dieser Wirkungsfaktor ist noch nicht gegen die "
                "Quelle geprüft und dient als konservativer Platzhalter.\n"
                if review
                else ""
            )
        )
    return (
        "## Finding\n"
        f"This segment carries **{int(cand.affected_cases)} cases** of the target "
        "indicator.\n\n"
        "## Space budget\n"
        f"- Width required: {budget.required_width_m or 0} m\n"
        f"- Width available: {_width_text(budget, 'unknown')} m "
        f"({budget.width_confidence})\n"
        f"- {space_en}\n"
        f"- Recorded obstacles: {obstacles}\n\n"
        "## Expected effect\n"
        f"{_effect_line(factor, de=False)}\n\n"
        f"Source: {src_line}\n"
        + (
            "\n> **Note:** this effect factor has not yet been checked against its "
            "source and stands as a conservative placeholder.\n"
            if review
            else ""
        )
    )


def _width_text(budget, unknown_label):
    """Width as text, saying plainly when the data does not state one."""
    if budget.available_width_m is None:
        return unknown_label
    return str(budget.available_width_m)


def _effect_line(factor, *, de):
    if not factor:
        return "—"
    low = round(factor["low"] * 100)
    central = round(factor["central"] * 100)
    high = round(factor["high"] * 100)
    if de:
        return (
            f"Erwartete Reduktion der Fälle auf diesem Abschnitt: "
            f"**{low}–{high} %** (Planwert {central} %), Konfidenz "
            f"{factor.get('confidence', 'low')}."
        )
    return (
        f"Expected reduction of cases on this segment: **{low}–{high} %** "
        f"(planning figure {central} %), confidence {factor.get('confidence', 'low')}."
    )
