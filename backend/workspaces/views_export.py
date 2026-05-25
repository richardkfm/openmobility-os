"""Export views for measures, data sources, and goals."""

import csv
import io
import json
from datetime import datetime

from django.http import HttpResponse
from django.views.generic import View

from core.decorators import admin_required
from core.utils import get_active_workspace
from measures.models import Measure

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.units import inch
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


class ExportView(View):
    """Export measures, data sources, or goals as CSV, JSON, or PDF."""

    @admin_required
    def get(self, request, workspace_slug):
        workspace = get_active_workspace(workspace_slug)
        what = request.GET.get("what", "measures")  # measures, datasources, goals
        format_ = request.GET.get("format", "json")  # csv, json, pdf

        if what == "measures":
            return self._export_measures(workspace, format_)
        elif what == "datasources":
            return self._export_datasources(workspace, format_)
        elif what == "goals":
            return self._export_goals(workspace, format_)
        else:
            return HttpResponse("Invalid 'what' parameter", status=400)

    def _export_measures(self, workspace, format_):
        """Export measures."""
        measures = Measure.objects.filter(workspace=workspace)

        if format_ == "csv":
            return self._measures_to_csv(measures)
        elif format_ == "json":
            return self._measures_to_json(measures)
        elif format_ == "pdf":
            return self._measures_to_pdf(measures, workspace)
        else:
            return HttpResponse("Invalid format", status=400)

    def _export_datasources(self, workspace, format_):
        """Export data sources."""
        sources = workspace.data_sources.all()

        if format_ == "csv":
            return self._datasources_to_csv(sources)
        elif format_ == "json":
            return self._datasources_to_json(sources)
        elif format_ == "pdf":
            return self._datasources_to_pdf(sources, workspace)
        else:
            return HttpResponse("Invalid format", status=400)

    def _export_goals(self, workspace, format_):
        """Export goals."""
        goals = workspace.workspace_goals.all()

        if format_ == "csv":
            return self._goals_to_csv(goals)
        elif format_ == "json":
            return self._goals_to_json(goals)
        elif format_ == "pdf":
            return self._goals_to_pdf(goals, workspace)
        else:
            return HttpResponse("Invalid format", status=400)

    # Measures export
    def _measures_to_csv(self, measures):
        """Serialize measures to CSV."""
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "Code", "Name (DE)", "Name (EN)", "Category", "Benefit",
            "Cost (EUR)", "CO2 Avoided (tons)", "Mean Score", "Rationale (DE)", "Rationale (EN)"
        ])

        for measure in measures:
            score = measure.measure_scores.first() if hasattr(measure, "measure_scores") else None
            writer.writerow([
                measure.slug,
                measure.name_de,
                measure.name_en,
                measure.get_category_display(),
                measure.benefit or "",
                measure.cost_eur or "",
                measure.co2_avoided_tons or "",
                score.mean_score if score else "",
                measure.rationale_de or "",
                measure.rationale_en or "",
            ])

        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename=measures.csv"
        return response

    def _measures_to_json(self, measures):
        """Serialize measures to JSON."""
        data = []
        for measure in measures:
            score = measure.measure_scores.first() if hasattr(measure, "measure_scores") else None
            data.append({
                "code": measure.slug,
                "name_de": measure.name_de,
                "name_en": measure.name_en,
                "category": measure.get_category_display(),
                "benefit": measure.benefit,
                "cost_eur": measure.cost_eur,
                "co2_avoided_tons": measure.co2_avoided_tons,
                "mean_score": score.mean_score if score else None,
                "rationale_de": measure.rationale_de,
                "rationale_en": measure.rationale_en,
            })

        response = HttpResponse(
            json.dumps(data, indent=2, ensure_ascii=False),
            content_type="application/json; charset=utf-8"
        )
        response["Content-Disposition"] = "attachment; filename=measures.json"
        return response

    def _measures_to_pdf(self, measures, workspace):
        """Serialize measures to PDF."""
        if not HAS_REPORTLAB:
            return HttpResponse("ReportLab not installed", status=500)

        output = io.BytesIO()
        doc = SimpleDocTemplate(
            output,
            pagesize=letter,
            topMargin=0.5 * inch,
            bottomMargin=0.5 * inch,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
        )

        styles = getSampleStyleSheet()
        story = []

        # Title
        from reportlab.platypus import Paragraph
        title = Paragraph(f"{workspace.name} — Measures Report", styles["Heading1"])
        story.append(title)
        timestamp = Paragraph(
            f"<font size=8>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</font>",
            styles["Normal"]
        )
        story.append(timestamp)
        story.append(Spacer(1, 0.3 * inch))

        # Measures table
        table_data = [
            ["Code", "Name", "Benefit", "Mean Score"]
        ]
        for measure in measures:
            score = measure.measure_scores.first() if hasattr(measure, "measure_scores") else None
            table_data.append([
                measure.slug,
                measure.name_en,
                measure.benefit or "",
                f"{score.mean_score:.2f}" if score else "—"
            ])

        table = Table(table_data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
        ]))
        story.append(table)

        doc.build(story)
        output.seek(0)

        response = HttpResponse(output.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = "attachment; filename=measures.pdf"
        return response

    # DataSources export
    def _datasources_to_csv(self, sources):
        """Serialize data sources to CSV."""
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "Name", "Type", "Layer Kind", "Status", "Last Sync", "Record Count"
        ])

        for source in sources:
            writer.writerow([
                source.name,
                source.get_source_type_display(),
                source.get_layer_kind_display(),
                source.get_status_display(),
                source.last_synced_at.isoformat() if source.last_synced_at else "",
                source.record_count or "",
            ])

        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename=datasources.csv"
        return response

    def _datasources_to_json(self, sources):
        """Serialize data sources to JSON."""
        data = []
        for source in sources:
            data.append({
                "name": source.name,
                "type": source.source_type,
                "layer_kind": source.layer_kind,
                "status": source.status,
                "last_synced_at": source.last_synced_at.isoformat() if source.last_synced_at else None,
                "record_count": source.record_count,
                "source_url": source.source_url,
            })

        response = HttpResponse(
            json.dumps(data, indent=2, ensure_ascii=False),
            content_type="application/json; charset=utf-8"
        )
        response["Content-Disposition"] = "attachment; filename=datasources.json"
        return response

    def _datasources_to_pdf(self, sources, workspace):
        """Serialize data sources to PDF."""
        if not HAS_REPORTLAB:
            return HttpResponse("ReportLab not installed", status=500)

        output = io.BytesIO()
        doc = SimpleDocTemplate(
            output,
            pagesize=letter,
            topMargin=0.5 * inch,
            bottomMargin=0.5 * inch,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
        )

        styles = getSampleStyleSheet()
        story = []

        # Title
        title = Paragraph(f"{workspace.name} — Data Sources Report", styles["Heading1"])
        story.append(title)
        timestamp = Paragraph(
            f"<font size=8>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</font>",
            styles["Normal"]
        )
        story.append(timestamp)
        story.append(Spacer(1, 0.3 * inch))

        # Sources table
        table_data = [
            ["Name", "Type", "Status", "Records"]
        ]
        for source in sources:
            table_data.append([
                source.name,
                source.get_source_type_display(),
                source.get_status_display(),
                str(source.record_count) if source.record_count else "—"
            ])

        table = Table(table_data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
        ]))
        story.append(table)

        doc.build(story)
        output.seek(0)

        response = HttpResponse(output.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = "attachment; filename=datasources.pdf"
        return response

    # Goals export
    def _goals_to_csv(self, goals):
        """Serialize goals to CSV."""
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "Code", "Name (DE)", "Name (EN)", "Current Value", "Target Value", "Unit", "Deadline Year"
        ])

        for goal in goals:
            writer.writerow([
                goal.code,
                goal.name_de,
                goal.name_en,
                goal.current_value or "",
                goal.target_value or "",
                goal.unit or "",
                goal.deadline_year or "",
            ])

        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename=goals.csv"
        return response

    def _goals_to_json(self, goals):
        """Serialize goals to JSON."""
        data = []
        for goal in goals:
            data.append({
                "code": goal.code,
                "name_de": goal.name_de,
                "name_en": goal.name_en,
                "current_value": goal.current_value,
                "target_value": goal.target_value,
                "unit": goal.unit,
                "deadline_year": goal.deadline_year,
                "rationale_de": goal.rationale_de,
            })

        response = HttpResponse(
            json.dumps(data, indent=2, ensure_ascii=False),
            content_type="application/json; charset=utf-8"
        )
        response["Content-Disposition"] = "attachment; filename=goals.json"
        return response

    def _goals_to_pdf(self, goals, workspace):
        """Serialize goals to PDF."""
        if not HAS_REPORTLAB:
            return HttpResponse("ReportLab not installed", status=500)

        output = io.BytesIO()
        doc = SimpleDocTemplate(
            output,
            pagesize=letter,
            topMargin=0.5 * inch,
            bottomMargin=0.5 * inch,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
        )

        styles = getSampleStyleSheet()
        story = []

        # Title
        title = Paragraph(f"{workspace.name} — Goals Report", styles["Heading1"])
        story.append(title)
        timestamp = Paragraph(
            f"<font size=8>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</font>",
            styles["Normal"]
        )
        story.append(timestamp)
        story.append(Spacer(1, 0.3 * inch))

        # Goals table
        table_data = [
            ["Code", "Name", "Current", "Target", "Unit"]
        ]
        for goal in goals:
            table_data.append([
                goal.code,
                goal.name_en,
                str(goal.current_value) if goal.current_value else "—",
                str(goal.target_value) if goal.target_value else "—",
                goal.unit or "—"
            ])

        table = Table(table_data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
        ]))
        story.append(table)

        doc.build(story)
        output.seek(0)

        response = HttpResponse(output.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = "attachment; filename=goals.pdf"
        return response
