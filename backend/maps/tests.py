"""Unit tests for accident-density aggregation (snapping + cycling gaps).

Pure-function tests — no DB, no network — per the CLAUDE.md testing rule.
Geometry is built so that distances are easy to reason about: the workspace
centre is the projection anchor, and streets run along short east-west lines.
"""

from unittest import TestCase

from measures.accident_density import (
    compute_density_lines,
    find_cycling_gaps,
)

# Projection is anchored at (0, 0); near the origin 1° lon ≈ 111 km, so we use
# very small coordinate deltas to keep accidents within metres of the streets.
CENTER = (0.0, 0.0)


def _accident(lon, lat, *, severity="minor", year=2023, modes=None):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "severity": severity,
            "year": year,
            "involved_modes": modes or [],
        },
    }


def _street(name, coords, **props):
    props["name"] = name
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": props,
    }


# Two parallel east-west streets ~5.5 km apart in latitude (0.05° ≈ 5.5 km),
# each 0 → 0.02° long. Far enough apart that a point near one never snaps to
# the other.
STREET_A = _street("A Street", [[0.0, 0.0], [0.02, 0.0]])
STREET_B = _street("B Street", [[0.0, 0.05], [0.02, 0.05]])


class DensityLinesTests(TestCase):
    def test_snaps_to_nearest_street_and_weights_by_severity(self):
        accidents = [
            _accident(0.005, 0.00001, severity="fatal"),   # ~1 m from A
            _accident(0.010, 0.00001, severity="serious"),  # near A
            _accident(0.010, 0.05001, severity="minor"),    # near B
        ]
        fc = compute_density_lines(
            accidents, [STREET_A, STREET_B], center_lonlat=CENTER
        )
        by_name = {f["properties"]["street_name"]: f["properties"] for f in fc["features"]}
        self.assertIn("A Street", by_name)
        self.assertIn("B Street", by_name)
        # A: fatal(3) + serious(2) = 5 over 2 accidents
        self.assertEqual(by_name["A Street"]["severity_score"], 5)
        self.assertEqual(by_name["A Street"]["accident_count"], 2)
        # B: minor(1)
        self.assertEqual(by_name["B Street"]["severity_score"], 1)
        self.assertEqual(fc["metadata"]["method"], "snapped")
        self.assertEqual(fc["metadata"]["contributing_accidents"], 3)

    def test_point_beyond_snap_radius_is_dropped(self):
        # 0.01° lat ≈ 1.1 km away — far beyond the 25 m default snap radius.
        accidents = [_accident(0.005, 0.01, severity="fatal")]
        fc = compute_density_lines(accidents, [STREET_A], center_lonlat=CENTER)
        self.assertEqual(fc["features"], [])
        self.assertEqual(fc["metadata"]["unsnapped_accidents"], 1)

    def test_mode_filter_keeps_only_cyclist_accidents(self):
        accidents = [
            _accident(0.005, 0.00001, severity="serious", modes=["car"]),
            _accident(0.010, 0.00001, severity="serious", modes=["cyclist"]),
        ]
        fc = compute_density_lines(
            accidents, [STREET_A], center_lonlat=CENTER, modes=["cyclist"]
        )
        self.assertEqual(len(fc["features"]), 1)
        self.assertEqual(fc["features"][0]["properties"]["severity_score"], 2)
        self.assertEqual(fc["features"][0]["properties"]["accident_count"], 1)

    def test_year_filter(self):
        accidents = [
            _accident(0.005, 0.00001, severity="minor", year=2021),
            _accident(0.010, 0.00001, severity="minor", year=2023),
        ]
        fc = compute_density_lines(
            accidents, [STREET_A], center_lonlat=CENTER, years=[2023]
        )
        self.assertEqual(fc["features"][0]["properties"]["accident_count"], 1)

    def test_no_streets_returns_empty_with_reason(self):
        fc = compute_density_lines(
            [_accident(0.0, 0.0)], [], center_lonlat=CENTER
        )
        self.assertEqual(fc["features"], [])
        self.assertEqual(fc["metadata"]["method"], "none")
        self.assertEqual(fc["metadata"]["reason"], "no_streets")


class CyclingGapTests(TestCase):
    def _cyclist_accidents_on_a(self):
        # Enough cyclist accidents on A Street to clear the min_score=3 default.
        return [
            _accident(0.004, 0.00001, severity="serious", modes=["cyclist"]),
            _accident(0.008, 0.00001, severity="serious", modes=["cyclist"]),
        ]

    def test_flags_street_with_cyclist_accidents_and_no_bike_infra(self):
        gaps = find_cycling_gaps(
            self._cyclist_accidents_on_a(),
            [STREET_A],
            bike_ways=[],
            center_lonlat=CENTER,
        )
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["street_name"], "A Street")
        self.assertEqual(gaps[0]["severity_score"], 4)
        self.assertIsNone(gaps[0]["nearest_bike_m"])

    def test_skips_street_with_nearby_bike_infra(self):
        # Bike way running right along A Street → no gap.
        bike = _street("A cycleway", [[0.0, 0.00002], [0.02, 0.00002]])
        gaps = find_cycling_gaps(
            self._cyclist_accidents_on_a(),
            [STREET_A],
            bike_ways=[bike],
            center_lonlat=CENTER,
        )
        self.assertEqual(gaps, [])

    def test_ignores_non_cyclist_accidents(self):
        car_accidents = [
            _accident(0.004, 0.00001, severity="serious", modes=["car"]),
            _accident(0.008, 0.00001, severity="fatal", modes=["car"]),
        ]
        gaps = find_cycling_gaps(
            car_accidents, [STREET_A], bike_ways=[], center_lonlat=CENTER
        )
        self.assertEqual(gaps, [])
