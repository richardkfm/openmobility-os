"""Unit tests for the shared-mobility gap-analysis aggregation.

These exercise the pure functions in ``datasets.mobility_gaps`` and need no
database — they use plain ``unittest.TestCase`` so they run standalone as well
as under the Django test runner.
"""

from unittest import TestCase

from datasets.mobility_gaps import (
    ANY_FACTOR,
    bin_features_to_grid,
    cell_key,
    cell_polygon,
    compute_gap_grid,
    feature_weight_and_factor,
    grid_steps,
)


def _vehicle(lon, lat, form_factor="bicycle"):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"form_factor": form_factor},
    }


def _station(lon, lat, available):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"num_vehicles_available": available},
    }


class GridGeometryTests(TestCase):
    def test_grid_steps_are_positive_and_metric(self):
        lon_step, lat_step = grid_steps(51.34, 400)
        self.assertGreater(lon_step, 0)
        self.assertGreater(lat_step, 0)
        # At 51° latitude a degree of longitude is much shorter than a degree
        # of latitude, so the lon step (in degrees) must be the larger one to
        # cover the same 400 m on the ground.
        self.assertGreater(lon_step, lat_step)

    def test_cell_key_and_polygon_round_trip(self):
        lon_step, lat_step = grid_steps(51.34, 400)
        key = cell_key(12.37, 51.34, lon_step, lat_step)
        ring = cell_polygon(key, lon_step, lat_step)
        # Closed ring of 5 points enclosing the original coordinate.
        self.assertEqual(len(ring), 5)
        self.assertEqual(ring[0], ring[-1])
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        self.assertLessEqual(min(xs), 12.37)
        self.assertGreaterEqual(max(xs), 12.37)
        self.assertLessEqual(min(ys), 51.34)
        self.assertGreaterEqual(max(ys), 51.34)


class FeatureParsingTests(TestCase):
    def test_vehicle_weight_is_one(self):
        lon, lat, weight, factor = feature_weight_and_factor(_vehicle(12.37, 51.34, "car"))
        self.assertEqual((lon, lat, weight, factor), (12.37, 51.34, 1.0, "car"))

    def test_station_weight_uses_available_count(self):
        _, _, weight, factor = feature_weight_and_factor(_station(12.37, 51.34, 5))
        self.assertEqual(weight, 5.0)
        self.assertEqual(factor, ANY_FACTOR)

    def test_non_point_and_malformed_rejected(self):
        self.assertIsNone(
            feature_weight_and_factor(
                {"geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}}
            )
        )
        self.assertIsNone(feature_weight_and_factor({"geometry": {"type": "Point"}}))


class BinningTests(TestCase):
    def setUp(self):
        self.lon_step, self.lat_step = grid_steps(51.34, 400)

    def test_nearby_vehicles_share_a_cell_and_sum(self):
        feats = [_vehicle(12.3700, 51.3400), _vehicle(12.3701, 51.3401)]
        grid = bin_features_to_grid(feats, self.lon_step, self.lat_step)
        self.assertEqual(len(grid), 1)
        cell = next(iter(grid.values()))
        self.assertEqual(cell["bicycle"], 2)

    def test_form_factors_tracked_separately(self):
        feats = [_vehicle(12.37, 51.34, "bicycle"), _vehicle(12.37, 51.34, "car")]
        grid = bin_features_to_grid(feats, self.lon_step, self.lat_step)
        cell = next(iter(grid.values()))
        self.assertEqual(cell["bicycle"], 1)
        self.assertEqual(cell["car"], 1)

    def test_zero_weight_station_skipped(self):
        grid = bin_features_to_grid([_station(12.37, 51.34, 0)], self.lon_step, self.lat_step)
        self.assertEqual(grid, {})


class GapGridTests(TestCase):
    def setUp(self):
        self.lon_step, self.lat_step = grid_steps(51.34, 400)
        # Three snapshots. Cell A has a vehicle every time (no gap); cell B has
        # one in only one of three snapshots (persistent gap).
        a = cell_key(12.37, 51.34, self.lon_step, self.lat_step)
        b = cell_key(12.45, 51.40, self.lon_step, self.lat_step)
        self.a, self.b = a, b
        self.grids = [
            {a: {"bicycle": 2}, b: {"bicycle": 1}},
            {a: {"bicycle": 1}},
            {a: {"bicycle": 3}},
        ]

    def test_gap_rate_reflects_absence(self):
        fc = compute_gap_grid(self.grids, self.lon_step, self.lat_step)
        self.assertEqual(fc["samples"], 3)
        by_cell = {f["properties"]["cell"]: f["properties"] for f in fc["features"]}
        # Cell A present in all 3 → gap_rate 0.
        self.assertEqual(by_cell[self.a]["availability_rate"], 1.0)
        self.assertEqual(by_cell[self.a]["gap_rate"], 0.0)
        self.assertEqual(by_cell[self.a]["mean_count"], 2.0)  # (2+1+3)/3
        self.assertEqual(by_cell[self.a]["max_count"], 3)
        # Cell B present in 1 of 3 → gap_rate ~0.667.
        self.assertEqual(by_cell[self.b]["present_samples"], 1)
        self.assertAlmostEqual(by_cell[self.b]["gap_rate"], 0.667, places=2)

    def test_form_factor_filter_excludes_other_modes(self):
        grids = [
            {self.a: {"bicycle": 1, "car": 1}},
            {self.a: {"bicycle": 2}},  # no car this snapshot
        ]
        fc = compute_gap_grid(grids, self.lon_step, self.lat_step, form_factors=["car"])
        props = fc["features"][0]["properties"]
        # Car present in 1 of 2 snapshots.
        self.assertEqual(props["present_samples"], 1)
        self.assertAlmostEqual(props["gap_rate"], 0.5, places=3)

    def test_empty_window_returns_zero_samples(self):
        fc = compute_gap_grid([], self.lon_step, self.lat_step)
        self.assertEqual(fc["samples"], 0)
        self.assertEqual(fc["features"], [])
