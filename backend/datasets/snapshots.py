"""Capture a single shared-mobility snapshot.

Shared by the ``collect_mobility_snapshots`` management command (for scheduled
collection) and the data-hub "Collect snapshot now" button (for manual,
on-demand collection from the UI). Keeping the logic here means both paths
produce identical :class:`MobilitySnapshot` rows.
"""

from __future__ import annotations

from django.utils import timezone

from connectors.registry import get_connector

from .mobility_gaps import DEFAULT_CELL_SIZE_M, bin_features_to_grid, grid_steps
from .models import DataSource, MobilitySnapshot

SHARED_LAYER_KINDS = (
    DataSource.LayerKind.SHARED_VEHICLES,
    DataSource.LayerKind.SHARED_STATIONS,
)


def capture_snapshot(
    source: DataSource, *, cell_size: int = DEFAULT_CELL_SIZE_M
) -> MobilitySnapshot:
    """Fetch a shared-mobility source's current state and store one snapshot.

    Raises ``ValueError`` if the workspace has no centre (the analysis grid is
    anchored on it), ``KeyError`` if the connector is unknown, or whatever the
    connector raises on a failed fetch — callers decide how to surface those.
    """
    ws = source.workspace
    center = ws.center
    if center is None:
        raise ValueError("Workspace has no centre set; cannot build analysis grid.")

    connector = get_connector(source.source_type)
    result = connector.fetch(source.config, workspace=ws)
    features = (result.feature_collection or {}).get("features") or []

    lon_step, lat_step = grid_steps(center.y, cell_size)
    grid = bin_features_to_grid(features, lon_step, lat_step)
    vehicle_count = int(sum(sum(cell.values()) for cell in grid.values()))

    return MobilitySnapshot.objects.create(
        source=source,
        workspace=ws,
        captured_at=timezone.now(),
        vehicle_count=vehicle_count,
        cell_counts=grid,
        cell_size_m=cell_size,
        lon_step=lon_step,
        lat_step=lat_step,
    )
