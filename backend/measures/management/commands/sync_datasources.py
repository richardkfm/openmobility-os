"""Sync all data sources (or just one workspace) via their connectors."""

from django.core.management.base import BaseCommand

from datasets.models import DataSource
from datasets.views import _run_sync
from workspaces.models import Workspace


class Command(BaseCommand):
    help = "Sync all data sources; optionally filter by workspace slug."

    def add_arguments(self, parser):
        parser.add_argument("workspace_slug", nargs="?", default="")

    def handle(self, *args, **options):
        slug = options["workspace_slug"]
        qs = DataSource.objects.all()
        if slug:
            ws = Workspace.objects.filter(slug=slug).first()
            if not ws:
                self.stdout.write(self.style.ERROR(f"Unknown workspace: {slug}"))
                return
            qs = qs.filter(workspace=ws)

        for source in qs:
            self.stdout.write(f"→ Syncing {source}")
            success, message = _run_sync(source)
            style = self.style.SUCCESS if success else self.style.WARNING
            self.stdout.write(style(f"   {'✓' if success else '✗'} {message}"))
