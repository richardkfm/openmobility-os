"""GeoJSON feature API consumed by MapLibre on the workspace map page."""

import json
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_GET

from core.utils import get_active_workspace
from goals.indicators import label_for as indicator_label
from datasets.mobility_gaps import compute_gap_grid
from datasets.models import DataSource, MobilitySnapshot, NormalizedFeatureSet
from measures.accident_density import compute_density_lines
from measures.models import MeasureScore
from measures.scoring import compute_priority_score


def _features_for_kind(ws, layer_kind):
    """Aggregate features across all enabled sources of a layer kind."""
    feature_sets = NormalizedFeatureSet.objects.filter(
        workspace=ws, layer_kind=layer_kind, source__is_enabled=True
    )
    features: list = []
    for fs in feature_sets:
        fc = fs.feature_collection or {}
        features.extend(fc.get("features") or [])
    return features


def _csv_param(request, name):
    """Parse a comma-separated query param into a list (empty → None)."""
    raw = (request.GET.get(name) or "").strip()
    if not raw:
        return None
    return [v.strip() for v in raw.split(",") if v.strip()]


@require_GET
@cache_page(30)
def workspace_layer(request, workspace_slug: str, layer_kind: str):
    ws = get_active_workspace(workspace_slug)
    # Multiple data sources can publish into the same layer kind (e.g. one
    # Unfallatlas datasource per year). Aggregate across all feature sets so
    # the map sees a single FeatureCollection per layer.
    # Disabled sources (is_enabled=False) are excluded from map rendering.
    features = _features_for_kind(ws, layer_kind)
    return JsonResponse({"type": "FeatureCollection", "features": features})


@require_GET
@cache_page(300)
def accident_density_view(request, workspace_slug: str):
    """Streets coloured by severity-weighted accident density (Unfallatlas-style).

    Snaps accident points to the workspace street network and returns one
    coloured LineString per street that received matching accidents. The
    aggregation depends on the active filters, so unlike the circle/heatmap
    layers this is recomputed server-side per filter combination (cached for
    5 minutes, keyed on the querystring). Filters: ``years``, ``severity``,
    ``modes`` — all comma-separated; empty means "all". The ``modes`` filter
    (e.g. ``cyclist``) drives the aggregation here, which is what powers the
    cycling-infrastructure-gap workflow.
    """
    ws = get_active_workspace(workspace_slug)
    accidents = _features_for_kind(ws, "accidents")
    streets = _features_for_kind(ws, "streets_with_speed") or _features_for_kind(
        ws, "streets"
    )

    center = ws.center
    center_lonlat = (center.x, center.y) if center else (0.0, 0.0)

    fc = compute_density_lines(
        accidents,
        streets,
        center_lonlat=center_lonlat,
        years=_csv_param(request, "years"),
        severities=_csv_param(request, "severity"),
        modes=_csv_param(request, "modes"),
    )
    return JsonResponse(fc)


@require_GET
def workspace_measures_geojson(request, workspace_slug: str):
    ws = get_active_workspace(workspace_slug)
    lang = getattr(request, "LANGUAGE_CODE", "de")
    weights = ws.scoring_weights or {}
    features = []
    for m in ws.measures.exclude(geometry__isnull=True).prefetch_related("scores"):
        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(m.geometry.geojson),
                "properties": {
                    "slug": m.slug,
                    "title": m.title_localized(lang),
                    "summary": m.summary_localized(lang),
                    "category": m.category,
                    "effort_level": m.effort_level,
                    "status": m.status,
                    "priority_score": compute_priority_score(m, weights),
                },
            }
        )
    return JsonResponse({"type": "FeatureCollection", "features": features})


def _parse_int_range(raw: str | None, lo: int, hi: int) -> set[int] | None:
    """Parse ``"7-9"`` or ``"1,3,5"`` into a set of ints within ``[lo, hi]``.

    Returns ``None`` for an empty/absent value (meaning "no filter").
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                start, end = int(a), int(b)
            except ValueError:
                continue
            for v in range(min(start, end), max(start, end) + 1):
                if lo <= v <= hi:
                    out.add(v)
        else:
            try:
                v = int(part)
            except ValueError:
                continue
            if lo <= v <= hi:
                out.add(v)
    return out or None


@require_GET
@cache_page(120)
def shared_mobility_gaps_view(request, workspace_slug: str):
    """Temporal availability / gap grid for a shared-mobility source.

    Aggregates the :class:`MobilitySnapshot` history recorded by the
    ``collect_mobility_snapshots`` command into a grid of cells, each carrying
    a ``gap_rate`` (fraction of the time window the cell had no available
    vehicle) plus mean/peak counts. Colour the result by ``gap_rate`` to see
    where shared vehicles are reliably available versus where the persistent
    pick-up gaps are.

    Query parameters (all optional):
        ``source``        — DataSource pk; defaults to the most recently
                            sampled shared-mobility source in the workspace.
        ``days``          — look-back window in days (default 7, max 90).
        ``hours``         — hour-of-day filter in workspace local time,
                            e.g. ``7-9`` (morning peak) or ``0,1,2``.
        ``weekdays``      — ISO weekday filter, 1=Mon … 7=Sun, e.g. ``1-5``.
        ``form_factors``  — comma list, e.g. ``car`` or ``bicycle,scooter``.
    """
    ws = get_active_workspace(workspace_slug)

    shared_kinds = [
        DataSource.LayerKind.SHARED_VEHICLES,
        DataSource.LayerKind.SHARED_STATIONS,
    ]

    source = None
    source_id = (request.GET.get("source") or "").strip()
    if source_id.isdigit():
        source = ws.data_sources.filter(
            pk=int(source_id), layer_kind__in=shared_kinds
        ).first()
    if source is None:
        latest = (
            MobilitySnapshot.objects.filter(
                workspace=ws, source__layer_kind__in=shared_kinds
            )
            .order_by("-captured_at")
            .first()
        )
        source = latest.source if latest else None

    empty = {"type": "FeatureCollection", "features": [], "samples": 0}
    if source is None:
        return JsonResponse({**empty, "message": "No shared-mobility snapshots yet."})

    try:
        days = max(1, min(int(request.GET.get("days", 7)), 90))
    except ValueError:
        days = 7
    since = timezone.now() - timedelta(days=days)

    hours = _parse_int_range(request.GET.get("hours"), 0, 23)
    weekdays = _parse_int_range(request.GET.get("weekdays"), 1, 7)
    factors_raw = (request.GET.get("form_factors") or "").strip()
    form_factors = (
        [f.strip() for f in factors_raw.split(",") if f.strip()] or None
    )

    try:
        tz = ZoneInfo(ws.timezone) if ws.timezone else timezone.get_current_timezone()
    except (ZoneInfoNotFoundError, ValueError):
        tz = timezone.get_current_timezone()

    snapshots = list(
        MobilitySnapshot.objects.filter(
            source=source, captured_at__gte=since
        ).order_by("-captured_at")
    )
    if not snapshots:
        return JsonResponse({**empty, "source": source.pk})

    # Cell keys only line up across snapshots that share a grid resolution.
    # Pin to the most recent snapshot's grid and drop any with a different one
    # (e.g. taken before the operator changed --cell-size).
    lon_step = snapshots[0].lon_step
    lat_step = snapshots[0].lat_step

    grids = []
    for snap in snapshots:
        if snap.lon_step != lon_step or snap.lat_step != lat_step:
            continue
        local = snap.captured_at.astimezone(tz)
        if hours is not None and local.hour not in hours:
            continue
        if weekdays is not None and local.isoweekday() not in weekdays:
            continue
        grids.append(snap.cell_counts or {})

    fc = compute_gap_grid(grids, lon_step, lat_step, form_factors=form_factors)
    fc["source"] = source.pk
    fc["source_name"] = source.name
    fc["window_days"] = days
    return JsonResponse(fc)


@require_GET
@cache_page(60)
def district_scores_view(request, workspace_slug: str):
    """Districts coloured by aggregate measure priority.

    The ``dimension`` query parameter selects a single scoring dimension
    (e.g. ``safety``, ``climate``). Omit it or pass an unknown value to use
    the workspace-weighted overall priority score.
    """
    ws = get_active_workspace(workspace_slug)
    dimension = (request.GET.get("dimension") or "").strip()
    valid_dims = {d for d, _ in MeasureScore.Dimension.choices}
    if dimension not in valid_dims:
        dimension = ""

    weights = ws.scoring_weights or {}
    features = []

    for district in ws.districts.all():
        if district.geometry is None:
            continue

        measures = list(district.measures.prefetch_related("scores").all())

        if not measures:
            score = 0.0
            measure_count = 0
        elif dimension:
            vals = []
            for m in measures:
                for s in m.scores.all():
                    if s.dimension == dimension:
                        vals.append(s.display_value)
                        break
            score = round(sum(vals) / len(vals), 1) if vals else 0.0
            measure_count = len(measures)
        else:
            scores_list = [compute_priority_score(m, weights) for m in measures]
            score = round(sum(scores_list) / len(scores_list), 1) if scores_list else 0.0
            measure_count = len(measures)

        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(district.geometry.geojson),
                "properties": {
                    "district_name": district.name,
                    "score": score,
                    "measure_count": measure_count,
                },
            }
        )

    return JsonResponse({"type": "FeatureCollection", "features": features})


@require_GET
@cache_page(60)
def focus_areas_view(request, workspace_slug: str):
    """Focus areas of a workspace as GeoJSON, with their target status.

    Public, like every read endpoint. ``residual_absolute`` is exposed next to
    the percentage so a consumer of this API cannot render progress without the
    number of people still expected to be harmed.
    """
    ws = get_active_workspace(workspace_slug)
    lang = getattr(request, "LANGUAGE_CODE", "de")

    features = []
    for area in ws.focus_areas.prefetch_related("targets__plans"):
        target = area.current_target
        plan = target.plans.first() if target else None
        projection = (plan.projection or {}) if plan else {}
        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(area.geometry.geojson),
                "properties": {
                    "slug": area.slug,
                    "name": area.name,
                    "origin": area.origin,
                    "indicator": target.indicator if target else None,
                    "indicator_label": (
                        indicator_label(target.indicator, lang) if target else None
                    ),
                    "baseline": projection.get("baseline"),
                    "target_value": target.target_value if target else None,
                    "is_vision_zero": target.is_vision_zero if target else False,
                    "residual_absolute": projection.get("residual_absolute"),
                    "goal_attainment_pct": projection.get("goal_attainment_pct"),
                    "meets_target": projection.get("meets_target", False),
                    "item_count": plan.items.count() if plan else 0,
                },
            }
        )
    return JsonResponse({"type": "FeatureCollection", "features": features})


@require_GET
@cache_page(60)
def area_plan_view(request, workspace_slug: str, area_slug: str):
    """One area's plan: the proposed segments plus the numbers behind them.

    The ``plan`` block carries the baseline, the projection band, the space
    budget and every source used, so the whole argument travels with the data
    instead of only living in the HTML page.
    """
    ws = get_active_workspace(workspace_slug)
    area = ws.focus_areas.filter(slug=area_slug).first()
    if area is None:
        raise Http404("No such focus area in this workspace")

    target = area.current_target
    plan = target.plans.first() if target else None
    if plan is None:
        return JsonResponse(
            {
                "type": "FeatureCollection",
                "features": [],
                "plan": None,
                "message": "No plan generated for this area yet.",
            }
        )

    features = []
    for item in plan.items.select_related("measure").order_by("rank"):
        measure = item.measure
        features.append(
            {
                "type": "Feature",
                "geometry": (
                    json.loads(measure.geometry.geojson) if measure.geometry else None
                ),
                "properties": {
                    "rank": item.rank,
                    "measure_slug": measure.slug,
                    "intervention": item.intervention,
                    "quantity": item.quantity,
                    "unit": item.unit,
                    "width_required_m": item.width_required_m,
                    "width_available_m": item.width_available_m,
                    "width_confidence": item.width_confidence,
                    "space_source": item.space_source,
                    "parking_spaces_removed": item.parking_spaces_removed,
                    "car_lanes_reallocated": item.car_lanes_reallocated,
                    "obstacles": item.obstacles,
                    "share_of_baseline": item.affected_baseline,
                    "affected_severity": item.affected_severity,
                    "effect_low": item.effect_low,
                    "effect_central": item.effect_central,
                    "effect_high": item.effect_high,
                    "confidence": item.confidence,
                    "sources": item.sources,
                },
            }
        )

    return JsonResponse(
        {
            "type": "FeatureCollection",
            "features": features,
            "plan": {
                "area": area.slug,
                "indicator": target.indicator,
                "is_vision_zero": target.is_vision_zero,
                "target_value": target.target_value,
                "deadline_year": target.deadline_year,
                "baseline": plan.baseline,
                "projection": plan.projection,
                "space_budget": plan.space_budget,
                "assumptions": plan.assumptions,
                "sources": plan.sources,
                "generated_at": plan.generated_at.isoformat(),
            },
        }
    )
