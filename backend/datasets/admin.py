"""Django admin configuration for datasets app.

Provides a full data-source management interface directly from /django-admin/
so operators who prefer the Django admin over the workspace data-hub UI can:
  - List, filter and search all data sources across workspaces
  - Toggle is_enabled in the list view (inline checkbox)
  - Upload or replace a source file without touching JSON config
  - Run "Sync now", "Enable", or "Disable" bulk actions
  - View connector schema hints on the change page
  - Preview the normalized feature set as a read-only inline
"""

import json
import logging

from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import DataSource, NormalizedFeatureSet

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inline: NormalizedFeatureSet preview inside DataSource change page
# ---------------------------------------------------------------------------

class NormalizedFeatureSetInline(admin.StackedInline):
    model = NormalizedFeatureSet
    can_delete = False
    extra = 0
    max_num = 1
    readonly_fields = (
        "layer_kind", "record_count", "schema_version", "synced_at",
        "feature_preview",
    )
    fields = readonly_fields
    verbose_name = _("Normalized feature set (latest sync)")
    verbose_name_plural = verbose_name

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description=_("Feature preview (first 3)"))
    def feature_preview(self, obj):
        if not obj.feature_collection:
            return "—"
        features = (obj.feature_collection or {}).get("features") or []
        snippet = json.dumps(features[:3], indent=2, ensure_ascii=False)
        return format_html(
            '<pre style="font-size:0.75rem;max-height:200px;overflow:auto;'
            'background:#f8fafc;padding:8px;border-radius:4px;">{}</pre>',
            snippet,
        )


# ---------------------------------------------------------------------------
# Custom admin form — adds a file-upload widget that auto-fills config["url"]
# ---------------------------------------------------------------------------

class DataSourceAdminForm(forms.ModelForm):
    """Extends the default ModelForm with a convenience file-upload field.

    When an operator uploads a file its absolute path on disk is injected into
    config["url"] automatically so the connector's fetch logic picks it up
    without manual JSON editing.
    """

    upload_source_file = forms.FileField(
        required=False,
        label=_("Upload / replace source file"),
        help_text=_(
            "Upload a CSV or GeoJSON file directly. "
            "The file path will be auto-injected into config['url']."
        ),
    )

    class Meta:
        model = DataSource
        fields = "__all__"
        widgets = {
            "config": forms.Textarea(
                attrs={"rows": 8, "style": "font-family:monospace;width:100%;"}
            ),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        uploaded = self.cleaned_data.get("upload_source_file")
        if uploaded:
            instance.source_file = uploaded
            if commit:
                instance.save()
                # Inject path AFTER save so the file is on disk and .path is valid.
                config = instance.config or {}
                config["url"] = instance.source_file.path
                instance.config = config
                instance.save(update_fields=["config"])
                return instance
        if commit:
            instance.save()
            self.save_m2m()
        return instance


# ---------------------------------------------------------------------------
# Bulk actions
# ---------------------------------------------------------------------------

@admin.action(description=_("Enable selected sources (show on map)"))
def enable_sources(modeladmin, request, queryset):
    updated = queryset.update(is_enabled=True)
    messages.success(request, _("%(n)d source(s) enabled.") % {"n": updated})


@admin.action(description=_("Disable selected sources (hide from map)"))
def disable_sources(modeladmin, request, queryset):
    updated = queryset.update(is_enabled=False)
    messages.success(request, _("%(n)d source(s) disabled.") % {"n": updated})


@admin.action(description=_("Sync selected sources now"))
def sync_sources(modeladmin, request, queryset):
    from datasets.views import _run_sync  # local import to avoid circular

    ok = err = 0
    for source in queryset:
        success, msg = _run_sync(source)
        if success:
            ok += 1
        else:
            err += 1
            logger.warning("Admin sync failed for source %s: %s", source.pk, msg)

    if ok:
        messages.success(
            request, _("%(n)d source(s) synced successfully.") % {"n": ok}
        )
    if err:
        messages.error(
            request,
            _("%(n)d source(s) failed to sync — see error_message field.") % {"n": err},
        )


# ---------------------------------------------------------------------------
# DataSource admin
# ---------------------------------------------------------------------------

@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    form = DataSourceAdminForm

    list_display = (
        "name",
        "workspace",
        "source_type",
        "layer_kind",
        "status_badge",
        "is_enabled",
        "record_count",
        "last_synced_at",
    )
    list_display_links = ("name",)
    list_editable = ("is_enabled",)
    list_filter = ("is_enabled", "status", "source_type", "layer_kind", "workspace")
    search_fields = ("name", "attribution", "source_url")
    ordering = ("workspace", "layer_kind", "name")
    readonly_fields = (
        "status",
        "last_synced_at",
        "record_count",
        "error_message",
        "created_at",
        "updated_at",
        "connector_schema_hint",
    )
    actions = [enable_sources, disable_sources, sync_sources]
    inlines = [NormalizedFeatureSetInline]

    fieldsets = (
        (None, {
            "fields": ("workspace", "name", "source_type", "layer_kind", "is_enabled"),
        }),
        (_("Configuration"), {
            "fields": (
                "config",
                "connector_schema_hint",
                "upload_source_file",
                "source_file",
            ),
            "description": _(
                "Edit the JSON config for this connector. "
                "The schema hint below lists every expected key."
            ),
        }),
        (_("Attribution"), {
            "fields": ("license", "attribution", "source_url"),
        }),
        (_("Sync status (read-only)"), {
            "fields": ("status", "last_synced_at", "record_count", "error_message"),
            "classes": ("collapse",),
        }),
        (_("Timestamps"), {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description=_("Status"), ordering="status")
    def status_badge(self, obj):
        colour_map = {
            "active":   "#059669",
            "error":    "#dc2626",
            "pending":  "#d97706",
            "unsynced": "#94a3b8",
        }
        colour = colour_map.get(obj.status, "#94a3b8")
        return format_html(
            '<span style="color:{c};font-weight:600;">● {l}</span>',
            c=colour,
            l=obj.get_status_display(),
        )

    @admin.display(description=_("Connector schema"))
    def connector_schema_hint(self, obj):
        """Render the selected connector's config_schema as an HTML table."""
        if not obj.source_type:
            return "—"
        try:
            from connectors.registry import get_connector
            connector = get_connector(obj.source_type)
        except KeyError:
            return format_html("<em>{}</em>", _("Unknown connector type"))

        schema = connector.config_schema or {}
        if not schema:
            return "—"

        header = format_html(
            "<p style='margin:0 0 6px;font-style:italic;color:#475569'>{}</p>",
            connector.description_de,
        )
        rows = format_html("".join([
            format_html(
                "<tr>"
                "<td style='padding:3px 8px;font-family:monospace'>{k}</td>"
                "<td style='padding:3px 8px;color:#475569'>{t}</td>"
                "<td style='padding:3px 8px;text-align:center'>{r}</td>"
                "<td style='padding:3px 8px;color:#64748b'>{l}</td>"
                "</tr>",
                k=key,
                t=defn.get("type", "string"),
                r="✓" if defn.get("required") else "",
                l=defn.get("label", ""),
            )
            for key, defn in schema.items()
        ]))
        table = format_html(
            "<table style='font-size:0.8rem;border-collapse:collapse;width:100%;border:1px solid #e2e8f0'>"
            "<thead><tr style='background:#f1f5f9;text-align:left'>"
            "<th style='padding:4px 8px'>Key</th>"
            "<th style='padding:4px 8px'>Type</th>"
            "<th style='padding:4px 8px'>Req</th>"
            "<th style='padding:4px 8px'>Description</th>"
            "</tr></thead><tbody>{}</tbody></table>",
            rows,
        )
        return format_html("{}{}", header, table)


# ---------------------------------------------------------------------------
# NormalizedFeatureSet admin — read-only reference
# ---------------------------------------------------------------------------

@admin.register(NormalizedFeatureSet)
class NormalizedFeatureSetAdmin(admin.ModelAdmin):
    list_display = ("source", "workspace", "layer_kind", "record_count", "synced_at")
    list_filter = ("workspace", "layer_kind")
    search_fields = ("source__name",)
    readonly_fields = (
        "source", "workspace", "layer_kind",
        "record_count", "schema_version", "synced_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
