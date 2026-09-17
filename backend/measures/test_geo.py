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


class LineLengthTests(TestCase):
    def test_a_known_east_west_line_measures_its_own_length(self):
        for lon, lat in CENTRES:
            with self.subTest(centre=(lon, lat)):
                m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat))
                geom = {
                    "type": "LineString",
                    "coordinates": [[lon, lat], [lon + 500.0 / m_per_deg_lon, lat]],
                }
                self.assertAlmostEqual(geo.line_length_m(geom), 500.0, delta=1.0)

    def test_a_north_south_line_measures_its_own_length(self):
        for lon, lat in CENTRES:
            with self.subTest(centre=(lon, lat)):
                geom = {
                    "type": "LineString",
                    "coordinates": [[lon, lat], [lon, lat + 500.0 / 111_132.0]],
                }
                self.assertAlmostEqual(geo.line_length_m(geom), 500.0, delta=1.0)

    def test_segments_add_up(self):
        lon, lat = CENTRES[0]
        step = 100.0 / 111_132.0
        geom = {
            "type": "LineString",
            "coordinates": [[lon, lat], [lon, lat + step], [lon, lat + 2 * step]],
        }
        self.assertAlmostEqual(geo.line_length_m(geom), 200.0, delta=1.0)

    def test_a_multilinestring_sums_its_parts(self):
        lon, lat = CENTRES[0]
        step = 100.0 / 111_132.0
        geom = {
            "type": "MultiLineString",
            "coordinates": [
                [[lon, lat], [lon, lat + step]],
                [[lon + 0.01, lat], [lon + 0.01, lat + step]],
            ],
        }
        self.assertAlmostEqual(geo.line_length_m(geom), 200.0, delta=1.0)

    def test_it_agrees_with_the_projector_at_every_scale_it_is_used_on(self):
        # The equirectangular shortcut exists to avoid projecting a whole street
        # network; it is only worth having if it matches the projection it
        # replaces. What is left is a small scale bias from the fixed
        # degrees-to-metres constants, not a drift that grows with distance —
        # so the same relative bound has to hold for a single street segment
        # and for a span across a whole city.
        for lon, lat in CENTRES:
            for d_lon, d_lat in ((0.004, 0.002), (0.1, 0.05)):
                with self.subTest(centre=(lon, lat), span=(d_lon, d_lat)):
                    end = (lon + d_lon, lat + d_lat)
                    geom = {"type": "LineString", "coordinates": [[lon, lat], list(end)]}
                    x, y = geo.make_projector((lon, lat))(*end)
                    projected = math.hypot(x, y)
                    self.assertAlmostEqual(
                        geo.line_length_m(geom), projected, delta=projected * 0.003
                    )

    def test_a_non_line_is_none_rather_than_zero(self):
        # "Not a line at all" and "zero metres long" are different answers, and
        # a caller that conflates them models cars onto a point.
        self.assertIsNone(geo.line_length_m({"type": "Point", "coordinates": [1, 2]}))
        self.assertIsNone(geo.line_length_m({"type": "LineString", "coordinates": []}))
        self.assertIsNone(geo.line_length_m({}))
        self.assertIsNone(geo.line_length_m(None))
