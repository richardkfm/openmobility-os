"""KPI importers for German survey data sources.

Parses CSV-based survey results (ADFC Fahrradklimatest, MiD modal-split)
and returns structured dicts that the ``import_kpis`` management command
writes into ``WorkspaceGoal.current_value``.

These are *not* regular connectors — they produce KPI values for workspace
goals, not GeoJSON features for the map. The import flow is:

    CSV → parser → [{workspace_match, goal_code, value, unit, …}] → WorkspaceGoal

Both parsers accept raw CSV bytes (``_csv_bytes`` kwarg for tests) or fetch
from a URL. City matching is case-insensitive and accent-folded.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

import requests

_USER_AGENT = "OpenMobility-OS/1 (kpi-importer)"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _normalize_city(name: str) -> str:
    """Lowercase, strip accents and whitespace for fuzzy city matching."""
    s = unicodedata.normalize("NFD", name.lower().strip())
    return re.sub(r"[̀-ͯ]", "", s)


@dataclass
class KPIRecord:
    """One KPI value ready to be written into a WorkspaceGoal."""

    city_name: str
    city_normalized: str
    goal_code: str
    value: float
    unit: str = ""
    title_de: str = ""
    title_en: str = ""
    source_label: str = ""
    source_url: str = ""
    year: Optional[int] = None
    extra: dict = field(default_factory=dict)


def _fetch_csv(url: str, encoding: str = "utf-8", timeout: int = 60) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": _USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.content.decode(encoding)


# ---------------------------------------------------------------------------
# ADFC Fahrradklimatest
# ---------------------------------------------------------------------------

# Default column names in the ADFC results CSV. The CSV layout has changed
# slightly between survey rounds (2018, 2020, 2022); these are the 2022
# defaults. Operators can override via config.
_ADFC_DEFAULTS = {
    "city_col": "Ort",
    "grade_col": "Gesamtbewertung",
    "delimiter": ";",
    "encoding": "utf-8",
}


def parse_adfc(
    *,
    url: Optional[str] = None,
    city_col: str = _ADFC_DEFAULTS["city_col"],
    grade_col: str = _ADFC_DEFAULTS["grade_col"],
    subcategory_cols: Optional[list[str]] = None,
    delimiter: str = _ADFC_DEFAULTS["delimiter"],
    encoding: str = _ADFC_DEFAULTS["encoding"],
    _csv_bytes: Optional[bytes] = None,
) -> list[KPIRecord]:
    """Parse an ADFC Fahrradklimatest results CSV.

    The ADFC Fahrradklimatest is a biennial survey (since 2012) where
    cyclists rate their city's cycling-friendliness on a 1–6 school-grade
    scale (1 = very good, 6 = very poor). Results are published per city.

    Returns one ``KPIRecord`` per city with ``goal_code="adfc_fahrradklima"``
    carrying the overall grade. If ``subcategory_cols`` is given, additional
    records are emitted per sub-grade (e.g. ``adfc_fahrradklima_sicherheit``).
    """
    if _csv_bytes is not None:
        text = _csv_bytes.decode(encoding)
    elif url:
        text = _fetch_csv(url, encoding=encoding)
    else:
        raise ValueError("Either url or _csv_bytes must be provided.")

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    records: list[KPIRecord] = []

    for row in reader:
        city = (row.get(city_col) or "").strip()
        grade_raw = (row.get(grade_col) or "").strip().replace(",", ".")
        if not city or not grade_raw:
            continue
        try:
            grade = float(grade_raw)
        except ValueError:
            continue

        records.append(
            KPIRecord(
                city_name=city,
                city_normalized=_normalize_city(city),
                goal_code="adfc_fahrradklima",
                value=grade,
                unit="Note / grade (1–6)",
                title_de="ADFC Fahrradklimatest — Gesamtbewertung",
                title_en="ADFC cycling climate test — overall grade",
                source_label="ADFC Fahrradklimatest",
            )
        )

        for sub_col in subcategory_cols or []:
            sub_raw = (row.get(sub_col) or "").strip().replace(",", ".")
            if not sub_raw:
                continue
            try:
                sub_val = float(sub_raw)
            except ValueError:
                continue
            slug = re.sub(r"[^a-z0-9]+", "_", sub_col.lower()).strip("_")
            records.append(
                KPIRecord(
                    city_name=city,
                    city_normalized=_normalize_city(city),
                    goal_code=f"adfc_fahrradklima_{slug}",
                    value=sub_val,
                    unit="Note / grade (1–6)",
                    title_de=f"ADFC Fahrradklimatest — {sub_col}",
                    title_en=f"ADFC cycling climate test — {sub_col}",
                    source_label="ADFC Fahrradklimatest",
                )
            )

    return records


# ---------------------------------------------------------------------------
# MiD 2017 (Mobilität in Deutschland)
# ---------------------------------------------------------------------------

_MID_DEFAULTS = {
    "city_col": "Raumeinheit",
    "walking_col": "Fuß",
    "cycling_col": "Rad",
    "transit_col": "ÖV",
    "car_col": "MIV",
    "delimiter": ";",
    "encoding": "utf-8",
}


def parse_mid(
    *,
    url: Optional[str] = None,
    city_col: str = _MID_DEFAULTS["city_col"],
    walking_col: str = _MID_DEFAULTS["walking_col"],
    cycling_col: str = _MID_DEFAULTS["cycling_col"],
    transit_col: str = _MID_DEFAULTS["transit_col"],
    car_col: str = _MID_DEFAULTS["car_col"],
    delimiter: str = _MID_DEFAULTS["delimiter"],
    encoding: str = _MID_DEFAULTS["encoding"],
    _csv_bytes: Optional[bytes] = None,
) -> list[KPIRecord]:
    """Parse a MiD (Mobilität in Deutschland) modal-split CSV.

    MiD is the federal household travel survey (BMDV, most recent: 2017).
    Regional modal-split data is published as aggregated percentages per
    city/Kreis/region type. Each row yields up to four ``KPIRecord`` objects:

    - ``mid_walking_share`` — walking %
    - ``mid_cycling_share`` — cycling %
    - ``mid_transit_share`` — public transit %
    - ``mid_car_share``     — motorized individual transport (MIV) %

    Column names are configurable to handle both the official BMDV
    publication and regional re-publications with different headers.
    """
    if _csv_bytes is not None:
        text = _csv_bytes.decode(encoding)
    elif url:
        text = _fetch_csv(url, encoding=encoding)
    else:
        raise ValueError("Either url or _csv_bytes must be provided.")

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    records: list[KPIRecord] = []

    mode_map = [
        (walking_col, "mid_walking_share", "Fußverkehrsanteil (MiD)", "Walking mode share (MiD)"),
        (cycling_col, "mid_cycling_share", "Radverkehrsanteil (MiD)", "Cycling mode share (MiD)"),
        (transit_col, "mid_transit_share", "ÖV-Anteil (MiD)", "Public transit mode share (MiD)"),
        (car_col, "mid_car_share", "MIV-Anteil (MiD)", "Car mode share (MiD)"),
    ]

    for row in reader:
        city = (row.get(city_col) or "").strip()
        if not city:
            continue

        for col_name, goal_code, title_de, title_en in mode_map:
            raw = (row.get(col_name) or "").strip().replace(",", ".").rstrip("%").strip()
            if not raw:
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            records.append(
                KPIRecord(
                    city_name=city,
                    city_normalized=_normalize_city(city),
                    goal_code=goal_code,
                    value=value,
                    unit="%",
                    title_de=title_de,
                    title_en=title_en,
                    source_label="MiD 2017 (BMDV)",
                    source_url="https://www.mobilitaet-in-deutschland.de/",
                )
            )

    return records
