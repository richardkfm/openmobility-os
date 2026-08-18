"""Generate the area plan(s) for a workspace.

Mirrors ``generate_measures``: idempotent, safe to re-run, and usable from cron
or the entrypoint without any web request.
"""

from django.core.management.base import BaseCommand, CommandError

from goals.models import AreaTarget
from measures.area_engine import build_area_plan
from workspaces.models import Workspace


class Command(BaseCommand):
    help = "Build area plans for a workspace's focus-area targets."

    def add_arguments(self, parser):
        parser.add_argument("workspace", help="Workspace slug")
        parser.add_argument(
            "area",
            nargs="?",
            help="Focus-area slug. Omit to plan every area in the workspace.",
        )

    def handle(self, *args, **options):
        try:
            ws = Workspace.objects.get(slug=options["workspace"])
        except Workspace.DoesNotExist as exc:
            raise CommandError(f"No workspace '{options['workspace']}'") from exc

        targets = AreaTarget.objects.filter(workspace=ws).select_related("focus_area")
        if options.get("area"):
            targets = targets.filter(focus_area__slug=options["area"])
        if not targets.exists():
            self.stdout.write(self.style.WARNING("No area targets to plan."))
            return

        for target in targets:
            plan = build_area_plan(target)
            projection = plan.projection or {}
            residual = projection.get("residual_absolute")
            self.stdout.write(
                f"{target.focus_area.slug}/{target.code}: "
                f"{plan.items.count()} items, "
                f"baseline {projection.get('baseline')} → residual {residual}"
            )
            if target.is_vision_zero and residual and residual > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Target not met: {residual} still expected per year."
                    )
                )
