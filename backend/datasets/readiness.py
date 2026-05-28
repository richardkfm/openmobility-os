"""Per-source readiness badge used by the admin data hub.

Translates the raw `DataSource` status + record count + last-sync timestamp
into a single categorical badge so the hub list reads at a glance.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext as _

from .models import DataSource

STALE_THRESHOLD = timedelta(days=30)
THIN_RECORD_COUNT = 50


def source_readiness(source: DataSource) -> dict:
    """Return ``{level, label, hint}`` for a single data source.

    Levels (in priority order):
        ``error``    — last sync failed
        ``empty``    — never synced or zero records
        ``stale``    — synced > 30 days ago
        ``thin``     — fewer than 50 records (sampling threshold)
        ``good``     — recent sync with a reasonable record count
    """
    if source.status == DataSource.Status.ERROR:
        return {
            "level": "error",
            "label": _("Error"),
            "hint": _("Last sync failed — see error message."),
        }

    count = source.record_count or 0
    if count == 0 or source.last_synced_at is None:
        return {
            "level": "empty",
            "label": _("No data"),
            "hint": _("Source has not been synced yet."),
        }

    age = timezone.now() - source.last_synced_at
    if age > STALE_THRESHOLD:
        days = int(age.total_seconds() // 86400)
        return {
            "level": "stale",
            "label": _("Stale"),
            "hint": _("Last sync %(d)d days ago — consider re-syncing.")
            % {"d": days},
        }

    if count < THIN_RECORD_COUNT:
        return {
            "level": "thin",
            "label": _("Thin"),
            "hint": _("Only %(n)d records — may indicate a partial import.")
            % {"n": count},
        }

    return {
        "level": "good",
        "label": _("Ready"),
        "hint": _("Recent sync with %(n)d records.") % {"n": count},
    }
