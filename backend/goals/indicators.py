"""Indicator catalogue for area targets.

An indicator answers "what exactly are we measuring inside this area, and how do
we get its current value from the data we have?". Each entry is self-describing
so the methodology page can print the definition and the baseline can be
reproduced by anyone with the same source data.

Two things here are load-bearing beyond bookkeeping:

``harm_class``
    ``"fatal_or_serious"`` marks indicators that count killed or seriously
    injured people. Those indicators may only ever carry a target of **zero**
    (see :class:`goals.models.AreaTarget`). A goal of "90 % fewer road deaths"
    declares the remaining 10 % acceptable, and no one should be asked to sign
    off on which of their neighbours that is. The platform therefore cannot
    express such a target at all — this flag is what makes that structural
    rather than a matter of wording.

``required_layers``
    Gates the indicator in the UI, so a workspace is never offered a target it
    has no data to measure — the same rule the map's story views follow.
"""

from django.utils.translation import gettext_lazy as _

# Severity weighting shared with measures.accident_density (fatal 3 / serious 2 /
# minor 1). Repeated here as a doc reference only; counting uses the raw classes.
FATAL = "fatal"
SERIOUS = "serious"
MINOR = "minor"

# Default look-back window. Road-safety analysis normally pools several years,
# because single-year counts on a small area are dominated by chance.
DEFAULT_WINDOW_YEARS = 3

# Below this many recorded cases in the window, any rate computed for the area is
# statistically fragile and is reported with low confidence and a visible note.
MIN_ROBUST_CASES = 5


def _accident_baseline(features, *, severities, modes, window_years):
    """Count matching accidents per year, plus the metadata to reproduce it.

    ``features`` are already clipped to the focus area by the caller.
    """
    years = sorted(
        {
            y
            for y in (_year_of(f) for f in features)
            if y is not None
        }
    )
    recent = years[-window_years:] if years else []
    matched = [
        f
        for f in features
        if _year_of(f) in recent
        and (not severities or _prop(f, "severity") in severities)
        and (not modes or _has_mode(f, modes))
    ]
    n_years = len(recent) or 1
    by_severity: dict[str, int] = {}
    for f in matched:
        key = _prop(f, "severity") or "unknown"
        by_severity[key] = by_severity.get(key, 0) + 1

    return round(len(matched) / n_years, 2), {
        "method": "count_per_year",
        "years": recent,
        "years_counted": n_years,
        "matched_cases": len(matched),
        "by_severity": by_severity,
        "severities": sorted(severities) if severities else "all",
        "modes": sorted(modes) if modes else "all",
        "robust": len(matched) >= MIN_ROBUST_CASES,
        "min_robust_cases": MIN_ROBUST_CASES,
    }


def _year_of(feature):
    props = feature.get("properties") or {}
    for key in ("year", "date"):
        raw = props.get(key)
        if raw is None:
            continue
        text = str(raw)
        if text[:4].isdigit():
            return int(text[:4])
    return None


def _prop(feature, key):
    return (feature.get("properties") or {}).get(key)


def _has_mode(feature, modes):
    involved = _prop(feature, "involved_modes") or []
    if isinstance(involved, str):
        involved = [involved]
    return any(m in involved for m in modes)


INDICATORS: dict[str, dict] = {
    "cyclist_fatal_serious": {
        "label_de": "Getötete und Schwerverletzte im Radverkehr (pro Jahr)",
        "label_en": "Cyclists killed or seriously injured (per year)",
        "unit_de": "Personen / Jahr",
        "unit_en": "people / year",
        "direction": "decrease",
        "harm_class": "fatal_or_serious",
        "required_layers": ["accidents"],
        "window_years": DEFAULT_WINDOW_YEARS,
        "severities": {FATAL, SERIOUS},
        "modes": {"cyclist"},
    },
    "vru_fatal_serious": {
        "label_de": (
            "Getötete und Schwerverletzte unter zu Fuß Gehenden und Radfahrenden "
            "(pro Jahr)"
        ),
        "label_en": (
            "Pedestrians and cyclists killed or seriously injured (per year)"
        ),
        "unit_de": "Personen / Jahr",
        "unit_en": "people / year",
        "direction": "decrease",
        "harm_class": "fatal_or_serious",
        "required_layers": ["accidents"],
        "window_years": DEFAULT_WINDOW_YEARS,
        "severities": {FATAL, SERIOUS},
        "modes": {"cyclist", "pedestrian"},
    },
    "all_fatal_serious": {
        "label_de": "Getötete und Schwerverletzte insgesamt (pro Jahr)",
        "label_en": "All road users killed or seriously injured (per year)",
        "unit_de": "Personen / Jahr",
        "unit_en": "people / year",
        "direction": "decrease",
        "harm_class": "fatal_or_serious",
        "required_layers": ["accidents"],
        "window_years": DEFAULT_WINDOW_YEARS,
        "severities": {FATAL, SERIOUS},
        "modes": set(),
    },
    "cyclist_accidents_all": {
        "label_de": "Radverkehrsunfälle aller Schweregrade (pro Jahr)",
        "label_en": "Cyclist collisions of all severities (per year)",
        "unit_de": "Unfälle / Jahr",
        "unit_en": "collisions / year",
        "direction": "decrease",
        "harm_class": "all_severities",
        "required_layers": ["accidents"],
        "window_years": DEFAULT_WINDOW_YEARS,
        "severities": set(),
        "modes": {"cyclist"},
    },
    "all_accidents": {
        "label_de": "Verkehrsunfälle aller Schweregrade (pro Jahr)",
        "label_en": "Road collisions of all severities (per year)",
        "unit_de": "Unfälle / Jahr",
        "unit_en": "collisions / year",
        "direction": "decrease",
        "harm_class": "all_severities",
        "required_layers": ["accidents"],
        "window_years": DEFAULT_WINDOW_YEARS,
        "severities": set(),
        "modes": set(),
    },
}


def get_indicator(key: str) -> dict | None:
    return INDICATORS.get(key)


def is_vision_zero(key: str) -> bool:
    """True when the indicator counts killed or seriously injured people.

    Such indicators accept only a target of zero — the single most important
    rule in this module.
    """
    spec = INDICATORS.get(key)
    return bool(spec and spec.get("harm_class") == "fatal_or_serious")


def label_for(key: str, language_code: str = "de") -> str:
    spec = INDICATORS.get(key)
    if not spec:
        return key
    return spec["label_en"] if str(language_code).startswith("en") else spec["label_de"]


def unit_for(key: str, language_code: str = "de") -> str:
    spec = INDICATORS.get(key)
    if not spec:
        return ""
    return spec["unit_en"] if str(language_code).startswith("en") else spec["unit_de"]


def compute_baseline(key: str, clipped_features_by_layer: dict) -> tuple[float, dict]:
    """Current value of the indicator inside an area, plus reproducible metadata.

    ``clipped_features_by_layer`` maps a layer kind to the GeoJSON features of
    that layer already restricted to the focus area.
    """
    spec = INDICATORS.get(key)
    if not spec:
        return 0.0, {"error": f"unknown indicator: {key}"}
    accidents = clipped_features_by_layer.get("accidents") or []
    return _accident_baseline(
        accidents,
        severities=spec["severities"],
        modes=spec["modes"],
        window_years=spec["window_years"],
    )


def available_indicators(layer_kinds) -> list[str]:
    """Indicator keys this workspace has the data to measure."""
    present = set(layer_kinds)
    return [
        key
        for key, spec in INDICATORS.items()
        if present.issuperset(spec["required_layers"])
    ]


# Human-readable choices for forms/admin. Kept lazy so the language of the
# request decides, per the i18n rule in CLAUDE.md.
def indicator_choices():
    return [
        (key, _(spec["label_en"]))
        for key, spec in INDICATORS.items()
    ]
