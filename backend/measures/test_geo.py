"""Tests for the shared metric-geometry helpers.

Pure functions — no DB, no network — per the CLAUDE.md testing rule.
"""

import math
from unittest import TestCase

from measures import geo


# A 100 m x 100 m square in projected metres. Listed anticlockwise; several
# tests re-list it the other way round to prove winding order is irrelevant.
SQUARE = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]

# Somewhere in Leipzig, and somewhere in Auckland. Every geometry test runs
# against both: the projection is anchored on the workspace centre precisely so
# that nothing here is correct only in the northern hemisphere.
CENTRES = [(12.37, 51.34), (174.76, -36.85)]


class ProjectorTests(TestCase):
    def test_the_centre_projects_to_the_origin(self):
        for centre in CENTRES:
            with self.subTest(centre=centre):
                x, y = geo.make_projector(centre)(*centre)
                self.assertAlmostEqual(x, 0.0, places=6)
                self.assertAlmostEqual(y, 0.0, places=6)

    def test_projecting_and_back_returns_the_original_point(self):
        for centre in CENTRES:
            with self.subTest(centre=centre):
                forward = geo.make_projector(centre)
                inverse = geo.make_inverse_projector(centre)
                lon_in, lat_in = centre[0] + 0.01, centre[1] + 0.01
                lon_out, lat_out = inverse(*forward(lon_in, lat_in))
                self.assertAlmostEqual(lon_out, lon_in, places=9)
                self.assertAlmostEqual(lat_out, lat_in, places=9)

    def test_a_known_distance_comes_back_in_metres(self):
        """One degree of latitude is ~111 km anywhere, so this is a real check
        on the projection rather than a restatement of it."""
        for centre in CENTRES:
            with self.subTest(centre=centre):
                forward = geo.make_projector(centre)
                _, y0 = forward(*centre)
                _, y1 = forward(centre[0], centre[1] + 1.0)
                self.assertAlmostEqual(abs(y1 - y0), 111_000, delta=1_500)


class PolygonAreaTests(TestCase):
    def test_area_of_a_known_square(self):
        self.assertAlmostEqual(geo.polygon_area_m2(SQUARE), 10_000.0)

    def test_winding_order_does_not_change_the_area(self):
        self.assertAlmostEqual(
            geo.polygon_area_m2(list(reversed(SQUARE))),
            geo.polygon_area_m2(SQUARE),
        )

    def test_a_closed_ring_is_not_counted_twice(self):
        """GeoJSON repeats the first point as the last; the shoelace already
        wraps around, so the duplicate must not add a phantom edge."""
        self.assertAlmostEqual(geo.polygon_area_m2([*SQUARE, SQUARE[0]]), 10_000.0)

    def test_a_degenerate_ring_has_no_area(self):
        self.assertEqual(geo.polygon_area_m2([]), 0.0)
        self.assertEqual(geo.polygon_area_m2([(0.0, 0.0), (1.0, 1.0)]), 0.0)
        self.assertEqual(geo.polygon_area_m2(None), 0.0)


class PointInRingTests(TestCase):
    def test_inside_and_outside_a_square(self):
        self.assertTrue(geo.point_in_ring(50.0, 50.0, SQUARE))
        self.assertFalse(geo.point_in_ring(150.0, 50.0, SQUARE))
        self.assertFalse(geo.point_in_ring(50.0, -50.0, SQUARE))

    def test_a_concave_ring_excludes_its_notch(self):
        """An L shape: the missing quadrant must read as outside, which a
        bounding-box test would get wrong."""
        l_shape = [
            (0.0, 0.0), (100.0, 0.0), (100.0, 50.0),
            (50.0, 50.0), (50.0, 100.0), (0.0, 100.0),
        ]
        self.assertTrue(geo.point_in_ring(25.0, 25.0, l_shape))
        self.assertTrue(geo.point_in_ring(25.0, 75.0, l_shape))
        self.assertFalse(geo.point_in_ring(75.0, 75.0, l_shape))

    def test_a_degenerate_ring_contains_nothing(self):
        self.assertFalse(geo.point_in_ring(0.0, 0.0, []))
        self.assertFalse(geo.point_in_ring(0.0, 0.0, [(0.0, 0.0), (1.0, 1.0)]))


class LongestEdgeBearingTests(TestCase):
    def test_a_wide_rectangle_points_along_its_long_side(self):
        rect = [(0.0, 0.0), (200.0, 0.0), (200.0, 50.0), (0.0, 50.0)]
        self.assertAlmostEqual(geo.longest_edge_bearing(rect), 0.0)

    def test_a_tall_rectangle_points_up(self):
        rect = [(0.0, 0.0), (50.0, 0.0), (50.0, 200.0), (0.0, 200.0)]
        self.assertAlmostEqual(geo.longest_edge_bearing(rect), math.pi / 2, places=6)

    def test_a_diagonal_bar_is_reported_at_its_angle(self):
        bar = [(0.0, 0.0), (100.0, 100.0), (95.0, 105.0), (-5.0, 5.0)]
        self.assertAlmostEqual(
            geo.longest_edge_bearing(bar), math.radians(45.0), places=6
        )

    def test_the_result_is_an_axis_not_a_direction(self):
        """Reversing the winding must not rotate a generated grid by 180
        degrees, so the angle is folded into [0, pi)."""
        rect = [(0.0, 0.0), (200.0, 0.0), (200.0, 50.0), (0.0, 50.0)]
        forward = geo.longest_edge_bearing(rect)
        backward = geo.longest_edge_bearing(list(reversed(rect)))
        self.assertAlmostEqual(forward, backward, places=6)
        for ring in (rect, list(reversed(rect))):
            angle = geo.longest_edge_bearing(ring)
            self.assertGreaterEqual(angle, 0.0)
            self.assertLess(angle, math.pi)

    def test_a_degenerate_ring_has_no_bearing(self):
        self.assertEqual(geo.longest_edge_bearing([]), 0.0)
        self.assertEqual(geo.longest_edge_bearing([(0.0, 0.0)]), 0.0)
