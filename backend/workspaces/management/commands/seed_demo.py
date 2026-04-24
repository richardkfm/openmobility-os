"""Idempotent demo seed command.

Reads YAML files under `config/workspaces/` and creates workspaces, goals,
data sources, and optionally pre-baked measures. Running it twice does not
duplicate data — it updates existing records.
"""

from pathlib import Path

import yaml
from django.conf import settings
from django.contrib.gis.geos import Point, Polygon
from django.core.management.base import BaseCommand

from datasets.models import DataSource
from datasets.views import _run_sync
from goals.models import WorkspaceGoal
from measures.models import Measure, MeasureScore
from workspaces.models import Workspace


class Command(BaseCommand):
    help = "Seed demo workspaces from config/workspaces/*.yaml (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            default="",
            help="Comma-separated list of workspace slugs to seed (default: all)",
        )

    def handle(self, *args, **options):
        config_dir: Path = settings.REPO_ROOT / "config" / "workspaces"
        if not config_dir.exists():
            self.stdout.write(self.style.WARNING(f"No config dir at {config_dir}"))
            return

        only = {s.strip() for s in options["only"].split(",") if s.strip()}

        for path in sorted(config_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            slug = data["slug"]
            if only and slug not in only:
                continue
            self._seed_workspace(data)

    def _seed_workspace(self, data: dict):
        slug = data["slug"]
        self.stdout.write(f"→ Seeding workspace: {slug}")

        bounds = None
        center = None
        if "bounds" in data:
            b = data["bounds"]
            bounds = Polygon.from_bbox((b["west"], b["south"], b["east"], b["north"]))
        if "center" in data:
            c = data["center"]
            center = Point(c["lon"], c["lat"], srid=4326)
        elif bounds:
            b = data["bounds"]
            center = Point((b["west"] + b["east"]) / 2, (b["south"] + b["north"]) / 2, srid=4326)

        ws, _ = Workspace.objects.update_or_create(
            slug=slug,
            defaults={
                "name": data["name"],
                "kind": data.get("kind", Workspace.Kind.CITY),
                "country_code": data.get("country_code", "DE"),
                "region": data.get("region", ""),
                "language_code": data.get("language_code", "de"),
                "timezone": data.get("timezone", "Europe/Berlin"),
                "population": data.get("population"),
                "area_km2": data.get("area_km2"),
                "description_de": data.get("description_de", ""),
                "description_en": data.get("description_en", ""),
                "is_demo": data.get("is_demo", True),
                "is_active": True,
                "bounds": bounds,
                "center": center,
                "default_zoom": data.get("default_zoom", 12),
                "scoring_weights": data.get("scoring_weights", {}),
            },
        )

        for g in data.get("goals", []):
            WorkspaceGoal.objects.update_or_create(
                workspace=ws,
                code=g["code"],
                defaults={
                    "title_de": g.get("title_de", ""),
                    "title_en": g.get("title_en", ""),
                    "target_value": g.get("target_value"),
                    "current_value": g.get("current_value"),
                    "unit": g.get("unit", ""),
                    "deadline_year": g.get("deadline_year"),
                    "rationale_de": g.get("rationale_de", ""),
                    "rationale_en": g.get("rationale_en", ""),
                    "source_url": g.get("source_url", ""),
                },
            )

        for ds in data.get("data_sources", []):
            source, _ = DataSource.objects.update_or_create(
                workspace=ws,
                name=ds["name"],
                defaults={
                    "source_type": ds["source_type"],
                    "layer_kind": ds.get("layer_kind", DataSource.LayerKind.CUSTOM),
                    "config": ds.get("config", {}),
                    "license": ds.get("license", ""),
                    "attribution": ds.get("attribution", ""),
                    "source_url": ds.get("source_url", ""),
                },
            )
            # Auto-sync offline (manual) sources so their data is immediately
            # available on the map without a manual sync step.
            if source.source_type == DataSource.SourceType.MANUAL:
                success, msg = _run_sync(source)
                style = self.style.SUCCESS if success else self.style.WARNING
                self.stdout.write(style(f"     sync {source.name}: {msg}"))

        for m in data.get("measures", []):
            measure, _ = Measure.objects.update_or_create(
                workspace=ws,
                slug=m["slug"],
                defaults={
                    "category": m.get("category", Measure.Category.OTHER),
                    "title_de": m.get("title_de", ""),
                    "title_en": m.get("title_en", ""),
                    "summary_de": m.get("summary_de", ""),
                    "summary_en": m.get("summary_en", ""),
                    "description_de_md": m.get("description_de_md", ""),
                    "description_en_md": m.get("description_en_md", ""),
                    "effort_level": m.get("effort_level", Measure.EffortLevel.MEDIUM),
                    "status": m.get("status", Measure.Status.PROPOSED),
                    "is_auto_generated": False,
                    "evidence": m.get("evidence", {}),
                },
            )
            for dim, payload in (m.get("scores") or {}).items():
                MeasureScore.objects.update_or_create(
                    measure=measure,
                    dimension=dim,
                    defaults={
                        "raw_value": payload["raw"],
                        "display_value": payload.get("display", round(payload["raw"] * 100, 1)),
                        "confidence": payload.get("confidence", "medium"),
                        "rationale_de": payload.get("rationale_de", ""),
                        "rationale_en": payload.get("rationale_en", ""),
                        "sources": payload.get("sources", []),
                    },
                )

        self.stdout.write(self.style.SUCCESS(f"   ✓ {slug} done."))
