"""Run the measures engine for one or all workspaces."""

from django.core.management.base import BaseCommand, CommandError

from measures.engine import run_engine
from workspaces.models import Workspace


class Command(BaseCommand):
    help = "Generate measures via the rule-based engine."

    def add_arguments(self, parser):
        parser.add_argument(
            "workspace_slug",
            nargs="?",
            default="",
            help="Workspace slug (omit for all active workspaces)",
        )

    def handle(self, *args, **options):
        slug = options["workspace_slug"]
        if slug:
            try:
                workspaces = [Workspace.objects.get(slug=slug)]
            except Workspace.DoesNotExist as exc:
                raise CommandError(f"Unknown workspace: {slug}") from exc
        else:
            workspaces = list(Workspace.objects.filter(is_active=True))

        for ws in workspaces:
            self.stdout.write(f"→ Generating measures for {ws.slug}")
            report = run_engine(ws)
            self.stdout.write(
                self.style.SUCCESS(
                    f"   ✓ generated={report.generated}, updated={report.updated}, "
                    f"skipped={report.skipped}, rules={report.rule_counts}"
                )
            )
