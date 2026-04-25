"""Unit tests for Phase 9 transit rules and KPI helpers."""

from dataclasses import dataclass, field
from unittest import TestCase

from measures.rules.transit import (
    rule_transit_accessibility,
    rule_transit_coverage_gap,
    rule_transit_frequency,
)
from measures.transit_kpis import compute_transit_kpis


@dataclass
class _FakeFS:
    layer_kind: str
    feature_collection: dict = field(default_factory=lambda: {"features": []})


@dataclass
class _FakeBounds:
    extent: tuple[float, float, float, float]


@dataclass
class _FakeWorkspace:
    name: str = "Demo"
    population: int | None = 50_000
    bounds: _FakeBounds | None = None


def _stop(stop_id, *, headway=None, wheelchair="unknown", night=False, modes=None):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [10.0, 50.0]},
        "properties": {
            "stop_id": stop_id,
            "avg_headway_min": headway,
            "wheelchair_boarding": wheelchair,
            "night_service": night,
            "modes": modes or [],
        },
    }


class TransitCoverageGapRuleTests(TestCase):
    def test_triggers_when_stop_count_well_below_population_target(self):
        # 50_000 residents ⇒ expected ~100 stops. Provide only 40 → gap=60%.
        stops = [_stop(f"s{i}") for i in range(40)]
        fs = _FakeFS("transit_stops", {"features": stops})
        ws = _FakeWorkspace(population=50_000)
        candidates = rule_transit_coverage_gap(ws, [fs])
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.category, "transit_gap")
        self.assertEqual(c.evidence["stop_count"], 40)
        self.assertGreater(c.evidence["gap_ratio"], 0.15)

    def test_skips_when_well_covered(self):
        stops = [_stop(f"s{i}") for i in range(150)]
        fs = _FakeFS("transit_stops", {"features": stops})
        ws = _FakeWorkspace(population=50_000)
        self.assertEqual(rule_transit_coverage_gap(ws, [fs]), [])


class TransitFrequencyRuleTests(TestCase):
    def test_triggers_when_many_stops_have_long_headway(self):
        stops = (
            [_stop(f"slow{i}", headway=30) for i in range(10)]
            + [_stop(f"fast{i}", headway=10) for i in range(10)]
        )
        fs = _FakeFS("transit_stops", {"features": stops})
        ws = _FakeWorkspace(population=30_000)
        candidates = rule_transit_frequency(ws, [fs])
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.category, "transit_frequency")
        self.assertEqual(c.evidence["low_freq_stops"], 10)
        self.assertEqual(c.evidence["total_stops_with_headway"], 20)

    def test_ignores_stops_without_headway(self):
        stops = [_stop(f"s{i}", headway=None) for i in range(5)]
        fs = _FakeFS("transit_stops", {"features": stops})
        self.assertEqual(rule_transit_frequency(_FakeWorkspace(), [fs]), [])


class TransitAccessibilityRuleTests(TestCase):
    def test_triggers_when_many_stops_not_barrier_free(self):
        stops = (
            [_stop(f"no{i}", wheelchair="no") for i in range(4)]
            + [_stop(f"yes{i}", wheelchair="yes") for i in range(6)]
        )
        fs = _FakeFS("transit_stops", {"features": stops})
        candidates = rule_transit_accessibility(_FakeWorkspace(), [fs])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].category, "transit_accessibility")
        self.assertEqual(candidates[0].evidence["stops_not_barrier_free"], 4)

    def test_unknown_accessibility_counts_as_unrated(self):
        stops = [_stop(f"u{i}", wheelchair="unknown") for i in range(10)]
        fs = _FakeFS("transit_stops", {"features": stops})
        self.assertEqual(rule_transit_accessibility(_FakeWorkspace(), [fs]), [])


class TransitKPIsTests(TestCase):
    def test_headway_night_and_barrier_free_pct(self):
        stops = [
            _stop("a", headway=10, wheelchair="yes", night=True),
            _stop("b", headway=20, wheelchair="no", night=False),
            _stop("c", headway=30, wheelchair="unknown", night=True),
        ]
        fs = _FakeFS("transit_stops", {"features": stops})
        kpis = compute_transit_kpis(_FakeWorkspace(), [fs])
        self.assertEqual(kpis["stop_count"], 3)
        self.assertEqual(kpis["avg_headway_min"], 20)
        self.assertAlmostEqual(kpis["night_service_pct"], 66.7, places=1)
        self.assertEqual(kpis["barrier_free_pct"], 50.0)

    def test_coverage_percentage_from_buffer_polygons(self):
        # Workspace bounds 10×10 degrees; one big buffer over center covers ~an
        # ellipse with radii 2 → area ≈ π * 2 * 2 ≈ 12.57 / 100 ≈ 12.6%.
        buffer = {
            "type": "Polygon",
            "coordinates": [[
                [4.0, 4.0],
                [6.0, 4.0],
                [6.0, 6.0],
                [4.0, 6.0],
                [4.0, 4.0],
            ]],
        }
        stops_fs = _FakeFS("transit_stops", {"features": []})
        coverage_fs = _FakeFS(
            "transit_coverage",
            {"features": [{"type": "Feature", "geometry": buffer, "properties": {}}]},
        )
        ws = _FakeWorkspace(
            population=100_000, bounds=_FakeBounds(extent=(0.0, 0.0, 10.0, 10.0))
        )
        kpis = compute_transit_kpis(ws, [stops_fs, coverage_fs])
        self.assertIn("coverage_pct", kpis)
        self.assertGreater(kpis["coverage_pct"], 2.0)
        self.assertLess(kpis["coverage_pct"], 5.0)
        self.assertEqual(
            kpis["population_in_coverage"],
            int(100_000 * kpis["coverage_pct"] / 100),
        )

    def test_empty_feature_sets_yield_empty_dict(self):
        self.assertEqual(compute_transit_kpis(_FakeWorkspace(), []), {})
