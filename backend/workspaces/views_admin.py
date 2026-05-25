"""Admin dashboard views — workspace health, comparison, export."""

from django.shortcuts import render
from django.views.generic import TemplateView

from core.decorators import admin_required
from core.utils import get_active_workspace
from datasets.models import DataSource
from measures.models import Measure

from .models import Workspace, ConnectorAuditLog


class HealthDashboardView(TemplateView):
    """Dashboard showing connector status, data freshness, and recent sync history."""

    template_name = "workspaces/health_dashboard.html"

    @admin_required
    def get(self, request, workspace_slug):
        workspace = get_active_workspace(workspace_slug)
        sources = workspace.data_sources.all().order_by(
            "-last_synced_at", "name"
        )

        # Summary stats
        total_sources = sources.count()
        active_count = sources.filter(status=DataSource.Status.ACTIVE).count()
        error_count = sources.filter(status=DataSource.Status.ERROR).count()
        total_features = sum(
            source.record_count or 0 for source in sources
        )

        # Recent audit log (last 20 entries workspace-wide)
        recent_logs = ConnectorAuditLog.objects.filter(
            workspace=workspace
        ).select_related("datasource")[:20]

        # Data freshness heatmap — count sources by LayerKind
        layer_kinds = DataSource.LayerKind.choices
        layer_freshness = {}
        for layer_value, layer_label in layer_kinds:
            sources_for_kind = sources.filter(layer_kind=layer_value)
            layer_freshness[layer_label] = {
                "count": sources_for_kind.count(),
                "sources": list(sources_for_kind),
            }

        context = {
            "workspace": workspace,
            "sources": sources,
            "total_sources": total_sources,
            "active_count": active_count,
            "error_count": error_count,
            "total_features": total_features,
            "recent_logs": recent_logs,
            "layer_freshness": layer_freshness,
            "status_choices": dict(DataSource.Status.choices),
            "page_title": f"Health Dashboard — {workspace.name}",
        }
        return render(request, self.template_name, context)


class WorkspaceComparisonView(TemplateView):
    """Side-by-side comparison of two workspaces."""

    template_name = "workspaces/workspace_comparison.html"

    @admin_required
    def get(self, request):
        workspace_a_id = request.GET.get("workspace_a")
        workspace_b_id = request.GET.get("workspace_b")
        workspaces = Workspace.objects.filter(is_active=True).order_by("name")

        workspace_a = None
        workspace_b = None
        comparison_data = None

        if workspace_a_id and workspace_b_id:
            try:
                workspace_a = Workspace.objects.get(pk=workspace_a_id)
                workspace_b = Workspace.objects.get(pk=workspace_b_id)
                comparison_data = self._build_comparison(workspace_a, workspace_b)
            except Workspace.DoesNotExist:
                pass

        context = {
            "workspaces": workspaces,
            "workspace_a": workspace_a,
            "workspace_b": workspace_b,
            "comparison_data": comparison_data,
            "page_title": "Workspace Comparison",
        }
        return render(request, self.template_name, context)

    @staticmethod
    def _build_comparison(ws_a: Workspace, ws_b: Workspace) -> dict:
        """Build a comparison data structure."""
        def count_by_layer(workspace):
            return {
                layer_value: workspace.data_sources.filter(
                    layer_kind=layer_value
                ).count()
                for layer_value, _ in DataSource.LayerKind.choices
            }

        def count_goals(workspace):
            return workspace.workspace_goals.count() if hasattr(
                workspace, "workspace_goals"
            ) else 0

        return {
            "basic": {
                "name_a": ws_a.name,
                "name_b": ws_b.name,
                "bounds_a": str(ws_a.bounds) if ws_a.bounds else "Not set",
                "bounds_b": str(ws_b.bounds) if ws_b.bounds else "Not set",
                "districts_a": ws_a.districts.count(),
                "districts_b": ws_b.districts.count(),
            },
            "data_sources": {
                "a": count_by_layer(ws_a),
                "b": count_by_layer(ws_b),
            },
            "goals": {
                "a": count_goals(ws_a),
                "b": count_goals(ws_b),
            },
            "measures": {
                "a": Measure.objects.filter(workspace=ws_a).count(),
                "b": Measure.objects.filter(workspace=ws_b).count(),
            },
        }
