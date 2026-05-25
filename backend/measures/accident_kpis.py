"""Accident data sufficiency heuristic.

Compares the number of accident records against a population-derived
expectation to give operators a quick read on whether their data is
thick enough for meaningful analysis.

Reference value: ~3 police-recorded accidents per 1,000 residents per
year is a rough EU/German average (Destatis, IRTAD). A workspace with
significantly fewer records likely has incomplete coverage.

Returned keys (all optional — missing when no accident data exists):

``record_count``
    Total accident features on record.

``fatal_count`` / ``serious_count`` / ``minor_count``
    Breakdown by severity.

``year_range``
    ``[min_year, max_year]`` extracted from feature properties, or None.

``expected_per_year``
    Population-derived estimate of expected records per year.

``coverage_ratio``
    ``record_count / (expected_per_year * years_spanned)``, capped at 1.0.
    Values below ~0.2 suggest the dataset is a small sample.

``sufficiency``
    One of ``"good"``, ``"thin"``, ``"placeholder"`` — a plain-language
    rating operators can act on without understanding the math.
"""

from __future__ import annotations

from typing import Any

ACCIDENTS_PER_1000_RESIDENTS = 3.0
MIN_RECORDS_PLACEHOLDER = 50


def compute_accident_kpis(workspace, feature_sets) -> dict[str, Any]:
    accidents_fs = _select(feature_sets, "accidents")
    if not accidents_fs:
        return {}

    features = accidents_fs.feature_collection.get("features", [])
    if not features:
        return {}

    fatal = 0
    serious = 0
    minor = 0
    years_seen: set[int] = set()

    for f in features:
        props = f.get("properties") or {}
        sev = props.get("severity", "minor")
        if sev == "fatal":
            fatal += 1
        elif sev == "serious":
            serious += 1
        else:
            minor += 1

        year = props.get("year")
        if year is not None:
            try:
                years_seen.add(int(year))
            except (ValueError, TypeError):
                pass

    n = len(features)
    kpis: dict[str, Any] = {
        "record_count": n,
        "fatal_count": fatal,
        "serious_count": serious,
        "minor_count": minor,
    }

    if years_seen:
        kpis["year_range"] = [min(years_seen), max(years_seen)]

    population = workspace.population or 0
    if population:
        expected_per_year = population * ACCIDENTS_PER_1000_RESIDENTS / 1000
        kpis["expected_per_year"] = round(expected_per_year)

        years_spanned = max(len(years_seen), 1)
        expected_total = expected_per_year * years_spanned
        ratio = min(n / expected_total, 1.0) if expected_total > 0 else 0.0
        kpis["coverage_ratio"] = round(ratio, 2)
        kpis["coverage_pct"] = round(ratio * 100)

        if n < MIN_RECORDS_PLACEHOLDER:
            kpis["sufficiency"] = "placeholder"
        elif ratio >= 0.4:
            kpis["sufficiency"] = "good"
        else:
            kpis["sufficiency"] = "thin"
    else:
        if n < MIN_RECORDS_PLACEHOLDER:
            kpis["sufficiency"] = "placeholder"
        elif n >= 200:
            kpis["sufficiency"] = "good"
        else:
            kpis["sufficiency"] = "thin"

    return kpis


def _select(feature_sets, layer_kind: str):
    for fs in feature_sets:
        if fs.layer_kind == layer_kind:
            return fs
    return None
