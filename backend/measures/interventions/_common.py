"""Shared types for intervention finders.

An intervention finder answers: "given the data inside this focus area, which
concrete segments should be rebuilt, and how?" It mirrors the rule interface in
``measures/rules/_common.py`` deliberately — same shape, same registration
style — so that adding a finder for climate or transit targets later needs no
new machinery.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InterventionCandidate:
    """One proposed segment rebuild, before scoring and space analysis."""

    key: str                       # stable identity within the plan
    intervention: str              # AreaPlanItem.Intervention value
    title_de: str
    title_en: str
    geometry: Any = None           # GeoJSON geometry dict
    quantity: float | None = None  # e.g. metres of street
    unit: str = "m"

    # Harm this segment carries, in the units of the target's indicator.
    affected_cases: float = 0.0
    # Whether any of that harm is a person killed or seriously injured. This
    # drives the ranking, and it is never traded away against volume.
    severe: bool = False

    street_props: dict = field(default_factory=dict)
    parking_features: list = field(default_factory=list)
    obstacles: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
