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
from workspaces.models import ConnectorAuditLog

from .models import DataSource, NormalizedFeatureSet

logger = logging.getLogger(__name__)


def data_hub(request, workspace_slug):
    ws = get_active_workspace(workspace_slug)
    sources = ws.data_sources.all().order_by("layer_kind", "name")
    return render(
        request,
        "datasets/data_hub.html",
        {
            "workspace": ws,
            "sources": sources,
            "status_choices": dict(DataSource.Status.choices),
            "data_sources_active": sources.filter(
                status=DataSource.Status.ACTIVE, is_enabled=True
            ).count(),
            "page_title": _("Data hub — %(name)s") % {"name": ws.name},
        },
    )


@admin_required
def add_data_source(request, workspace_slug):
    ws = get_active_workspace(workspace_slug)
    connectors = list_connectors()

    if request.method == "POST":
        source_type = request.POST.get("source_type")
        name = request.POST.get("name", "").strip()
        layer_kind = request.POST.get("layer_kind", DataSource.LayerKind.CUSTOM)
        config_raw = request.POST.get("config", "{}")
        license_ = request.POST.get("license", "")
        attribution = request.POST.get("attribution", "")
        source_url = request.POST.get("source_url", "")

        try:
            config = json.loads(config_raw) if config_raw else {}
        except json.JSONDecodeError:
            messages.error(request, _("Config must be valid JSON."))
            return redirect(reverse("data_source_add", kwargs={"workspace_slug": ws.slug}))

        source = DataSource.objects.create(
            workspace=ws,
            name=name or source_type,
            source_type=source_type,
            layer_kind=layer_kind,
            config=config,
            license=license_,
            attribution=attribution,
            source_url=source_url,
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
        return JsonResponse({"success": False, "message": f"Unknown connector {source.source_type}"})

    result = connector.test_connection(source.config, workspace=ws)
    return JsonResponse(
        {
            "success": result.success,
            "message": result.message,
            "preview_features": result.preview_features,
        }
    )


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
    source.save(
        update_fields=[
            "status",
            "error_message",
            "last_synced_at",
            "record_count",
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
    return True, _("Synced %(n)d records.") % {"n": result.record_count}


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
