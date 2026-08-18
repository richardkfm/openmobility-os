"""Effect-factor catalogue — how much harm an intervention is expected to avoid.

Every factor is a range, never a single number, and every factor names the body
of evidence it comes from. That is not decoration: a municipality is being asked
to remove parking and re-stripe streets on the strength of these numbers, so a
reader must be able to check where each came from and disagree with it.

Three rules govern this file:

1. **No unsourced factor.** Each entry carries a ``source`` with a title and a
   link. Where the evidence base is thin or contested, the entry says so through
   a low ``confidence`` and a wide band rather than through a confident-looking
   midpoint.
2. **The lower bound is what gets promised.** UI copy leads with ``low``; the
   central value is a planning figure, not a commitment.
3. **Replaceable.** A workspace overrides any factor via
   ``Workspace.settings["effect_factors"]``. Local evaluation beats a general
   meta-analysis, and no city should have to fork the code to use its own.

Reported values are *expected reductions in the indicator inside the treated
segment*, expressed as a fraction of the harm occurring there — not a
citywide effect, and not a promise about any individual crash.

CALIBRATION NOTE FOR MAINTAINERS
-------------------------------
The bands below are deliberately conservative placeholders drawn from the
general direction of the road-safety literature (protected cycling
infrastructure and lower motor-traffic speeds reduce injury risk; the size of
the effect varies widely by context). They are marked ``needs_review`` until a
maintainer has checked each against the cited source and recorded the exact
figure and page. Do not remove that flag without doing so — the UI surfaces it
so that no reader mistakes a placeholder for a validated number.
"""

from copy import deepcopy

# Reference works, cited by key so a factor cannot drift away from its source.
SOURCES = {
    "who_speed": {
        "title": "WHO — Managing speed / Global status report on road safety",
        "url": "https://www.who.int/publications/i/item/managing-speed",
        "note": (
            "Establishes the relationship between motor-traffic speed and the "
            "probability and severity of injury, and the case for 30 km/h where "
            "motor traffic mixes with people walking and cycling."
        ),
    },
    "who_cycling_infra": {
        "title": (
            "WHO / UNEP — Cycling and walking can help reduce physical inactivity "
            "and air pollution, save lives and mitigate climate change"
        ),
        "url": "https://www.who.int/europe/publications/i/item/9789289057882",
        "note": (
            "Reviews the safety case for physically separated cycling "
            "infrastructure and safe crossings."
        ),
    },
    "itf_safe_system": {
        "title": "ITF/OECD — Road Safety Annual Report / Safe System approach",
        "url": "https://www.itf-oecd.org/road-safety",
        "note": (
            "Safe System framing: infrastructure and speed management are the "
            "levers that remove fatal outcomes rather than redistribute them."
        ),
    },
}


def _factor(low, central, high, *, confidence, source, note_de, note_en, needs_review=True):
    return {
        "low": low,
        "central": central,
        "high": high,
        "confidence": confidence,
        "source": source,
        "note_de": note_de,
        "note_en": note_en,
        "needs_review": needs_review,
    }


# Keyed by intervention. Effects are applied to the harm occurring on the
# treated segment for the indicator in question.
EFFECT_FACTORS: dict[str, dict] = {
    "protected_bike_lane": _factor(
        0.20,
        0.35,
        0.50,
        confidence="medium",
        source=SOURCES["who_cycling_infra"],
        note_de=(
            "Physisch getrennte Radinfrastruktur an Stellen, an denen Radfahrende "
            "heute im Mischverkehr fahren. Die Spanne ist breit, weil die Wirkung "
            "stark von Knotenpunktgestaltung und Kfz-Geschwindigkeit abhängt."
        ),
        note_en=(
            "Physically separated cycling infrastructure where cyclists currently "
            "share the carriageway. The band is wide because the effect depends "
            "heavily on junction design and motor-traffic speed."
        ),
    ),
    "speed_limit_30": _factor(
        0.15,
        0.25,
        0.40,
        confidence="medium",
        source=SOURCES["who_speed"],
        note_de=(
            "Reduzierung der zulässigen Höchstgeschwindigkeit auf 30 km/h. Wirkt "
            "vor allem auf die Schwere der Folgen; die tatsächliche Wirkung hängt "
            "davon ab, ob die Geschwindigkeit auch baulich oder durch Kontrolle "
            "durchgesetzt wird."
        ),
        note_en=(
            "Lowering the posted limit to 30 km/h. Acts mainly on injury severity; "
            "the realised effect depends on whether the speed is actually enforced "
            "by design or by policing."
        ),
    ),
    "safe_crossing": _factor(
        0.10,
        0.20,
        0.35,
        confidence="low",
        source=SOURCES["who_cycling_infra"],
        note_de=(
            "Sichere Querungen (Mittelinseln, vorgezogene Seitenräume, gesicherte "
            "Furten) an Knoten mit dokumentierten Konflikten. Niedrige Konfidenz: "
            "die Wirkung hängt sehr stark von der konkreten Ausführung ab."
        ),
        note_en=(
            "Safe crossings (refuge islands, kerb extensions, protected crossings) "
            "at junctions with a documented conflict record. Low confidence: the "
            "effect depends heavily on the specific design."
        ),
    ),
    "intersection_redesign": _factor(
        0.20,
        0.35,
        0.50,
        confidence="low",
        source=SOURCES["itf_safe_system"],
        note_de=(
            "Umbau eines Knotens nach Safe-System-Prinzipien (Sichtbeziehungen, "
            "Geschwindigkeitsdämpfung, konfliktfreie Führung). Breite Spanne, weil "
            "„Umbau“ sehr unterschiedliche Eingriffstiefen umfasst."
        ),
        note_en=(
            "Rebuilding a junction to Safe System principles (sight lines, speed "
            "reduction, conflict-free routing). Wide band because 'redesign' spans "
            "very different depths of intervention."
        ),
    ),
    "traffic_calming": _factor(
        0.10,
        0.20,
        0.30,
        confidence="low",
        source=SOURCES["who_speed"],
        note_de=(
            "Bauliche Verkehrsberuhigung (Aufpflasterungen, Fahrbahnverengungen, "
            "Diagonalsperren) in Wohnstraßen."
        ),
        note_en=(
            "Physical traffic calming (raised tables, narrowings, modal filters) "
            "in residential streets."
        ),
    ),
}


def factors_for(workspace=None) -> dict:
    """The effect catalogue as it applies to one workspace.

    Per-workspace overrides are merged field-by-field so a city can adjust just
    the band of one intervention without having to restate the source.
    """
    merged = deepcopy(EFFECT_FACTORS)
    overrides = {}
    if workspace is not None:
        overrides = (getattr(workspace, "settings", None) or {}).get("effect_factors") or {}
    for intervention, override in overrides.items():
        if not isinstance(override, dict):
            continue
        base = merged.get(intervention, {})
        merged[intervention] = {**base, **override, "overridden": True}
        # A city that supplies its own numbers has, by doing so, reviewed them.
        merged[intervention].setdefault("needs_review", False)
        if "needs_review" in override:
            merged[intervention]["needs_review"] = override["needs_review"]
        else:
            merged[intervention]["needs_review"] = False
    return merged


def effect_for(intervention: str, workspace=None) -> dict | None:
    return factors_for(workspace).get(intervention)


def combine(shares_and_effects) -> dict:
    """Aggregate per-segment effects into one area-wide reduction.

    ``shares_and_effects`` is an iterable of ``(share, factor)`` pairs, where
    ``share`` is the fraction of the area's baseline harm occurring on that
    segment and ``factor`` is an entry of this catalogue.

    Callers must hand in **disjoint** shares — each unit of harm attributed to at
    most one segment — which is what the engine's one-primary-intervention rule
    guarantees. Under that condition the reductions simply add, and the result
    cannot exceed the share of harm actually addressed.
    """
    out = {"low": 0.0, "central": 0.0, "high": 0.0, "share_addressed": 0.0}
    for share, factor in shares_and_effects:
        if not factor or not share:
            continue
        out["share_addressed"] += share
        for band in ("low", "central", "high"):
            out[band] += share * float(factor[band])
    for key in out:
        out[key] = round(min(out[key], 1.0), 4)
    return out
