"""Unit tests for transit rules, KPI helpers, and equity overlay."""

from dataclasses import dataclass, field
from unittest import TestCase

from measures.rules.electrification import rule_ev_charging_gap
from measures.rules.equity import rule_population_equity_gap
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
    area_km2: float | None = 100.0
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


def _charger(idx):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [12.37 + idx * 0.001, 51.34]},
        "properties": {"osm_id": idx, "amenity": "charging_station"},
    }


class EVChargingGapRuleTests(TestCase):
    def test_triggers_when_residents_per_charger_above_afir_reference(self):
        # 50_000 residents / 100 chargers = 500 per point → far above 100.
        chargers = [_charger(i) for i in range(100)]
        fs = _FakeFS("ev_charging", {"features": chargers})
        ws = _FakeWorkspace(population=50_000, area_km2=300.0)
        candidates = rule_ev_charging_gap(ws, [fs])
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.category, "electrification")
        self.assertEqual(c.evidence["charger_count"], 100)
        self.assertEqual(c.evidence["residents_per_charger"], 500.0)
        # Need 500 to hit AFIR reference (50_000/100) → 400 more.
        self.assertEqual(c.evidence["needed_extra_by_2030"], 400)

    def test_skips_when_density_and_ratio_both_healthy(self):
        chargers = [_charger(i) for i in range(600)]
        fs = _FakeFS("ev_charging", {"features": chargers})
        ws = _FakeWorkspace(population=50_000, area_km2=300.0)
        self.assertEqual(rule_ev_charging_gap(ws, [fs]), [])

    def test_no_feature_set_means_no_candidate(self):
        self.assertEqual(rule_ev_charging_gap(_FakeWorkspace(), []), [])

    def test_density_floor_fires_without_population(self):
        # No population data: rule falls back to the density floor.
        chargers = [_charger(i) for i in range(5)]
        fs = _FakeFS("ev_charging", {"features": chargers})
        ws = _FakeWorkspace(population=None, area_km2=300.0)
        candidates = rule_ev_charging_gap(ws, [fs])
        self.assertEqual(len(candidates), 1)
        # 0.5 chargers/km² * 300 km² = 150 wanted, minus 5 we have.
        self.assertEqual(candidates[0].evidence["needed_extra_by_2030"], 145)


def _grid_cell(pop, under_18, over_65):
    """Build a fake population_grid feature."""
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[12.0, 51.0], [12.001, 51.0], [12.001, 51.001], [12.0, 51.001], [12.0, 51.0]]]},
        "properties": {
            "Einwohner": pop,
            "Alter_unter_18": under_18,
            "Alter_65_und_aelter": over_65,
        },
    }


class PopulationEquityGapRuleTests(TestCase):
    def test_triggers_when_clusters_of_high_child_share_exist(self):
        # 20 cells: 10 average (10% u18), 10 with very high child share (50% u18)
        # workspace avg u18 = (100+500)/2000 = 0.3, threshold = 0.45
        # high cells: 50/100 = 0.5 > 0.45 → flagged
        avg_cells = [_grid_cell(100, 10, 15) for _ in range(10)]
        high_cells = [_grid_cell(100, 50, 10) for _ in range(10)]
        fs = _FakeFS("population_grid", {"features": avg_cells + high_cells})
        ws = _FakeWorkspace(population=2000)
        candidates = rule_population_equity_gap(ws, [fs])
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.slug, "equity-focused-infrastructure")
        self.assertEqual(c.evidence["total_population"], 2000)
        self.assertGreater(c.evidence["high_child_cells"], 0)

    def test_skips_when_population_is_homogeneous(self):
        # All cells have identical demographics → no clusters
        cells = [_grid_cell(100, 20, 20) for _ in range(20)]
        fs = _FakeFS("population_grid", {"features": cells})
        ws = _FakeWorkspace(population=2000)
        self.assertEqual(rule_population_equity_gap(ws, [fs]), [])

    def test_skips_without_population_grid(self):
        self.assertEqual(rule_population_equity_gap(_FakeWorkspace(), []), [])

    def test_skips_when_too_few_cells(self):
        cells = [_grid_cell(100, 50, 50) for _ in range(5)]
        fs = _FakeFS("population_grid", {"features": cells})
        self.assertEqual(rule_population_equity_gap(_FakeWorkspace(), [fs]), [])


# --------------------------------------------------------------------------- #
# Cycling-gap rule
# --------------------------------------------------------------------------- #
from dataclasses import dataclass as _dataclass  # noqa: E402

from measures.rules.cycling_gap import rule_cycling_infrastructure_gap  # noqa: E402


@_dataclass
class _FakeCenter:
    x: float = 0.0
    y: float = 0.0


@_dataclass
class _GeoWorkspace:
    name: str = "Demo"
    center: _FakeCenter = None

    def __post_init__(self):
        if self.center is None:
            self.center = _FakeCenter()


def _acc(lon, lat, *, severity="serious", modes=("cyclist",)):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"severity": severity, "year": 2023, "involved_modes": list(modes)},
    }


def _line(name, coords):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {"name": name},
    }


_GAP_STREET = _line("Risk Road", [[0.0, 0.0], [0.02, 0.0]])


class CyclingInfrastructureGapRuleTests(TestCase):
    def _cyclist_accidents(self):
        return [
            _acc(0.004, 0.00001, severity="serious"),
            _acc(0.008, 0.00001, severity="serious"),
        ]

    def test_flags_gap_and_carries_multilinestring(self):
        accidents_fs = _FakeFS("accidents", {"features": self._cyclist_accidents()})
        streets_fs = _FakeFS("streets_with_speed", {"features": [_GAP_STREET]})
        bike_fs = _FakeFS("bike_network", {"features": []})
        ws = _GeoWorkspace()
        candidates = rule_cycling_infrastructure_gap(
            ws, [accidents_fs, streets_fs, bike_fs]
        )
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.slug, "cycling-accident-infrastructure-gaps")
        self.assertEqual(c.category, "bike_infra")
        self.assertEqual(c.evidence["gap_street_count"], 1)
        self.assertIsNotNone(c.geometry)
        self.assertEqual(c.geometry.geom_type, "MultiLineString")

    def test_skips_when_bike_infra_nearby(self):
        accidents_fs = _FakeFS("accidents", {"features": self._cyclist_accidents()})
        streets_fs = _FakeFS("streets_with_speed", {"features": [_GAP_STREET]})
        bike_fs = _FakeFS(
            "bike_network",
            {"features": [_line("cycleway", [[0.0, 0.00002], [0.02, 0.00002]])]},
        )
        candidates = rule_cycling_infrastructure_gap(
            _GeoWorkspace(), [accidents_fs, streets_fs, bike_fs]
        )
        self.assertEqual(candidates, [])

    def test_skips_without_streets(self):
        accidents_fs = _FakeFS("accidents", {"features": self._cyclist_accidents()})
        self.assertEqual(
            rule_cycling_infrastructure_gap(_GeoWorkspace(), [accidents_fs]), []
        )

    def test_prefers_dedicated_bike_network_layer(self):
        # A dedicated bike way sits right on the risky street → no gap, even
        # though the loose bike_network layer is empty. Confirms the rule reads
        # the stricter layer when present.
        accidents_fs = _FakeFS("accidents", {"features": self._cyclist_accidents()})
        streets_fs = _FakeFS("streets_with_speed", {"features": [_GAP_STREET]})
        dedicated_fs = _FakeFS(
            "dedicated_bike_network",
            {"features": [_line("dedicated track", [[0.0, 0.00002], [0.02, 0.00002]])]},
        )
        loose_fs = _FakeFS("bike_network", {"features": []})
        candidates = rule_cycling_infrastructure_gap(
            _GeoWorkspace(), [accidents_fs, streets_fs, dedicated_fs, loose_fs]
        )
        self.assertEqual(candidates, [])
