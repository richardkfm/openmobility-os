"""Record a point-in-time snapshot of every shared-mobility source.

GBFS feeds expose only the live state, so this command is meant to run on a
schedule (cron, a Docker sidecar, a systemd timer — anything; no SaaS
required, keeping with the self-hosting-first principle). Each run fetches the
current vehicles/stations from every enabled shared-mobility source, bins them
into a fixed spatial grid, and stores one :class:`MobilitySnapshot` per source.
Aggregated over time these snapshots power the availability / gap analysis
served at ``/api/v1/workspaces/<slug>/shared-mobility-gaps/``.

Typical cron entry (every 15 minutes):

    */15 * * * * python manage.py collect_mobility_snapshots --prune-days 35

The command is safe to run as often as you like; each run simply appends one
snapshot per source. ``--prune-days`` keeps the table bounded.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from datasets.mobility_gaps import DEFAULT_CELL_SIZE_M
from datasets.models import MobilitySnapshot
from datasets.snapshots import SHARED_LAYER_KINDS, capture_snapshot
from workspaces.models import Workspace


class Command(BaseCommand):
    help = (
        "Fetch every enabled shared-mobility source and store a time-stamped "
        "grid snapshot for temporal availability / gap analysis."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace",
            default="",
            help="Limit to a single workspace slug (default: all).",
        )
        parser.add_argument(
            "--cell-size",
            type=int,
            default=DEFAULT_CELL_SIZE_M,
            help=f"Analysis grid cell size in metres (default {DEFAULT_CELL_SIZE_M}).",
        )
        parser.add_argument(
            "--prune-days",
            type=int,
            default=0,
            help=(
                "Delete snapshots older than this many days after collecting "
                "(default 0 = keep everything)."
            ),
        )

    def handle(self, *args, **options):
        cell_size = max(int(options["cell_size"]), 1)
        only = (options["workspace"] or "").strip()

        workspaces = Workspace.objects.all()
        if only:
            workspaces = workspaces.filter(slug=only)

        now = timezone.now()
        total_snapshots = 0

        for ws in workspaces:
            if ws.center is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"  skip {ws.slug}: no centre set, cannot build grid."
                    )
                )
                continue

            sources = ws.data_sources.filter(
                is_enabled=True, layer_kind__in=SHARED_LAYER_KINDS
            )
            for source in sources:
                try:
                    snap = capture_snapshot(source, cell_size=cell_size)
                except KeyError:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  skip {source}: unknown connector "
                            f"{source.source_type!r}."
                        )
                    )
                    continue
                except Exception as exc:  # noqa: BLE001 — one feed failing is not fatal
                    self.stdout.write(
                        self.style.WARNING(f"  fetch failed {source}: {exc}")
                    )
                    continue

                total_snapshots += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  ✓ {source}: {snap.vehicle_count} vehicles in "
                        f"{len(snap.cell_counts)} cells."
                    )
                )

        prune_days = int(options["prune_days"])
        if prune_days > 0:
            cutoff = now - timezone.timedelta(days=prune_days)
            deleted, _ = MobilitySnapshot.objects.filter(
                captured_at__lt=cutoff
            ).delete()
            if deleted:
                self.stdout.write(f"  pruned {deleted} snapshot(s) older than {cutoff:%Y-%m-%d}.")

        self.stdout.write(
            self.style.SUCCESS(f"Done. Stored {total_snapshots} snapshot(s).")
        )
