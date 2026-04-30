"""Seed Unfallatlas (Destatis) accident data into a workspace.

Replaces the ~36-row illustrative demo accident layer that ships with new
workspaces by the actual police-recorded accident records published annually
by the German Federal Statistical Office (Statistisches Bundesamt).

The command is **city-agnostic in spirit but geographically scoped to
Germany** — Unfallatlas only covers Germany. For non-German workspaces, use
the generic `accident_csv` connector or the global `bikemaps` connector.

USAGE
    python manage.py seed_unfallatlas --workspace leipzig --years 2021-2024
    python manage.py seed_unfallatlas --workspace leipzig --years 2023,2024
    python manage.py seed_unfallatlas --workspace leipzig --years 2024 \\
        --url-pattern "https://example.org/unfallatlas/{year}.csv"

The command:

  1. Loads year→URL mappings from `config/unfallatlas.yaml` (or, if present,
     the per-workspace override at `config/unfallatlas/<slug>.yaml`).
     `--url-pattern` overrides both — useful for one-off imports.
  2. For each requested year it ensures a `DataSource` exists with
     `source_type=unfallat` and `layer_kind=accidents`, configured to clip
     to the workspace bounding box.
  3. Removes any prior `manual` demo accident layer for the workspace
     (only when --replace-demo is set, the default).
  4. Runs `_run_sync` so the normalized feature set is available on the map
     immediately.

The command is idempotent: running it twice updates the same DataSource
rows and does not duplicate records.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datasets.models import DataSource
from datasets.views import _run_sync
from workspaces.models import Workspace

CONFIG_FILENAME = "unfallatlas.yaml"
PER_WORKSPACE_DIR = "unfallatlas"
SOURCE_TYPE = "unfallat"


class Command(BaseCommand):
    help = (
        "Bootstrap a workspace with real Destatis Unfallatlas accident data "
        "(German Federal Statistical Office) clipped to the workspace bounds. "
        "Replaces the illustrative demo accident layer."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace",
            required=True,
            help="Workspace slug to seed (must already exist).",
        )
        parser.add_argument(
            "--years",
            required=True,
            help=(
                "Years to import. Comma-separated list (2021,2022) or range "
                "(2021-2024)."
            ),
        )
        parser.add_argument(
            "--url-pattern",
            default="",
            help=(
                "Override the YAML config: a URL pattern with {year} "
                "placeholder, e.g. 'https://example.org/unfallatlas/{year}.csv'."
            ),
        )
        parser.add_argument(
            "--encoding",
            default="",
            help="Override default encoding (utf-8 or latin-1). Optional.",
        )
        parser.add_argument(
            "--replace-demo",
            action="store_true",
            default=True,
            help=(
                "Disable any pre-existing `manual` demo accident sources "
                "in the workspace before seeding (default: yes)."
            ),
        )
        parser.add_argument(
            "--keep-demo",
            dest="replace_demo",
            action="store_false",
            help="Keep any existing manual demo accident layers alongside the import.",
        )
        parser.add_argument(
            "--no-sync",
            action="store_true",
            help="Create / update the DataSource rows but skip the network sync.",
        )

    def handle(self, *args, **options):
        slug = options["workspace"]
        try:
            workspace = Workspace.objects.get(slug=slug)
        except Workspace.DoesNotExist as exc:
            raise CommandError(
                f"Workspace '{slug}' not found. Run `seed_demo` first or "
                f"create the workspace via the admin UI."
            ) from exc

        if workspace.bounds is None:
            raise CommandError(
                f"Workspace '{slug}' has no bounding box set. The Unfallatlas "
                f"national CSV is too large to import unclipped — set bounds "
                f"in the workspace YAML (or admin) before running this command."
            )

        years = _parse_years(options["years"])
        if not years:
            raise CommandError("--years must list at least one calendar year.")

        sources_by_year, default_encoding = _load_year_sources(
            workspace_slug=slug,
            url_pattern=options["url_pattern"],
            encoding_override=options["encoding"],
        )

        missing = [y for y in years if y not in sources_by_year]
        if missing:
            raise CommandError(
                "No URL configured for years: "
                f"{missing}. Either add them to config/unfallatlas.yaml "
                f"(or config/unfallatlas/{slug}.yaml), or pass --url-pattern."
            )

        if options["replace_demo"]:
            removed = _disable_demo_accidents(workspace)
            if removed:
                self.stdout.write(
                    self.style.WARNING(
                        f"   removed {removed} pre-existing demo accident source(s)"
                    )
                )

        for year in years:
            spec = sources_by_year[year]
            url = spec["url"]
            encoding = spec.get("encoding") or default_encoding
            self._seed_year(workspace, year, url, encoding, run_sync=not options["no_sync"])

        self.stdout.write(self.style.SUCCESS(f"Done. {len(years)} year(s) processed."))

    def _seed_year(self, workspace, year, url, encoding, run_sync):
        name = f"Unfallatlas {year}"
        config = {
            "url": url,
            "encoding": encoding,
            "clip_to_workspace": True,
        }
        source, created = DataSource.objects.update_or_create(
            workspace=workspace,
            name=name,
            defaults={
                "source_type": SOURCE_TYPE,
                "layer_kind": DataSource.LayerKind.ACCIDENTS,
                "config": config,
                "license": "dl-de/by-2-0",
                "attribution": "© Statistische Ämter des Bundes und der Länder",
                "source_url": "https://unfallatlas.statistikportal.de/",
            },
        )
        verb = "created" if created else "updated"
        self.stdout.write(f"→ {verb} data source: {name}")

        if not run_sync:
            return

        success, message = _run_sync(source)
        style = self.style.SUCCESS if success else self.style.ERROR
        self.stdout.write(style(f"   sync {name}: {message}"))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _parse_years(raw):
    """Accepts '2021,2023', '2021-2024', or '2024'."""
    raw = (raw or "").strip()
    if not raw:
        return []
    if "-" in raw and "," not in raw:
        start_s, _, end_s = raw.partition("-")
        try:
            start, end = int(start_s), int(end_s)
        except ValueError:
            return []
        if start > end:
            start, end = end, start
        return list(range(start, end + 1))
    out: list[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(int(chunk))
        except ValueError:
            return []
    return sorted(set(out))


def _load_year_sources(workspace_slug, url_pattern, encoding_override):
    """Resolve the year→source map from CLI args or YAML config files."""
    if url_pattern:
        if "{year}" not in url_pattern:
            raise CommandError("--url-pattern must contain the literal '{year}' placeholder.")
        # Defer expansion to per-year iteration; we still want a uniform shape.
        return _PatternMap(url_pattern, encoding_override or "utf-8"), encoding_override or "utf-8"

    config_dir: Path = settings.REPO_ROOT / "config"
    per_ws = config_dir / PER_WORKSPACE_DIR / f"{workspace_slug}.yaml"
    fallback = config_dir / CONFIG_FILENAME

    paths = [p for p in (per_ws, fallback) if p.exists()]
    if not paths:
        raise CommandError(
            f"No URL config found at {per_ws} or {fallback}. "
            "Either create one of these files, or pass --url-pattern."
        )

    data = yaml.safe_load(paths[0].read_text()) or {}
    default_encoding = encoding_override or data.get("default_encoding") or "utf-8"
    raw_sources = data.get("sources") or {}

    out: dict[int, dict] = {}
    for year, spec in raw_sources.items():
        try:
            year_int = int(year)
        except (TypeError, ValueError):
            continue
        if isinstance(spec, str):
            spec = {"url": spec}
        if not spec or not spec.get("url"):
            continue
        out[year_int] = {
            "url": spec["url"],
            "encoding": spec.get("encoding") or default_encoding,
        }
    return out, default_encoding


class _PatternMap:
    """Lazy year→source resolver for the --url-pattern path.

    Behaves like a dict but expands the URL on access so any year passes
    the `missing-years` check above.
    """

    def __init__(self, pattern, encoding):
        self._pattern = pattern
        self._encoding = encoding

    def __contains__(self, year):
        return isinstance(year, int)

    def __getitem__(self, year):
        return {"url": self._pattern.format(year=year), "encoding": self._encoding}


def _disable_demo_accidents(workspace):
    """Delete `manual` accident sources flagged as demo on the workspace.

    The shipped demo workspaces use `source_type=manual` for the illustrative
    accident layer — that's what we want to replace with real data. Other
    `manual` accident sources (e.g. operator-curated supplements) might be
    intended; we play it safe by only removing sources whose name starts
    with the German/English demo prefix or whose attribution explicitly
    mentions illustrative data.
    """
    qs = workspace.data_sources.filter(
        source_type=DataSource.SourceType.MANUAL,
        layer_kind=DataSource.LayerKind.ACCIDENTS,
    )
    count = 0
    for source in qs:
        name_lower = (source.name or "").lower()
        attribution_lower = (source.attribution or "").lower()
        is_demo = (
            name_lower.startswith("beispiel")
            or name_lower.startswith("demo")
            or name_lower.startswith("example")
            or "illustrative" in attribution_lower
            or "example data" in attribution_lower
        )
        if is_demo:
            source.delete()
            count += 1
    return count
