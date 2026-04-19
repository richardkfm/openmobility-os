"""Data hub views."""

import json
import logging

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
        messages.success(request, _("Data source added: %(n)s") % {"n": source.name})
        return redirect(
            reverse("data_source_detail", kwargs={"workspace_slug": ws.slug, "pk": source.pk})
        )

    return render(
        request,
        "datasets/data_source_add.html",
        {
            "workspace": ws,
            "connectors": connectors,
            "layer_choices": DataSource.LayerKind.choices,
            "page_title": _("Add data source"),
        },
    )


def data_source_detail(request, workspace_slug, pk):
    ws = get_active_workspace(workspace_slug)
    source = get_object_or_404(DataSource, workspace=ws, pk=pk)
    normalized = getattr(source, "normalized", None)
    return render(
        request,
        "datasets/data_source_detail.html",
        {
            "workspace": ws,
            "source": source,
            "normalized": normalized,
            "page_title": source.name,
        },
    )


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
    try:
        connector = get_connector(source.source_type)
    except KeyError:
        source.status = DataSource.Status.ERROR
        source.error_message = f"Unknown connector type: {source.source_type}"
        source.save(update_fields=["status", "error_message"])
        return False, source.error_message

    source.status = DataSource.Status.PENDING
    source.save(update_fields=["status"])

    try:
        result = connector.fetch(source.config, workspace=source.workspace)
    except NotImplementedError as exc:
        source.status = DataSource.Status.ERROR
        source.error_message = str(exc)
        source.save(update_fields=["status", "error_message"])
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 — we want the message surfaced to admin
        logger.exception("Sync failed for source %s", source.pk)
        source.status = DataSource.Status.ERROR
        source.error_message = f"{type(exc).__name__}: {exc}"
        source.save(update_fields=["status", "error_message"])
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
    return True, _("Synced %(n)d records.") % {"n": result.record_count}
