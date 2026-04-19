"""
Rule-based measures engine.

Applies a set of deterministic rules to the workspace's normalized feature
sets and produces `Measure` records. Transparent by design — every rule
stores its inputs as `Measure.evidence` so reviewers can reproduce the logic.
"""

from dataclasses import dataclass, field

from datasets.models import NormalizedFeatureSet
from workspaces.models import Workspace

from .models import Measure, MeasureScore
from .rules import RULES


@dataclass
class EngineReport:
    generated: int = 0
    updated: int = 0
    skipped: int = 0
    rule_counts: dict = field(default_factory=dict)


def run_engine(workspace: Workspace) -> EngineReport:
    report = EngineReport()
    feature_sets = list(NormalizedFeatureSet.objects.filter(workspace=workspace))

    for rule in RULES:
        try:
            candidates = rule(workspace, feature_sets)
        except Exception as exc:  # noqa: BLE001
            report.skipped += 1
            report.rule_counts[rule.__name__] = f"ERROR: {exc}"
            continue
        report.rule_counts[rule.__name__] = len(candidates)
        for cand in candidates:
            measure, created = Measure.objects.update_or_create(
                workspace=workspace,
                slug=cand.slug,
                defaults={
                    "category": cand.category,
                    "title_de": cand.title_de,
                    "title_en": cand.title_en,
                    "summary_de": cand.summary_de,
                    "summary_en": cand.summary_en,
                    "description_de_md": cand.description_de_md,
                    "description_en_md": cand.description_en_md,
                    "effort_level": cand.effort_level,
                    "is_auto_generated": True,
                    "evidence": cand.evidence,
                    "geometry": cand.geometry,
                },
            )
            if created:
                report.generated += 1
            else:
                report.updated += 1

            for dim, payload in cand.scores.items():
                MeasureScore.objects.update_or_create(
                    measure=measure,
                    dimension=dim,
                    defaults={
                        "raw_value": payload["raw"],
                        "display_value": payload["display"],
                        "confidence": payload.get("confidence", "medium"),
                        "rationale_de": payload.get("rationale_de", ""),
                        "rationale_en": payload.get("rationale_en", ""),
                        "sources": payload.get("sources", []),
                    },
                )

    return report
