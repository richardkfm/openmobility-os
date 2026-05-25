"""Management command — browse the Mobilithek DCAT-AP catalog.

Usage examples::

    # List the first 20 datasets in the catalog
    python manage.py browse_mobilithek

    # Search by keyword and show distribution URLs
    python manage.py browse_mobilithek --keyword GTFS --formats

    # Search for bike-share feeds
    python manage.py browse_mobilithek -k "Leihrad" -n 5 --formats

    # Show only datasets that have a directly parseable distribution
    python manage.py browse_mobilithek -k "Leipzig" --supported-only

Results show the dataset UID, title, publisher, and optionally the list of
distributions. The UID is the value to paste into a Mobilithek DataSource
config as ``dataset_id`` for attribution, while the distribution URL goes
into ``distribution_url``.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from connectors.mobilithek_catalog import (
    CATALOG_URL,
    CatalogDataset,
    browse_catalog,
)

# Connector format_hint values that can be directly parsed
_SUPPORTED = {"gtfs", "geojson", "json", "csv"}


class Command(BaseCommand):
    help = (
        "Browse the Mobilithek DCAT-AP metadata catalog. "
        "Search for datasets by keyword and discover their distribution URLs."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--keyword",
            "-k",
            metavar="KEYWORD",
            default=None,
            help=(
                "Filter by keyword (case-insensitive match against title, "
                "description, and keyword tags). Omit to list all datasets."
            ),
        )
        parser.add_argument(
            "--limit",
            "-n",
            type=int,
            default=20,
            metavar="N",
            help="Maximum number of results to display (default: 20).",
        )
        parser.add_argument(
            "--formats",
            "-f",
            action="store_true",
            default=False,
            help="Show all available distributions with their format hints and URLs.",
        )
        parser.add_argument(
            "--supported-only",
            action="store_true",
            default=False,
            help=(
                "Only show datasets that have at least one distribution with a "
                "format directly supported by MobilithekConnector "
                f"({', '.join(sorted(_SUPPORTED))})."
            ),
        )
        parser.add_argument(
            "--catalog-url",
            default=CATALOG_URL,
            metavar="URL",
            help=f"Override the Mobilithek DCAT-AP feed URL (default: {CATALOG_URL}).",
        )

    def handle(self, *args, **options):
        keyword: str | None = options["keyword"]
        limit: int = options["limit"]
        show_formats: bool = options["formats"]
        supported_only: bool = options["supported_only"]
        catalog_url: str = options["catalog_url"]

        self.stdout.write("Fetching Mobilithek DCAT-AP catalog…")
        try:
            datasets = browse_catalog(keyword=keyword, catalog_url=catalog_url)
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Failed to fetch catalog: {exc}") from exc

        if supported_only:
            datasets = [d for d in datasets if d.has_supported_format()]

        total = len(datasets)
        if total == 0:
            label = f" matching {keyword!r}" if keyword else ""
            self.stdout.write(
                self.style.WARNING(f"No datasets found{label}.")
            )
            return

        shown = min(total, limit)
        kw_label = f" matching {keyword!r}" if keyword else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"Found {total} dataset(s){kw_label}. "
                f"Showing {shown}."
            )
        )
        self.stdout.write("")

        for ds in datasets[:limit]:
            self._print_dataset(ds, show_formats=show_formats)

        if total > limit:
            self.stdout.write(
                self.style.WARNING(
                    f"… and {total - limit} more. Use --limit to see more results."
                )
            )

    def _print_dataset(self, ds: CatalogDataset, *, show_formats: bool) -> None:
        """Pretty-print a single dataset entry."""
        # Title line
        self.stdout.write(self.style.HTTP_INFO(f"  {ds.title or '(no title)'}"))

        # UID
        self.stdout.write(f"    UID:  {ds.uid}")

        # Publisher
        if ds.publisher:
            self.stdout.write(f"    By:   {ds.publisher}")

        # Keywords (compact)
        if ds.keywords:
            self.stdout.write(f"    Tags: {', '.join(ds.keywords[:8])}")

        # Description — first sentence only to keep output readable
        if ds.description:
            first_sentence = ds.description.split(". ")[0].strip()
            if len(first_sentence) > 120:
                first_sentence = first_sentence[:117] + "…"
            self.stdout.write(f"    Desc: {first_sentence}")

        # Distributions
        if show_formats:
            if ds.distributions:
                for dist in ds.distributions:
                    supported = dist.format_hint in _SUPPORTED
                    marker = self.style.SUCCESS("✓") if supported else "·"
                    fmt_str = dist.format_hint or dist.format_label or "unknown"
                    self.stdout.write(
                        f"      {marker} [{fmt_str}] {dist.url}"
                    )
            else:
                self.stdout.write("      (no distributions)")
        else:
            # Just show the best distribution URL as a quick hint
            best = ds.best_distribution()
            if best:
                fmt_str = best.format_hint or best.format_label or "?"
                self.stdout.write(f"    Best: [{fmt_str}] {best.url}")

        self.stdout.write("")
