"""Shared helpers for rule functions."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MeasureCandidate:
    slug: str
    category: str
    title_de: str
    title_en: str = ""
    summary_de: str = ""
    summary_en: str = ""
    description_de_md: str = ""
    description_en_md: str = ""
    effort_level: str = "medium"
    evidence: dict = field(default_factory=dict)
    geometry: Any = None
    scores: dict = field(default_factory=dict)


def select_by_layer(feature_sets, layer_kind):
    for fs in feature_sets:
        if fs.layer_kind == layer_kind:
            return fs
    return None


def score(raw: float, confidence: str = "medium", rationale_de: str = "", rationale_en: str = "", sources=None) -> dict:
    raw = max(0.0, min(1.0, raw))
    return {
        "raw": raw,
        "display": round(raw * 100, 1),
        "confidence": confidence,
        "rationale_de": rationale_de,
        "rationale_en": rationale_en,
        "sources": sources or [],
    }
