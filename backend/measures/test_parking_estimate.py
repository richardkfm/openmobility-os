"""Tests for the parked-car estimator.

Pure functions — no DB, no network — per the CLAUDE.md testing rule. The point
of most of these is not the arithmetic but the honesty rules: a guess must stay
labelled as a guess, "we do not know" must stay distinct from "there is none",
and the same request must draw the same cars twice running.
"""

import math
from dataclasses import dataclass, field
from unittest import TestCase

from measures import parking_estimate as pe
from measures import street_space


# Leipzig and Auckland. Anything geometric runs against both, so nothing here
# can quietly depend on being in the northern hemisphere.
CENTRES = [(12.37, 51.34), (174.76, -36.85)]


@dataclass
class _Ws:
    """The two attributes this module reads off a workspace, and nothing else."""

    settings: dict = field(default_factory=dict)


def _line(center, length_m=100.0, osm_id=1):
    """A straight east-west way of a known length, near ``center``."""
    lon, lat = center
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat))
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[lon, lat], [lon + length_m / m_per_deg_lon, lat]],
        },
        "properties": {"osm_id": osm_id, "osm_type": "way", "length_m": length_m},
    }


def _square_lot(center, side_m=100.0, osm_id=9, **props):
    lon, lat = center
    m_per_deg_lat = 111_132.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat))
    dx = side_m / m_per_deg_lon
    dy = side_m / m_per_deg_lat
    ring = [
        [lon, lat],
        [lon + dx, lat],
        [lon + dx, lat + dy],
        [lon, lat + dy],
        [lon, lat],
    ]
    base = {
        "osm_id": osm_id,
        "osm_type": "way",
        "area_m2": side_m * side_m,
        "capacity": None,
        "capacity_source": "unknown",
        "parking_form": "surface",
        "access_class": "public",
        "levels": None,
    }
    base.update(props)
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": base,
    }


class ParamsTests(TestCase):
    def test_defaults_are_returned_untouched_without_a_workspace(self):
        p = pe.params_for()
        self.assertEqual(p["occupancy_rate"], 1.0)
        self.assertEqual(p["modelled_sides"], 1)

    def test_a_workspace_overrides_one_nested_key_without_losing_the_rest(self):
        ws = _Ws(settings={"parking_estimate": {"lot_area_per_space_m2": {"surface": 30.0}}})
        p = pe.params_for(ws)
        self.assertEqual(p["lot_area_per_space_m2"]["surface"], 30.0)
        # The forms the override did not mention survive.
        self.assertEqual(p["lot_area_per_space_m2"]["multi-storey"], 27.5)

    def test_overriding_does_not_mutate_the_module_defaults(self):
        ws = _Ws(settings={"parking_estimate": {"occupancy_rate": 0.5}})
        pe.params_for(ws)
        self.assertEqual(pe.DEFAULT_PARAMS["occupancy_rate"], 1.0)

    def test_the_catalogue_is_flagged_for_review(self):
        # These are plausible planning figures, not values checked against a
        # named standard. The flag is what tells the UI to say so.
        self.assertTrue(pe.DEFAULT_PARAMS["needs_review"])
        self.assertIn("title", pe.DEFAULT_PARAMS["source"])

    def test_capacity_is_the_default_not_occupancy(self):
        self.assertEqual(pe.DEFAULT_PARAMS["occupancy_rate"], 1.0)


class KerbEstimateTests(TestCase):
    def test_a_surveyed_kerb_counts_bays_along_its_length(self):
        est = pe.estimate_kerb(
            {"parking_present": True, "side": "right", "orientation": "parallel",
             "length_m": 100.0}
        )
        # 100 m x 0.8 coverage / 5.75 m per parallel bay = 13.
        self.assertEqual(est.count, 13)
        self.assertEqual(est.basis, "surveyed")
        self.assertEqual(est.confidence, "medium")

    def test_parking_on_both_sides_doubles_the_count(self):
        one = pe.estimate_kerb(
            {"parking_present": True, "side": "left", "orientation": "parallel",
             "length_m": 100.0}
        )
        both = pe.estimate_kerb(
            {"parking_present": True, "side": "both", "orientation": "parallel",
             "length_m": 100.0}
        )
        self.assertEqual(both.count, one.count * 2)

    def test_perpendicular_bays_fit_more_cars_than_parallel_ones(self):
        parallel = pe.estimate_kerb(
            {"parking_present": True, "side": "right", "orientation": "parallel",
             "length_m": 100.0}
        )
        perpendicular = pe.estimate_kerb(
            {"parking_present": True, "side": "right", "orientation": "perpendicular",
             "length_m": 100.0}
        )
        self.assertGreater(perpendicular.count, parallel.count)

    def test_a_surveyed_absence_is_zero_not_unknown(self):
        est = pe.estimate_kerb({"parking_present": False})
        self.assertEqual(est.count, 0)
        self.assertEqual(est.basis, "surveyed")
        self.assertEqual(est.confidence, "high")

    def test_silence_is_unknown_not_zero(self):
        # The whole feature hangs on this: None means "OSM does not say", and a
        # caller that collapses it into 0 has invented a finding.
        est = pe.estimate_kerb({})
        self.assertIsNone(est.count)
        self.assertEqual(est.basis, "unknown")

    def test_tagged_parking_without_a_length_is_unknown(self):
        est = pe.estimate_kerb({"parking_present": True, "side": "right"})
        self.assertIsNone(est.count)
        self.assertEqual(est.basis, "unknown")

    def test_the_kerb_coverage_factor_discounts_driveways_and_junctions(self):
        params = {**pe.DEFAULT_PARAMS, "kerb_coverage_factor": 1.0}
        full = pe.estimate_kerb(
            {"parking_present": True, "side": "right", "orientation": "parallel",
             "length_m": 100.0},
            params=params,
        )
        discounted = pe.estimate_kerb(
            {"parking_present": True, "side": "right", "orientation": "parallel",
             "length_m": 100.0}
        )
        self.assertGreater(full.count, discounted.count)

    def test_occupancy_rate_scales_the_count(self):
        params = {**pe.DEFAULT_PARAMS, "occupancy_rate": 0.5}
        est = pe.estimate_kerb(
            {"parking_present": True, "side": "right", "orientation": "parallel",
             "length_m": 100.0},
            params=params,
        )
        # 13 bays x 0.5; Python rounds the half to even, which is fine here —
        # an occupancy scenario is not a count anyone reads to the last car.
        self.assertEqual(est.count, 6)

    def test_the_bay_length_comes_from_the_street_space_catalogue(self):
        # Not restated here: overriding it there has to move this number too,
        # or a workspace's design standard would apply to plans but not to the
        # map drawn from the same streets.
        sp = {
            **street_space.DEFAULT_PARAMS,
            "parking_space_length_m": {"parallel": 10.0, "diagonal": 3.5,
                                       "perpendicular": 2.5},
        }
        est = pe.estimate_kerb(
            {"parking_present": True, "side": "right", "orientation": "parallel",
             "length_m": 100.0},
            street_params=sp,
        )
        self.assertEqual(est.count, 8)  # 100 * 0.8 / 10


class ModelledKerbTests(TestCase):
    def test_a_residential_street_gets_modelled_cars(self):
        est = pe.estimate_modelled_kerb({"highway": "residential", "length_m": 100.0})
        self.assertEqual(est.basis, "modelled")
        self.assertEqual(est.count, 13)
        self.assertEqual(est.confidence, "low")

    def test_a_trunk_road_is_not_modelled(self):
        est = pe.estimate_modelled_kerb({"highway": "trunk", "length_m": 500.0})
        self.assertIsNone(est.count)
        self.assertEqual(est.basis, "unknown")
        self.assertEqual(est.method, "street_class_not_modelled")

    def test_a_short_stub_gets_a_modelled_zero(self):
        est = pe.estimate_modelled_kerb({"highway": "residential", "length_m": 5.0})
        self.assertEqual(est.count, 0)
        self.assertEqual(est.basis, "modelled")

    def test_which_street_classes_are_modelled_is_a_workspace_parameter(self):
        params = {**pe.DEFAULT_PARAMS, "modelled_street_types": ["tertiary"]}
        self.assertEqual(
            pe.estimate_modelled_kerb({"highway": "tertiary", "length_m": 100.0},
                                      params=params).basis,
            "modelled",
        )
        self.assertEqual(
            pe.estimate_modelled_kerb({"highway": "residential", "length_m": 100.0},
                                      params=params).basis,
            "unknown",
        )

    def test_modelling_both_sides_doubles_the_count(self):
        params = {**pe.DEFAULT_PARAMS, "modelled_sides": 2}
        one = pe.estimate_modelled_kerb({"highway": "residential", "length_m": 100.0})
        two = pe.estimate_modelled_kerb({"highway": "residential", "length_m": 100.0},
                                        params=params)
        self.assertEqual(two.count, one.count * 2)


class LotEstimateTests(TestCase):
    def test_a_tagged_capacity_is_used_verbatim_and_counts_as_surveyed(self):
        est = pe.estimate_lot(
            {"capacity": 120, "capacity_source": "tagged", "area_m2": 100.0}
        )
        self.assertEqual(est.count, 120)
        self.assertEqual(est.basis, "surveyed")
        self.assertEqual(est.confidence, "high")

    def test_an_untagged_lot_is_modelled_from_its_footprint(self):
        est = pe.estimate_lot(
            {"capacity": None, "capacity_source": "unknown", "area_m2": 2500.0,
             "parking_form": "surface"}
        )
        self.assertEqual(est.count, 100)  # 2500 / 25
        self.assertEqual(est.basis, "modelled")

    def test_levels_multiply_a_multi_storey(self):
        est = pe.estimate_lot(
            {"capacity_source": "unknown", "area_m2": 2750.0,
             "parking_form": "multi-storey", "levels": 4}
        )
        self.assertEqual(est.count, 400)  # 2750 * 4 / 27.5

    def test_a_lot_with_neither_capacity_nor_area_is_unknown(self):
        est = pe.estimate_lot({"capacity_source": "unknown"})
        self.assertIsNone(est.count)
        self.assertEqual(est.basis, "unknown")

    def test_square_metres_per_space_is_a_workspace_parameter(self):
        params = {
            **pe.DEFAULT_PARAMS,
            "lot_area_per_space_m2": {**pe.DEFAULT_PARAMS["lot_area_per_space_m2"],
                                      "surface": 50.0},
        }
        est = pe.estimate_lot(
            {"capacity_source": "unknown", "area_m2": 2500.0, "parking_form": "surface"},
            params=params,
        )
        self.assertEqual(est.count, 50)

    def test_a_capacity_of_zero_is_a_surveyed_zero(self):
        est = pe.estimate_lot({"capacity": 0, "capacity_source": "tagged", "area_m2": 900.0})
        self.assertEqual(est.count, 0)
        self.assertEqual(est.basis, "surveyed")


class SeededRandomTests(TestCase):
    def test_the_same_key_gives_the_same_stream(self):
        self.assertEqual(
            [pe.seeded_random("way:42").random() for _ in range(5)],
            [pe.seeded_random("way:42").random() for _ in range(5)],
        )

    def test_different_keys_give_different_streams(self):
        self.assertNotEqual(
            pe.seeded_random("way:42").random(), pe.seeded_random("way:43").random()
        )


class ScatterAlongLineTests(TestCase):
    LINE = [(0.0, 0.0), (100.0, 0.0)]

    def test_it_places_the_requested_number_of_cars(self):
        pts = pe.scatter_along_line(
            self.LINE, 7, side="right", offset_m=4.0, jitter_m=0.0,
            rng=pe.seeded_random("k"),
        )
        self.assertEqual(len(pts), 7)

    def test_cars_are_spread_along_the_line_not_bunched_at_a_vertex(self):
        pts = pe.scatter_along_line(
            self.LINE, 4, side="right", offset_m=0.0, jitter_m=0.0,
            rng=pe.seeded_random("k"),
        )
        xs = sorted(p[0] for p in pts)
        self.assertEqual([round(x, 1) for x in xs], [12.5, 37.5, 62.5, 87.5])

    def test_no_car_sits_on_the_junction_at_either_end(self):
        pts = pe.scatter_along_line(
            self.LINE, 3, side="right", offset_m=0.0, jitter_m=0.0,
            rng=pe.seeded_random("k"),
        )
        xs = [p[0] for p in pts]
        self.assertGreater(min(xs), 0.0)
        self.assertLess(max(xs), 100.0)

    def test_the_side_decides_which_kerb_the_cars_sit_on(self):
        left = pe.scatter_along_line(
            self.LINE, 3, side="left", offset_m=4.0, jitter_m=0.0,
            rng=pe.seeded_random("k"),
        )
        right = pe.scatter_along_line(
            self.LINE, 3, side="right", offset_m=4.0, jitter_m=0.0,
            rng=pe.seeded_random("k"),
        )
        self.assertTrue(all(p[1] > 0 for p in left))
        self.assertTrue(all(p[1] < 0 for p in right))

    def test_both_sides_puts_cars_on_each_kerb(self):
        pts = pe.scatter_along_line(
            self.LINE, 6, side="both", offset_m=4.0, jitter_m=0.0,
            rng=pe.seeded_random("k"),
        )
        self.assertTrue(any(p[1] > 0 for p in pts))
        self.assertTrue(any(p[1] < 0 for p in pts))

    def test_the_same_seed_places_the_same_cars(self):
        a = pe.scatter_along_line(self.LINE, 5, side="right", offset_m=4.0,
                                  jitter_m=1.0, rng=pe.seeded_random("way:7"))
        b = pe.scatter_along_line(self.LINE, 5, side="right", offset_m=4.0,
                                  jitter_m=1.0, rng=pe.seeded_random("way:7"))
        self.assertEqual(a, b)

    def test_a_degenerate_line_places_nothing(self):
        self.assertEqual(
            pe.scatter_along_line([(0.0, 0.0)], 5, side="right", offset_m=4.0,
                                  jitter_m=0.0, rng=pe.seeded_random("k")),
            [],
        )
        self.assertEqual(
            pe.scatter_along_line([(0.0, 0.0), (0.0, 0.0)], 5, side="right",
                                  offset_m=4.0, jitter_m=0.0,
                                  rng=pe.seeded_random("k")),
            [],
        )


class ScatterInPolygonTests(TestCase):
    # A 50 m x 20 m lot, long side running east-west.
    LOT = [[(0.0, 0.0), (50.0, 0.0), (50.0, 20.0), (0.0, 20.0)]]

    def test_every_car_lands_inside_the_lot(self):
        pts = pe.scatter_in_polygon(self.LOT, 20, spacing_m=5.0,
                                    rng=pe.seeded_random("lot:1"))
        self.assertTrue(pts)
        for x, y in pts:
            self.assertTrue(0.0 <= x <= 50.0 and 0.0 <= y <= 20.0, (x, y))

    def test_it_stops_at_what_the_footprint_holds(self):
        # A 1000 m² lot at 5 m spacing has room for about 40 symbols, so asking
        # for 500 must not overlap them — the caller turns the shortfall into a
        # "one symbol stands for N cars" note instead.
        pts = pe.scatter_in_polygon(self.LOT, 500, spacing_m=5.0,
                                    rng=pe.seeded_random("lot:1"))
        self.assertLess(len(pts), 500)
        self.assertGreater(len(pts), 20)

    def test_a_hole_in_the_lot_holds_no_cars(self):
        rings = [
            [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
            [(40.0, 40.0), (60.0, 40.0), (60.0, 60.0), (40.0, 60.0)],
        ]
        pts = pe.scatter_in_polygon(rings, 200, spacing_m=5.0,
                                    rng=pe.seeded_random("lot:2"))
        self.assertTrue(pts)
        for x, y in pts:
            self.assertFalse(41.0 < x < 59.0 and 41.0 < y < 59.0, (x, y))

    def test_rows_follow_the_lots_own_long_side(self):
        # The same lot rotated 30 degrees must produce the same rotated layout,
        # not a north-south grid clipped to a diamond.
        angle = math.radians(30.0)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        rotated = [[(x * cos_a - y * sin_a, x * sin_a + y * cos_a)
                    for x, y in self.LOT[0]]]
        straight = pe.scatter_in_polygon(self.LOT, 12, spacing_m=5.0,
                                         rng=pe.seeded_random("lot:3"))
        turned = pe.scatter_in_polygon(rotated, 12, spacing_m=5.0,
                                       rng=pe.seeded_random("lot:3"))
        self.assertEqual(len(straight), len(turned))
        # Un-rotating the turned layout recovers the straight one.
        back = sorted(
            (round(x * cos_a + y * sin_a, 6), round(-x * sin_a + y * cos_a, 6))
            for x, y in turned
        )
        self.assertEqual(back, sorted((round(x, 6), round(y, 6))
                                      for x, y in straight))

    def test_the_same_seed_lays_out_the_same_lot(self):
        a = pe.scatter_in_polygon(self.LOT, 10, spacing_m=5.0,
                                  rng=pe.seeded_random("lot:4"))
        b = pe.scatter_in_polygon(self.LOT, 10, spacing_m=5.0,
                                  rng=pe.seeded_random("lot:4"))
        self.assertEqual(a, b)

    def test_a_degenerate_ring_places_nothing(self):
        self.assertEqual(
            pe.scatter_in_polygon([[(0.0, 0.0), (1.0, 1.0)]], 5, spacing_m=5.0,
                                  rng=pe.seeded_random("k")),
            [],
        )


class CollectPlacesTests(TestCase):
    def setUp(self):
        self.center = CENTRES[0]

    def test_a_surveyed_kerb_suppresses_the_modelled_one_on_the_same_way(self):
        street = _line(self.center, 200.0, osm_id=7)
        street["properties"]["highway"] = "residential"
        kerb = _line(self.center, 200.0, osm_id=7)
        kerb["properties"].update(
            {"parking_present": True, "side": "right", "orientation": "parallel"}
        )
        places = pe.collect_places(kerb_features=[kerb], street_features=[street])
        self.assertEqual(len(places), 1)
        self.assertEqual(places[0].estimate.basis, "surveyed")

    def test_a_surveyed_absence_also_suppresses_the_modelled_kerb(self):
        # A street surveyed as having no parking must not then be filled with
        # imaginary cars — that would overwrite evidence with an assumption.
        street = _line(self.center, 200.0, osm_id=8)
        street["properties"]["highway"] = "residential"
        kerb = _line(self.center, 200.0, osm_id=8)
        kerb["properties"]["parking_present"] = False
        places = pe.collect_places(kerb_features=[kerb], street_features=[street])
        self.assertEqual(places, [])

    def test_an_untagged_residential_street_is_modelled(self):
        street = _line(self.center, 200.0, osm_id=9)
        street["properties"]["highway"] = "residential"
        places = pe.collect_places(street_features=[street])
        self.assertEqual(len(places), 1)
        self.assertEqual(places[0].estimate.basis, "modelled")

    def test_include_filters_out_the_modelled_half(self):
        street = _line(self.center, 200.0, osm_id=10)
        street["properties"]["highway"] = "residential"
        places = pe.collect_places(street_features=[street], include=("surveyed",))
        self.assertEqual(places, [])

    def test_the_access_filter_applies_to_lots(self):
        public = _square_lot(self.center, 100.0, osm_id=1, access_class="public")
        private = _square_lot(self.center, 100.0, osm_id=2, access_class="private")
        places = pe.collect_places(
            lot_features=[public, private], access=["public"]
        )
        self.assertEqual([pl.access_class for pl in places], ["public"])

    def test_the_order_is_stable_regardless_of_input_order(self):
        a = _square_lot(self.center, 100.0, osm_id=1)
        b = _square_lot(self.center, 100.0, osm_id=2)
        forward = [pl.key for pl in pe.collect_places(lot_features=[a, b])]
        backward = [pl.key for pl in pe.collect_places(lot_features=[b, a])]
        self.assertEqual(forward, backward)


class BuildParkedCarsTests(TestCase):
    def _fixture(self, center):
        street = _line(center, 200.0, osm_id=100)
        street["properties"]["highway"] = "residential"
        kerb = _line(center, 200.0, osm_id=101)
        kerb["properties"].update(
            {"parking_present": True, "side": "both", "orientation": "parallel"}
        )
        lot = _square_lot(center, 100.0, osm_id=102)
        return {"kerb_features": [kerb], "street_features": [street],
                "lot_features": [lot]}

    def test_it_draws_points_and_counts_the_two_bases_apart(self):
        for center in CENTRES:
            with self.subTest(center=center):
                fc = pe.build_parked_cars(center_lonlat=center, **self._fixture(center))
                self.assertEqual(fc["type"], "FeatureCollection")
                self.assertTrue(fc["features"])
                self.assertGreater(fc["counts"]["surveyed"], 0)
                self.assertGreater(fc["counts"]["modelled"], 0)
                self.assertEqual(
                    fc["counts"]["total"],
                    fc["counts"]["surveyed"] + fc["counts"]["modelled"],
                )
                bases = {f["properties"]["basis"] for f in fc["features"]}
                self.assertEqual(bases, {"surveyed", "modelled"})
                for f in fc["features"]:
                    self.assertEqual(f["geometry"]["type"], "Point")

    def test_every_car_carries_its_basis_so_the_map_can_tell_them_apart(self):
        center = CENTRES[0]
        fc = pe.build_parked_cars(center_lonlat=center, **self._fixture(center))
        for f in fc["features"]:
            self.assertIn(f["properties"]["basis"], ("surveyed", "modelled"))
            self.assertIn(f["properties"]["origin"], ("kerb", "lot"))
            self.assertGreaterEqual(f["properties"]["represents"], 1)

    def test_the_same_request_draws_the_cars_in_the_same_places(self):
        center = CENTRES[1]
        a = pe.build_parked_cars(center_lonlat=center, **self._fixture(center))
        b = pe.build_parked_cars(center_lonlat=center, **self._fixture(center))
        self.assertEqual(
            [f["geometry"]["coordinates"] for f in a["features"]],
            [f["geometry"]["coordinates"] for f in b["features"]],
        )

    def test_cars_land_near_the_geometry_they_came_from(self):
        center = CENTRES[0]
        fc = pe.build_parked_cars(center_lonlat=center, **self._fixture(center))
        forward = pe.make_projector(center)
        for f in fc["features"]:
            lon, lat = f["geometry"]["coordinates"]
            x, y = forward(lon, lat)
            # The fixture spans a couple of hundred metres from the centre; a
            # car much further out than that means the projection round-trip
            # has gone wrong.
            self.assertLess(math.hypot(x, y), 400.0)

    def test_thinning_keeps_the_symbol_count_within_the_cap(self):
        center = CENTRES[0]
        fixture = self._fixture(center)
        fc = pe.build_parked_cars(center_lonlat=center, max_symbols=10, **fixture)
        self.assertLessEqual(fc["symbols"], 12)  # cap plus per-place rounding
        self.assertTrue(fc["truncated"])
        self.assertGreater(fc["represents"], 1)
        # The headline counts are untouched by thinning — only the drawing is.
        full = pe.build_parked_cars(center_lonlat=center, **fixture)
        self.assertEqual(fc["counts"], full["counts"])

    def test_an_unthinned_map_says_one_symbol_is_one_car(self):
        center = CENTRES[0]
        fc = pe.build_parked_cars(center_lonlat=center, **self._fixture(center))
        self.assertFalse(fc["truncated"])
        self.assertEqual(fc["represents"], 1)

    def test_a_multi_storey_records_the_cars_its_footprint_cannot_show(self):
        center = CENTRES[0]
        lot = _square_lot(
            center, 50.0, osm_id=200, parking_form="multi-storey", levels=8,
            area_m2=2500.0,
        )
        fc = pe.build_parked_cars(center_lonlat=center, lot_features=[lot])
        self.assertGreater(fc["counts"]["total"], fc["symbols"])
        self.assertTrue(any(f["properties"]["represents"] > 1 for f in fc["features"]))

    def test_no_input_gives_an_empty_but_well_formed_collection(self):
        fc = pe.build_parked_cars(center_lonlat=CENTRES[0])
        self.assertEqual(fc["features"], [])
        self.assertEqual(fc["counts"]["total"], 0)
        self.assertEqual(fc["represents"], 1)

    def test_the_review_flag_and_source_reach_the_response(self):
        fc = pe.build_parked_cars(center_lonlat=CENTRES[0])
        self.assertTrue(fc["needs_review"])
        self.assertIn("title", fc["source"])


class BuildParkingDensityTests(TestCase):
    def test_it_keeps_the_source_geometry_instead_of_re_binning_it(self):
        center = CENTRES[0]
        kerb = _line(center, 200.0, osm_id=1)
        kerb["properties"].update(
            {"parking_present": True, "side": "right", "orientation": "parallel"}
        )
        lot = _square_lot(center, 100.0, osm_id=2)
        fc = pe.build_parking_density(kerb_features=[kerb], lot_features=[lot])
        types = sorted(f["geometry"]["type"] for f in fc["features"])
        self.assertEqual(types, ["LineString", "Polygon"])

    def test_a_kerb_reports_cars_per_hundred_metres(self):
        center = CENTRES[0]
        kerb = _line(center, 200.0, osm_id=1)
        kerb["properties"].update(
            {"parking_present": True, "side": "right", "orientation": "parallel"}
        )
        fc = pe.build_parking_density(kerb_features=[kerb])
        props = fc["features"][0]["properties"]
        self.assertAlmostEqual(props["cars_per_100m"], props["cars"] * 100 / 200.0, places=1)
        self.assertIsNone(props["cars_per_1000m2"])

    def test_a_lot_reports_cars_per_thousand_square_metres(self):
        center = CENTRES[0]
        lot = _square_lot(center, 100.0, osm_id=2)
        fc = pe.build_parking_density(lot_features=[lot])
        props = fc["features"][0]["properties"]
        self.assertAlmostEqual(props["cars_per_1000m2"], 40.0, places=1)  # 1000 / 25
        self.assertIsNone(props["cars_per_100m"])

    def test_it_reports_the_same_totals_as_the_symbol_build(self):
        center = CENTRES[0]
        street = _line(center, 300.0, osm_id=3)
        street["properties"]["highway"] = "residential"
        symbols = pe.build_parked_cars(center_lonlat=center, street_features=[street])
        density = pe.build_parking_density(street_features=[street])
        self.assertEqual(symbols["counts"], density["counts"])


class StreetLayerFallbackTests(TestCase):
    """The modelled kerb must work off whichever street layer a workspace has.

    Only the street-space layers normalise a ``length_m``; the plain ``streets``
    layer carries raw OSM tags and a geometry. Requiring the heavier layer would
    mean the feature silently did nothing in most workspaces.
    """

    def test_a_street_without_a_normalised_length_still_gets_modelled_cars(self):
        center = CENTRES[0]
        street = _line(center, 200.0, osm_id=1)
        del street["properties"]["length_m"]
        street["properties"]["highway"] = "residential"
        places = pe.collect_places(street_features=[street])
        self.assertEqual(len(places), 1)
        self.assertEqual(places[0].estimate.basis, "modelled")
        self.assertAlmostEqual(places[0].estimate.inputs["length_m"], 200.0, delta=2.0)

    def test_a_normalised_length_is_preferred_over_measuring_the_geometry(self):
        center = CENTRES[0]
        street = _line(center, 200.0, osm_id=1)
        street["properties"]["length_m"] = 400.0
        street["properties"]["highway"] = "residential"
        places = pe.collect_places(street_features=[street])
        self.assertEqual(places[0].estimate.inputs["length_m"], 400.0)

    def test_density_reports_per_100m_off_the_measured_length(self):
        center = CENTRES[0]
        street = _line(center, 200.0, osm_id=1)
        del street["properties"]["length_m"]
        street["properties"]["highway"] = "residential"
        fc = pe.build_parking_density(street_features=[street])
        self.assertIsNotNone(fc["features"][0]["properties"]["cars_per_100m"])
