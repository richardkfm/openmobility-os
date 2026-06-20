"""Data hub views."""

import json
import logging
import time

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from connectors.registry import get_connector, list_connectors
from core.decorators import admin_required
from core.utils import get_active_workspace
from measures.accident_kpis import compute_accident_kpis
from measures.transit_kpis import compute_transit_kpis
from workspaces.models import ConnectorAuditLog

from .models import DataSource, NormalizedFeatureSet
from .readiness import source_provenance, source_readiness

logger = logging.getLogger(__name__)


def data_hub(request, workspace_slug):
    ws = get_active_workspace(workspace_slug)
    sources = list(ws.data_sources.all().order_by("layer_kind", "name"))
    sources_with_readiness = [
        (s, source_readiness(s), source_provenance(s)) for s in sources
    ]
    feature_sets = NormalizedFeatureSet.objects.filter(workspace=ws)
    return render(
        request,
        "datasets/data_hub.html",
        {
            "workspace": ws,
            "sources": sources,
            "sources_with_readiness": sources_with_readiness,
            "status_choices": dict(DataSource.Status.choices),
            "data_sources_active": sum(1 for s in sources if s.status == DataSource.Status.ACTIVE and s.is_enabled),
            "transit_kpis": compute_transit_kpis(ws, feature_sets),
            "accident_kpis": compute_accident_kpis(ws, feature_sets),
            "page_title": _("Data hub — %(name)s") % {"name": ws.name},
        },
    )


def _get_discoverable(connector_id: str):
    try:
        connector = get_connector(connector_id)
    except KeyError:
        return None
    if not connector.supports_discovery():
        return None
    return connector


def catalog_index(request, workspace_slug):
    ws = get_active_workspace(workspace_slug)
    connectors = [c for c in list_connectors() if c.supports_discovery()]
    return render(
        request,
        "datasets/catalog_index.html",
        {
            "workspace": ws,
            "connectors": connectors,
            "page_title": _("Browse data catalog"),
        },
    )


def catalog_browse(request, workspace_slug, connector_id):
    ws = get_active_workspace(workspace_slug)
    connector = _get_discoverable(connector_id)
    if connector is None:
        messages.error(request, _("Unknown or non-discoverable connector."))
        return redirect(reverse("data_hub", kwargs={"workspace_slug": ws.slug}))

    # The Mobilithek catalog URL can be overridden per workspace. When the
    # admin passes ?catalog_url=… we persist it under workspace.settings
    # so subsequent visits use the same override without re-typing.
    catalog_url_override = request.GET.get("catalog_url", "").strip()
    if (
        request.is_admin
        and connector_id == "mobilithek"
        and catalog_url_override
    ):
        settings_blob = dict(ws.settings or {})
        if settings_blob.get("mobilithek_catalog_url") != catalog_url_override:
            settings_blob["mobilithek_catalog_url"] = catalog_url_override
            ws.settings = settings_blob
            ws.save(update_fields=["settings"])

    query = request.GET.get("q", "").strip() or None
    facets = {k: v for k, v in request.GET.items() if k != "q"}
    page = connector.discover(query=query, facets=facets, workspace=ws)

    template = (
        "datasets/_catalog_results.html"
        if request.headers.get("HX-Request")
        else "datasets/catalog_browse.html"
    )
    return render(
        request,
        template,
        {
            "workspace": ws,
            "connector": connector,
            "page": page,
            "query": query or "",
            "page_title": _("Catalog: %(name)s") % {"name": connector.display_name_de},
        },
    )


@admin_required
@require_POST
def catalog_quickadd(request, workspace_slug, connector_id):
    """Inline form on the catalog page → create a DataSource without a
    pre-existing catalog entry (e.g. an Unfallatlas year not in the YAML)."""
    ws = get_active_workspace(workspace_slug)
    connector = _get_discoverable(connector_id)
    browse_url = reverse(
        "catalog_browse",
        kwargs={"workspace_slug": ws.slug, "connector_id": connector_id},
    )
    if connector is None:
        messages.error(request, _("Unknown or non-discoverable connector."))
        return redirect(reverse("data_hub", kwargs={"workspace_slug": ws.slug}))

    form_data = request.POST.dict()
    uploaded = request.FILES.get("source_file")
    if uploaded:
        # Signal to the connector that a file will provide the data, so it
        # doesn't reject a missing URL. The actual path is injected after the
        # file is saved to storage below.
        form_data["_has_upload"] = "1"

    try:
        entry = connector.quick_add(form_data, workspace=ws)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(browse_url)

    source, created = DataSource.objects.update_or_create(
        workspace=ws,
        name=entry.suggested_name or entry.title,
        defaults={
            "source_type": connector.id,
            "layer_kind": entry.suggested_layer_kind or DataSource.LayerKind.CUSTOM,
            "config": entry.suggested_config or {},
            "license": entry.license or "",
            "attribution": entry.attribution or "",
            "source_url": entry.source_url or "",
        },
    )

    # Persist the uploaded file and point the connector config at its path.
    if uploaded:
        source.source_file = uploaded
        source.save(update_fields=["source_file"])
        config = dict(source.config or {})
        config["url"] = source.source_file.path
        source.config = config
        source.save(update_fields=["config"])

    if request.POST.get("skip_sync"):
        verb = _("created") if created else _("updated")
        messages.success(
            request, _("Data source %(verb)s: %(n)s") % {"verb": verb, "n": source.name}
        )
        return redirect(
            reverse("data_source_detail", kwargs={"workspace_slug": ws.slug, "pk": source.pk})
        )

    success, message = _run_sync(source)
    if success:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return redirect(
        reverse("data_source_detail", kwargs={"workspace_slug": ws.slug, "pk": source.pk})
    )


@admin_required
@require_POST
def catalog_add(request, workspace_slug, connector_id):
    ws = get_active_workspace(workspace_slug)
    connector = _get_discoverable(connector_id)
    if connector is None:
        messages.error(request, _("Unknown or non-discoverable connector."))
        return redirect(reverse("data_hub", kwargs={"workspace_slug": ws.slug}))

    entry_id = request.POST.get("entry_id", "").strip()
    if not entry_id:
        messages.error(request, _("Missing catalog entry id."))
        return redirect(
            reverse(
                "catalog_browse",
                kwargs={"workspace_slug": ws.slug, "connector_id": connector_id},
            )
        )

    query = request.POST.get("q") or None
    page = connector.discover(query=query, facets=None, workspace=ws)
    entry = next((e for e in page.entries if e.entry_id == entry_id), None)
    if entry is None:
        page_all = connector.discover(query=None, facets=None, workspace=ws)
        entry = next((e for e in page_all.entries if e.entry_id == entry_id), None)
    if entry is None:
        messages.error(request, _("Catalog entry no longer available."))
        return redirect(
            reverse(
                "catalog_browse",
                kwargs={"workspace_slug": ws.slug, "connector_id": connector_id},
            )
        )

    source, created = DataSource.objects.update_or_create(
        workspace=ws,
        name=entry.suggested_name or entry.title,
        defaults={
            "source_type": connector.id,
            "layer_kind": entry.suggested_layer_kind or DataSource.LayerKind.CUSTOM,
            "config": entry.suggested_config or {},
            "license": entry.license or "",
            "attribution": entry.attribution or "",
            "source_url": entry.source_url or "",
        },
    )
    if request.POST.get("skip_sync"):
        verb = _("created") if created else _("updated")
        messages.success(
            request, _("Data source %(verb)s: %(n)s") % {"verb": verb, "n": source.name}
        )
        return redirect(
            reverse("data_source_detail", kwargs={"workspace_slug": ws.slug, "pk": source.pk})
        )

    success, message = _run_sync(source)
    if success:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return redirect(
        reverse("data_source_detail", kwargs={"workspace_slug": ws.slug, "pk": source.pk})
    )


@admin_required
def add_data_source(request, workspace_slug):
    ws = get_active_workspace(workspace_slug)
    connectors = list_connectors()

    form_values = {
        "source_type": "",
        "name": "",
        "layer_kind": DataSource.LayerKind.CUSTOM,
        "config": "",
        "license": "",
        "attribution": "",
        "source_url": "",
    }

    if request.method == "POST":
        form_values.update(
            {
                "source_type": request.POST.get("source_type", ""),
                "name": request.POST.get("name", "").strip(),
                "layer_kind": request.POST.get("layer_kind", DataSource.LayerKind.CUSTOM),
                "config": request.POST.get("config", ""),
                "license": request.POST.get("license", ""),
                "attribution": request.POST.get("attribution", ""),
                "source_url": request.POST.get("source_url", ""),
            }
        )

        config_raw = form_values["config"]
        config = None
        if config_raw.strip():
            try:
                config = json.loads(config_raw)
            except json.JSONDecodeError as exc:
                # Don't redirect — re-render with the values so the operator
                # can fix the JSON in place instead of re-typing.
                messages.error(
                    request,
                    _(
                        "Config is not valid JSON (%(err)s). "
                        "Expected an object like {\"url\": \"https://…\"}."
                    )
                    % {"err": f"line {exc.lineno}, col {exc.colno}: {exc.msg}"},
                )
                return _render_add_form(request, ws, connectors, form_values)
        if config is None:
            config = {}

        source = DataSource.objects.create(
            workspace=ws,
            name=form_values["name"] or form_values["source_type"],
            source_type=form_values["source_type"],
            layer_kind=form_values["layer_kind"],
            config=config,
            license=form_values["license"],
            attribution=form_values["attribution"],
            source_url=form_values["source_url"],
        )

        # Handle optional file upload: store file and inject its absolute path
        # into config["url"] so CSV / GeoJSON connectors pick it up automatically.
        uploaded = request.FILES.get("source_file")
        if uploaded:
            source.source_file = uploaded
            source.save(update_fields=["source_file"])
            if source.source_file and "url" not in config:
                source.config = {**config, "url": source.source_file.path}
                source.save(update_fields=["config"])

        messages.success(request, _("Data source added: %(n)s") % {"n": source.name})
        return redirect(
            reverse("data_source_detail", kwargs={"workspace_slug": ws.slug, "pk": source.pk})
        )

    return _render_add_form(request, ws, connectors, form_values)


def _render_add_form(request, ws, connectors, form_values):
    """Render the Add-source page, preserving any values the operator typed.

    Used both for the initial GET and to re-render after a validation
    error so the operator does not lose what they pasted.
    """
    # Serialize connector metadata (id, names, description, config_schema) so
    # the add-form template can render dynamic connector descriptions and field
    # hints via Alpine.js without a round-trip.
    connectors_json = json.dumps(
        {
            c.id: {
                "name": c.display_name_de,
                "name_en": c.display_name_en,
                "description": c.description_de,
                "description_en": c.description_en,
                "config_schema": c.config_schema or {},
                "supports_file": c.id in ("csv", "geojson_url", "unfallat"),
            }
            for c in connectors
        },
        ensure_ascii=False,
    )

    return render(
        request,
        "datasets/data_source_add.html",
        {
            "workspace": ws,
            "connectors": connectors,
            "connectors_json": connectors_json,
            "layer_choices": DataSource.LayerKind.choices,
            "form_values": form_values,
            "page_title": _("Add data source"),
        },
    )


def data_source_detail(request, workspace_slug, pk):
    ws = get_active_workspace(workspace_slug)
    source = get_object_or_404(DataSource, workspace=ws, pk=pk)

    # POST: update source file upload (admin only)
    if request.method == "POST" and request.is_admin:
        uploaded = request.FILES.get("source_file")
        if uploaded:
            source.source_file = uploaded
            source.save(update_fields=["source_file"])
            # Auto-inject file path into config["url"] if not already set
            config = source.config or {}
            if source.source_file:
                config["url"] = source.source_file.path
                source.config = config
                source.save(update_fields=["config"])
            messages.success(request, _("File uploaded and config updated."))
        return redirect(
            reverse("data_source_detail", kwargs={"workspace_slug": ws.slug, "pk": source.pk})
        )

    connector = None
    try:
        connector = get_connector(source.source_type)
    except KeyError:
        pass

    normalized = getattr(source, "normalized", None)
    return render(
        request,
        "datasets/data_source_detail.html",
        {
            "workspace": ws,
            "source": source,
            "normalized": normalized,
            "connector": connector,
            "page_title": source.name,
        },
    )


@admin_required
@require_POST
def toggle_data_source(request, workspace_slug, pk):
    """Toggle the is_enabled flag on a DataSource (activate / deactivate)."""
    ws = get_active_workspace(workspace_slug)
    source = get_object_or_404(DataSource, workspace=ws, pk=pk)
    source.is_enabled = not source.is_enabled
    source.save(update_fields=["is_enabled"])
    if source.is_enabled:
        messages.success(request, _("Data source enabled: %(n)s") % {"n": source.name})
    else:
        messages.success(request, _("Data source disabled: %(n)s") % {"n": source.name})
    # Support HTMX: return to data hub list, or honour ?next= redirect
    next_url = request.POST.get("next") or reverse("data_hub", kwargs={"workspace_slug": ws.slug})
    return redirect(next_url)


@admin_required
@require_POST
def sync_data_source(request, workspace_slug, pk):
    ws = get_active_workspace(workspace_slug)
    source = get_object_or_404(DataSource, workspace=ws, pk=pk)
    success, message = _run_sync(source)
    if success:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return redirect(
        reverse("data_source_detail", kwargs={"workspace_slug": ws.slug, "pk": source.pk})
    )


@admin_required
def test_data_source(request, workspace_slug, pk):
    ws = get_active_workspace(workspace_slug)
    source = get_object_or_404(DataSource, workspace=ws, pk=pk)
    try:
        connector = get_connector(source.source_type)
    except KeyError:
        if request.headers.get("HX-Request"):
            return render(
                request,
                "datasets/_test_panel.html",
                {
                    "success": False,
                    "message": _("Unknown connector: %(t)s") % {"t": source.source_type},
                    "diagnostics": {},
                    "preview_features": [],
                    "workspace": ws,
                    "source": source,
                },
            )
        return JsonResponse(
            {"success": False, "message": f"Unknown connector {source.source_type}"}
        )

    result = connector.test_connection(source.config, workspace=ws)

    if request.headers.get("HX-Request"):
        return render(
            request,
            "datasets/_test_panel.html",
            {
                "success": result.success,
                "message": result.message,
                "diagnostics": result.diagnostics or {},
                "preview_features": result.preview_features or [],
                "workspace": ws,
                "source": source,
                # Workspace bounds as a GeoJSON polygon for the mini-map.
                "workspace_bounds_geojson": _workspace_bounds_geojson(ws),
            },
        )
    return JsonResponse(
        {
            "success": result.success,
            "message": result.message,
            "preview_features": result.preview_features,
            "diagnostics": result.diagnostics,
        }
    )


def _workspace_bounds_geojson(workspace) -> dict | None:
    bounds = getattr(workspace, "bounds", None)
    if bounds is None:
        return None
    try:
        # GeoDjango Polygon → GeoJSON geometry
        return json.loads(bounds.geojson)
    except Exception:  # noqa: BLE001
        return None


@admin_required
@require_POST
def delete_data_source(request, workspace_slug, pk):
    ws = get_active_workspace(workspace_slug)
    source = get_object_or_404(DataSource, workspace=ws, pk=pk)
    source.delete()
    messages.success(request, _("Data source deleted."))
    return redirect(reverse("data_hub", kwargs={"workspace_slug": ws.slug}))


def _run_sync(source: DataSource):
    """Execute a connector fetch and persist the normalized feature set."""
    start_time = time.time()

    try:
        connector = get_connector(source.source_type)
    except KeyError:
        source.status = DataSource.Status.ERROR
        source.error_message = f"Unknown connector type: {source.source_type}"
        source.save(update_fields=["status", "error_message"])
        _log_sync(source, ConnectorAuditLog.Status.ERROR, source.error_message, start_time)
        return False, source.error_message

    source.status = DataSource.Status.PENDING
    source.save(update_fields=["status"])

    # Validate config before hitting the network — connectors with placeholder
    # config (e.g. example data sources shipped with empty URLs) would
    # otherwise raise a low-level `requests.MissingSchema` on the bare URL,
    # which is opaque to the operator.
    config_errors = connector.validate_config(source.config or {})
    if config_errors:
        source.status = DataSource.Status.ERROR
        source.error_message = "Configuration incomplete: " + "; ".join(config_errors)
        source.save(update_fields=["status", "error_message"])
        _log_sync(source, ConnectorAuditLog.Status.ERROR, source.error_message, start_time)
        return False, source.error_message

    try:
        result = connector.fetch(source.config, workspace=source.workspace)
    except NotImplementedError as exc:
        source.status = DataSource.Status.ERROR
        source.error_message = str(exc)
        source.save(update_fields=["status", "error_message"])
        _log_sync(source, ConnectorAuditLog.Status.ERROR, str(exc), start_time)
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 — we want the message surfaced to admin
        logger.exception("Sync failed for source %s", source.pk)
        source.status = DataSource.Status.ERROR
        source.error_message = f"{type(exc).__name__}: {exc}"
        source.save(update_fields=["status", "error_message"])
        _log_sync(source, ConnectorAuditLog.Status.ERROR, source.error_message, start_time)
        return False, source.error_message

    NormalizedFeatureSet.objects.update_or_create(
        source=source,
        defaults={
            "workspace": source.workspace,
            "layer_kind": source.layer_kind,
            "feature_collection": result.feature_collection,
            "record_count": result.record_count,
        },
    )
    source.status = DataSource.Status.ACTIVE
    source.error_message = ""
    source.last_synced_at = timezone.now()
    source.record_count = result.record_count
    source.last_sync_warnings = list(getattr(result, "warnings", []) or [])
    source.save(
        update_fields=[
            "status",
            "error_message",
            "last_synced_at",
            "record_count",
            "last_sync_warnings",
            "updated_at",
        ]
    )
    _log_sync(
        source,
        ConnectorAuditLog.Status.SUCCESS,
        "",
        start_time,
        feature_count=result.record_count,
    )
    base_message = _("Synced %(n)d records.") % {"n": result.record_count}
    if source.last_sync_warnings:
        # Pass warnings back so views can surface them with a distinct
        # styling (Django messages framework).
        joined = " ".join(source.last_sync_warnings)
        return True, f"{base_message} {joined}"
    return True, base_message


def _log_sync(
    source: DataSource,
    status: str,
    error_message: str = "",
    start_time: float = None,
    feature_count: int = None,
):
    """Create an audit log entry for a sync attempt."""
    duration_ms = None
    if start_time is not None:
        duration_ms = int((time.time() - start_time) * 1000)

    ConnectorAuditLog.objects.create(
        workspace=source.workspace,
        datasource=source,
        status=status,
        duration_ms=duration_ms,
        feature_count=feature_count,
        error_message=error_message,
    )
