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


# Ordered worst → best so a layer fed by several sources can report its
# weakest provenance (a single demo source taints the whole layer).
_PROVENANCE_RANK = {
    DataSource.Provenance.ILLUSTRATIVE_DEMO: 0,
    DataSource.Provenance.OFFICIAL_SNAPSHOT: 1,
    DataSource.Provenance.LIVE: 2,
}


def source_provenance(source: DataSource) -> dict:
    """Return ``{level, label, hint}`` describing how real a source is.

    Unlike :func:`source_readiness` (which is about freshness/volume), this is
    about the *nature* of the data and is shown to the public so visitors can
    tell live feeds apart from illustrative placeholders.
    """
    return _provenance_badge(source.provenance)


def _provenance_badge(value: str) -> dict:
    if value == DataSource.Provenance.ILLUSTRATIVE_DEMO:
        return {
            "level": "demo",
            "label": _("Illustrative demo"),
            "hint": _(
                "Placeholder data, not a real measurement — replace with a "
                "real source before drawing conclusions."
            ),
        }
    if value == DataSource.Provenance.OFFICIAL_SNAPSHOT:
        return {
            "level": "snapshot",
            "label": _("Official snapshot"),
            "hint": _(
                "A stored copy of official data — real, but may lag behind "
                "the live source."
            ),
        }
    return {
        "level": "live",
        "label": _("Live source"),
        "hint": _("Connected to a live, authoritative data source."),
    }


def layer_provenance_map(workspace) -> dict:
    """Map each layer kind to its weakest provenance badge.

    A layer can be fed by several sources; the map panel shows the weakest one
    (a single demo source taints the layer) so the public is never misled.
    """
    worst: dict[str, str] = {}
    for s in workspace.data_sources.filter(is_enabled=True):
        current = worst.get(s.layer_kind)
        rank = _PROVENANCE_RANK.get(s.provenance, 2)
        if current is None or rank < _PROVENANCE_RANK.get(current, 2):
            worst[s.layer_kind] = s.provenance
    return {kind: _provenance_badge(value) for kind, value in worst.items()}


def workspace_data_basis(workspace) -> dict:
    """Summarize the provenance mix across a workspace's enabled sources.

    Returns counts plus a ``worst`` badge so the dashboard can warn at a glance
    when a workspace still leans on illustrative demo data.
    """
    sources = workspace.data_sources.filter(is_enabled=True)
    counts = {"live": 0, "snapshot": 0, "demo": 0}
    worst_rank = None
    worst_value = DataSource.Provenance.LIVE
    for s in sources:
        counts[_provenance_badge(s.provenance)["level"]] += 1
        rank = _PROVENANCE_RANK.get(s.provenance, 2)
        if worst_rank is None or rank < worst_rank:
            worst_rank = rank
            worst_value = s.provenance
    total = sum(counts.values())
    return {
        "total": total,
        "live": counts["live"],
        "snapshot": counts["snapshot"],
        "demo": counts["demo"],
        "has_demo": counts["demo"] > 0,
        "worst": _provenance_badge(worst_value) if total else None,
    }
