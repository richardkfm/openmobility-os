"""Management command — import ADFC / MiD KPI data into workspace goals.

Usage examples::

    # Import ADFC Fahrradklimatest grades from a local file
    python manage.py import_kpis adfc --file results.csv --workspace leipzig

    # Import MiD modal-split data from a URL
    python manage.py import_kpis mid --url https://example.com/mid-modal-split.csv

    # Dry run — show what would be written without touching the database
    python manage.py import_kpis adfc --file results.csv --dry-run

    # Custom column names for a differently formatted CSV
    python manage.py import_kpis mid --file mid.csv --col city=Stadt --col cycling=Fahrrad

The command matches CSV rows to workspaces by city name (case-insensitive,
accent-folded). Only workspaces that already exist in the database are
updated — unmatched rows are listed so operators know which cities were
skipped.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from connectors.kpi_importers import (
    KPIRecord,
    _normalize_city,
    parse_adfc,
    parse_mid,
)
from goals.models import WorkspaceGoal
from workspaces.models import Workspace


class Command(BaseCommand):
    help = (
        "Import KPI data (ADFC Fahrradklimatest or MiD modal-split) into "
        "workspace goals. Matches CSV rows to workspaces by city name."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "source",
            choices=["adfc", "mid"],
            help="Data source to import: 'adfc' (Fahrradklimatest) or 'mid' (modal-split).",
        )
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--url",
            metavar="URL",
            help="URL to fetch the CSV from.",
        )
        group.add_argument(
            "--file",
            metavar="PATH",
            help="Local CSV file path.",
        )
        parser.add_argument(
            "--workspace",
            "-w",
            metavar="SLUG",
            help="Limit import to a single workspace slug.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Show what would be updated without writing to the database.",
        )
        parser.add_argument(
            "--delimiter",
            default=";",
            help="CSV delimiter (default: ';').",
        )
        parser.add_argument(
            "--encoding",
            default="utf-8",
            help="CSV file encoding (default: utf-8).",
        )
        parser.add_argument(
            "--col",
            action="append",
            default=[],
            metavar="KEY=NAME",
            help=(
                "Override a column name. Use key=value pairs. "
                "ADFC keys: city, grade, plus any subcategory. "
                "MiD keys: city, walking, cycling, transit, car. "
                "Example: --col city=Stadt --col cycling=Fahrrad"
            ),
        )
        parser.add_argument(
            "--source-url",
            default="",
            metavar="URL",
            help="Attribution source_url written into each WorkspaceGoal.",
        )

    def handle(self, *args, **options):
        source = options["source"]
        dry_run = options["dry_run"]
        ws_slug = options.get("workspace")

        # Parse column overrides
        col_overrides = {}
        for pair in options["col"]:
            if "=" not in pair:
                raise CommandError(f"Invalid --col format: {pair!r} (expected KEY=NAME)")
            key, name = pair.split("=", 1)
            col_overrides[key.strip()] = name.strip()

        # Read CSV bytes
        csv_bytes = self._read_csv(options)

        # Parse according to source type
        records = self._parse(source, csv_bytes, options, col_overrides)
        if not records:
            self.stdout.write(self.style.WARNING("No records parsed from CSV."))
            return

        self.stdout.write(f"Parsed {len(records)} KPI record(s) from CSV.")

        # Build workspace lookup
        ws_qs = Workspace.objects.all()
        if ws_slug:
            ws_qs = ws_qs.filter(slug=ws_slug)

        ws_map: dict[str, Workspace] = {}
        for ws in ws_qs:
            ws_map[_normalize_city(ws.name)] = ws
            ws_map[_normalize_city(ws.slug)] = ws

        # Match records to workspaces and upsert goals
        matched = 0
        skipped_cities: set[str] = set()

        for rec in records:
            ws = ws_map.get(rec.city_normalized)
            if ws is None:
                skipped_cities.add(rec.city_name)
                continue

            if dry_run:
                self.stdout.write(
                    f"  [DRY RUN] {ws.slug}/{rec.goal_code} ← {rec.value} {rec.unit}"
                )
            else:
                WorkspaceGoal.objects.update_or_create(
                    workspace=ws,
                    code=rec.goal_code,
                    defaults={
                        "title_de": rec.title_de,
                        "title_en": rec.title_en,
                        "current_value": rec.value,
                        "unit": rec.unit,
                        "rationale_de": f"Quelle: {rec.source_label}",
                        "rationale_en": f"Source: {rec.source_label}",
                        "source_url": options["source_url"] or rec.source_url,
                    },
                )
            matched += 1

        verb = "Would update" if dry_run else "Updated"
        self.stdout.write(
            self.style.SUCCESS(f"{verb} {matched} goal(s) across {len(ws_map)} workspace(s).")
        )

        if skipped_cities:
            self.stdout.write(
                self.style.WARNING(
                    f"Skipped {len(skipped_cities)} unmatched city name(s): "
                    + ", ".join(sorted(skipped_cities)[:20])
                )
            )

    def _read_csv(self, options) -> bytes:
        file_path = options.get("file")
        url = options.get("url")
        if file_path:
            try:
                with open(file_path, "rb") as f:
                    return f.read()
            except FileNotFoundError as exc:
                raise CommandError(f"File not found: {file_path}") from exc
        elif url:
            return None  # parsers will fetch from URL
        else:
            raise CommandError("Either --url or --file is required.")

    def _parse(
        self, source: str, csv_bytes: bytes | None, options: dict, col_overrides: dict
    ) -> list[KPIRecord]:
        common = {
            "delimiter": options["delimiter"],
            "encoding": options["encoding"],
        }
        if csv_bytes is not None:
            common["_csv_bytes"] = csv_bytes
        else:
            common["url"] = options["url"]

        if source == "adfc":
            return parse_adfc(
                city_col=col_overrides.get("city", "Ort"),
                grade_col=col_overrides.get("grade", "Gesamtbewertung"),
                subcategory_cols=[
                    v for k, v in col_overrides.items()
                    if k not in ("city", "grade")
                ],
                **common,
            )
        elif source == "mid":
            return parse_mid(
                city_col=col_overrides.get("city", "Raumeinheit"),
                walking_col=col_overrides.get("walking", "Fuß"),
                cycling_col=col_overrides.get("cycling", "Rad"),
                transit_col=col_overrides.get("transit", "ÖV"),
                car_col=col_overrides.get("car", "MIV"),
                **common,
            )
        raise CommandError(f"Unknown source: {source}")
