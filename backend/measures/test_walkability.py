"""Tests for the walkability scorer.

Pure functions — no DB, no network — per the CLAUDE.md testing rule.

Most of these are not about the arithmetic. They are about the three honesty
rules the module is built on: a factor the data cannot speak to must never land
as a middling value, a street below the coverage threshold must have no class at
all, and a surveyed absence must never be overridden by something that merely
happens to be nearby.
"""

import json
import math
from dataclasses import dataclass, field
from unittest import TestCase

from measures import street_space
from measures import walkability as wk


# Leipzig and Auckland. Anything geometric runs against both, so nothing here
# can quietly depend on being in the northern hemisphere — or on a country whose
# speed limits happen to be tagged in km/h.
CENTRES = [(12.37, 51.34), (174.76, -36.85)]


@dataclass
class _Ws:
    """The one attribute this module reads off a workspace, and nothing else."""

    settings: dict = field(default_factory=dict)


def _street(center, *, osm_id=1, length_m=200.0, offset_m=0.0, **props):
    """A straight east-west way of a known length, near ``center``."""
    lon, lat = center
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat))
    m_per_deg_lat = 111_132.0
    lat0 = lat + offset_m / m_per_deg_lat
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[lon, lat0], [lon + length_m / m_per_deg_lon, lat0]],
        },
        "properties": {"osm_id": osm_id, "length_m": length_m, **props},
    }


def _footway(center, *, osm_id=1, scheme="street_tag", length_m=200.0, offset_m=0.0, **props):
    feat = _street(center, osm_id=osm_id, length_m=length_m, offset_m=offset_m)
    feat["properties"].update({"foot_scheme": scheme, **props})
    return feat


def _crossing(center, *, offset_m=0.0, along_m=0.0, **props):
    lon, lat = center
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat))
    m_per_deg_lat = 111_132.0
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [lon + along_m / m_per_deg_lon, lat + offset_m / m_per_deg_lat],
        },
        "properties": dict(props),
    }


def _build(center, streets, **kwargs):
    return wk.build_walkability(
        center_lonlat=center, street_features=streets, **kwargs
    )


def _only(fc):
    """The single feature in a one-street collection."""
    return fc["features"][0]["properties"]


# ─── Parameters ──────────────────────────────────────────────────────────────


class ParamsTests(TestCase):
    def test_defaults_come_back_untouched_without_a_workspace(self):
        self.assertEqual(wk.params_for(), wk.DEFAULT_PARAMS)

    def test_a_workspace_override_merges_one_level_deep(self):
        ws = _Ws(settings={"walkability": {"weights_safety": {"traffic_speed": 0.9}}})
        params = wk.params_for(ws)
        self.assertEqual(params["weights_safety"]["traffic_speed"], 0.9)
        # The siblings survive — that is what "one level deep" buys.
        self.assertEqual(params["weights_safety"]["lane_count"], 0.15)

    def test_overriding_does_not_mutate_the_defaults(self):
        ws = _Ws(settings={"walkability": {"min_coverage": 0.9}})
        wk.params_for(ws)
        self.assertEqual(wk.DEFAULT_PARAMS["min_coverage"], 0.5)

    def test_no_country_is_privileged_with_an_implicit_speed(self):
        """The whole point of the implicit-zone table being empty.

        If a default ever appears here, this feature has silently acquired a
        home country, and CLAUDE.md principle 1 is broken.
        """
        self.assertEqual(wk.DEFAULT_PARAMS["implicit_maxspeed_kmh"], {})


# ─── Individual factors ──────────────────────────────────────────────────────


def _ctx(**kwargs):
    base = {
        "params": wk.DEFAULT_PARAMS,
        "footway": None,
        "crossings": [],
        "crossing_layer_present": False,
        "obstacles": [],
        "obstacle_layer_present": False,
        "parking": None,
    }
    base.update(kwargs)
    return base


class FootwaySeparationTests(TestCase):
    def test_a_pavement_on_both_sides_scores_full(self):
        f = wk._f_footway_separation({}, _ctx(footway={"footway_present": True, "sides": "both"}))
        self.assertEqual(f.value, 1.0)

    def test_one_side_only_scores_below_both_sides(self):
        f = wk._f_footway_separation({}, _ctx(footway={"footway_present": True, "sides": "left"}))
        self.assertEqual(f.value, 0.8)

    def test_a_surveyed_absence_scores_zero_and_says_so(self):
        f = wk._f_footway_separation({}, _ctx(footway={"footway_present": False, "sides": "none"}))
        self.assertEqual(f.value, 0.0)
        self.assertEqual(f.confidence, "high")

    def test_silence_is_none_not_zero(self):
        f = wk._f_footway_separation({}, _ctx(footway={"footway_present": None, "sides": "unknown"}))
        self.assertIsNone(f.value)

    def test_no_record_at_all_is_none(self):
        self.assertIsNone(wk._f_footway_separation({}, _ctx()).value)

    def test_a_separately_mapped_pavement_counts_as_one_side_only(self):
        """The connector writes `sides: "both"` on a standalone footway to mean
        the way itself is walkable, not that the street has two pavements.
        Reading it the second way would invent a kerb nobody has mapped."""
        f = wk._f_footway_separation(
            {},
            _ctx(
                footway={
                    "footway_present": True,
                    "sides": "both",
                    "foot_scheme": "separate_way",
                }
            ),
        )
        self.assertEqual(f.value, 0.8)
        self.assertEqual(f.method, "separate_way_matched")

    def test_a_shared_space_does_not_need_a_pavement(self):
        f = wk._f_footway_separation({"highway": "pedestrian"}, _ctx())
        self.assertEqual(f.value, 0.9)
        self.assertEqual(f.method, "shared_space")


class TrafficSpeedTests(TestCase):
    def test_a_calm_street_scores_full(self):
        f = wk._f_traffic_speed({"maxspeed_kmh": 30.0, "maxspeed_source": "tagged"}, _ctx())
        self.assertEqual(f.value, 1.0)

    def test_a_fast_road_scores_zero(self):
        f = wk._f_traffic_speed({"maxspeed_kmh": 80.0, "maxspeed_source": "tagged"}, _ctx())
        self.assertEqual(f.value, 0.0)

    def test_between_the_bands_is_linear(self):
        f = wk._f_traffic_speed({"maxspeed_kmh": 50.0, "maxspeed_source": "tagged"}, _ctx())
        self.assertAlmostEqual(f.value, 0.5)

    def test_an_unrestricted_road_is_the_worst_case_not_a_gap(self):
        """`maxspeed=none` is a survey result. Scoring it 0 km/h would rank an
        autobahn as the calmest street in town."""
        f = wk._f_traffic_speed({"maxspeed_kmh": None, "maxspeed_source": "unlimited"}, _ctx())
        self.assertEqual(f.value, 0.0)
        self.assertEqual(f.confidence, "high")

    def test_an_unconfigured_implicit_zone_stays_unknown(self):
        f = wk._f_traffic_speed(
            {"maxspeed_kmh": None, "maxspeed_source": "implicit", "maxspeed_zone": "de:urban"},
            _ctx(),
        )
        self.assertIsNone(f.value)
        self.assertEqual(f.method, "implicit_zone_unresolved")

    def test_a_workspace_may_supply_its_own_zone_numbers(self):
        params = wk.params_for(
            _Ws(settings={"walkability": {"implicit_maxspeed_kmh": {"nz:urban": 50}}})
        )
        f = wk._f_traffic_speed(
            {"maxspeed_kmh": None, "maxspeed_source": "implicit", "maxspeed_zone": "nz:urban"},
            _ctx(params=params),
        )
        self.assertAlmostEqual(f.value, 0.5)
        self.assertEqual(f.confidence, "medium")

    def test_every_country_zone_behaves_the_same_out_of_the_box(self):
        out = [
            wk._f_traffic_speed(
                {"maxspeed_kmh": None, "maxspeed_source": "implicit", "maxspeed_zone": zone},
                _ctx(),
            ).value
            for zone in ("de:urban", "nz:urban", "gb:nsl_single", "fr:rural")
        ]
        self.assertEqual(out, [None, None, None, None])

    def test_an_unparsed_value_is_unknown(self):
        f = wk._f_traffic_speed({"maxspeed_kmh": None, "maxspeed_source": "unparsed"}, _ctx())
        self.assertIsNone(f.value)


class LaneCountTests(TestCase):
    def test_a_two_lane_street_scores_full(self):
        self.assertEqual(wk._f_lane_count({"lanes": 2}, _ctx()).value, 1.0)

    def test_more_lanes_score_worse(self):
        values = [wk._f_lane_count({"lanes": n}, _ctx()).value for n in (3, 4, 6)]
        self.assertEqual(values, [0.6, 0.3, 0.0])

    def test_an_untagged_lane_count_is_none(self):
        self.assertIsNone(wk._f_lane_count({}, _ctx()).value)


class CrossingFactorTests(TestCase):
    def test_no_crossings_layer_is_none_never_zero(self):
        f = wk._f_crossings({"length_m": 400.0}, _ctx(crossing_layer_present=False))
        self.assertIsNone(f.value)
        self.assertEqual(f.method, "layer_absent")

    def test_a_long_street_with_no_crossing_scores_zero(self):
        f = wk._f_crossings({"length_m": 400.0}, _ctx(crossing_layer_present=True))
        self.assertEqual(f.value, 0.0)

    def test_a_short_street_is_not_punished_for_having_none(self):
        f = wk._f_crossings({"length_m": 60.0}, _ctx(crossing_layer_present=True))
        self.assertEqual(f.value, 1.0)
        self.assertEqual(f.method, "shorter_than_target_spacing")

    def test_crossings_at_the_target_spacing_score_full(self):
        f = wk._f_crossings(
            {"length_m": 300.0},
            _ctx(crossing_layer_present=True, crossings=[{}, {}]),
        )
        self.assertEqual(f.value, 1.0)

    def test_a_signalised_crossing_counts_for_a_little_more(self):
        plain = wk._f_crossings(
            {"length_m": 600.0}, _ctx(crossing_layer_present=True, crossings=[{}])
        )
        signal = wk._f_crossings(
            {"length_m": 600.0},
            _ctx(crossing_layer_present=True, crossings=[{"has_signals": True}]),
        )
        self.assertGreater(signal.value, plain.value)

    def test_an_unmeasurable_street_is_none(self):
        f = wk._f_crossings({"length_m": None}, _ctx(crossing_layer_present=True))
        self.assertIsNone(f.value)


class ObstacleFactorTests(TestCase):
    def test_no_obstacle_layer_is_none(self):
        self.assertIsNone(wk._f_obstacles({}, _ctx(obstacle_layer_present=False)).value)

    def test_a_synced_layer_with_no_match_is_a_weak_pass(self):
        f = wk._f_obstacles({}, _ctx(obstacle_layer_present=True))
        self.assertEqual(f.value, 1.0)
        # The obstacle list is knowingly incomplete, so this never claims more.
        self.assertEqual(f.confidence, "low")

    def test_matched_obstacles_cost_the_street(self):
        f = wk._f_obstacles(
            {},
            _ctx(obstacle_layer_present=True, obstacles=[{"obstacle_type": "barrier"}]),
        )
        self.assertEqual(f.value, 0.5)

    def test_the_penalty_never_goes_below_zero(self):
        f = wk._f_obstacles(
            {}, _ctx(obstacle_layer_present=True, obstacles=[{}, {}, {}, {}, {}])
        )
        self.assertEqual(f.value, 0.0)


class FootwayWidthTests(TestCase):
    def test_a_comfortable_width_scores_full(self):
        f = wk._f_footway_width(
            {}, _ctx(footway={"width_m": 3.0, "width_source": "tagged"})
        )
        self.assertEqual(f.value, 1.0)

    def test_a_nominal_width_scores_zero(self):
        f = wk._f_footway_width(
            {}, _ctx(footway={"width_m": 1.2, "width_source": "tagged"})
        )
        self.assertEqual(f.value, 0.0)

    def test_an_untagged_width_is_never_estimated(self):
        """The one number this feature must not invent: there is no lane count
        to derive a pavement width from, and it drives the heaviest comfort
        weight."""
        f = wk._f_footway_width(
            {}, _ctx(footway={"width_m": None, "width_source": "unknown"})
        )
        self.assertIsNone(f.value)

    def test_a_width_marked_estimated_is_refused(self):
        f = wk._f_footway_width(
            {}, _ctx(footway={"width_m": 2.5, "width_source": "estimated"})
        )
        self.assertIsNone(f.value)


class KerbParkingTests(TestCase):
    def test_parking_on_the_pavement_scores_zero(self):
        f = wk._f_kerb_parking(
            {}, _ctx(parking={"parking_present": True, "parking_type": "on_kerb"})
        )
        self.assertEqual(f.value, 0.0)

    def test_parking_in_a_lane_does_not_cost_the_walker(self):
        f = wk._f_kerb_parking(
            {}, _ctx(parking={"parking_present": True, "parking_type": "lane"})
        )
        self.assertEqual(f.value, 1.0)

    def test_half_on_the_kerb_lands_between(self):
        f = wk._f_kerb_parking(
            {}, _ctx(parking={"parking_present": True, "parking_type": "half_on_kerb"})
        )
        self.assertEqual(f.value, 0.3)

    def test_a_surveyed_absence_of_parking_is_good_news(self):
        f = wk._f_kerb_parking({}, _ctx(parking={"parking_present": False}))
        self.assertEqual(f.value, 1.0)

    def test_silence_is_none(self):
        self.assertIsNone(wk._f_kerb_parking({}, _ctx()).value)

    def test_an_unrecognised_layout_is_not_guessed_at(self):
        f = wk._f_kerb_parking(
            {}, _ctx(parking={"parking_present": True, "parking_type": "something_new"})
        )
        self.assertIsNone(f.value)

    def test_every_layout_it_claims_to_know_is_in_range(self):
        for key, value in wk.KERB_PARKING_QUALITY.items():
            with self.subTest(parking_type=key):
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)


class StepFreeTests(TestCase):
    def test_steps_are_decisive(self):
        f = wk._f_step_free({}, _ctx(footway={"is_steps": True, "incline_pct": 0.0}))
        self.assertEqual(f.value, 0.0)

    def test_a_steep_incline_scores_low(self):
        f = wk._f_step_free({}, _ctx(footway={"incline_pct": 9.0}))
        self.assertEqual(f.value, 0.2)

    def test_a_descent_is_as_steep_as_a_climb(self):
        f = wk._f_step_free({}, _ctx(footway={"incline_pct": -9.0}))
        self.assertEqual(f.value, 0.2)

    def test_a_flush_kerb_reads_as_step_free(self):
        f = wk._f_step_free({}, _ctx(crossings=[{"kerb": "flush"}]))
        self.assertEqual(f.value, 1.0)

    def test_a_raised_kerb_binds_even_on_a_gentle_slope(self):
        """The worst element, not the average: one raised kerb stops a
        wheelchair however flat the rest is."""
        f = wk._f_step_free(
            {}, _ctx(footway={"incline_pct": 1.0}, crossings=[{"kerb": "raised"}])
        )
        self.assertEqual(f.value, 0.3)

    def test_silence_is_none(self):
        self.assertIsNone(wk._f_step_free({}, _ctx()).value)


class SurfaceTests(TestCase):
    def test_asphalt_scores_full(self):
        self.assertEqual(wk._f_surface({}, _ctx(footway={"surface": "asphalt"})).value, 1.0)

    def test_cobbles_score_poorly(self):
        self.assertEqual(wk._f_surface({}, _ctx(footway={"surface": "sett"})).value, 0.4)

    def test_smoothness_overrides_the_material(self):
        """Worn asphalt is not asphalt."""
        f = wk._f_surface({}, _ctx(footway={"surface": "asphalt", "smoothness": "bad"}))
        self.assertEqual(f.value, 0.4)
        self.assertEqual(f.method, "smoothness")

    def test_an_unknown_material_is_not_guessed_at(self):
        self.assertIsNone(wk._f_surface({}, _ctx(footway={"surface": "moon_dust"})).value)

    def test_silence_is_none(self):
        self.assertIsNone(wk._f_surface({}, _ctx()).value)


class LitTests(TestCase):
    def test_three_states_stay_three_states(self):
        self.assertEqual(wk._f_lit({}, _ctx(footway={"lit": True})).value, 1.0)
        self.assertEqual(wk._f_lit({}, _ctx(footway={"lit": False})).value, 0.0)
        self.assertIsNone(wk._f_lit({}, _ctx(footway={"lit": None})).value)


class NoFactorInventsAMiddleTests(TestCase):
    def test_an_empty_street_leaves_every_factor_silent(self):
        """The rule the whole module rests on, asserted across all ten at once:
        with no data at all, not one factor may return a value."""
        ctx = _ctx()
        for name, fn in wk.ALL_FACTORS.items():
            with self.subTest(factor=name):
                self.assertIsNone(fn({}, ctx).value)


# ─── Composition ─────────────────────────────────────────────────────────────


class ComposeTests(TestCase):
    def test_a_none_is_dropped_rather_than_scored_half(self):
        weights = {"a": 0.5, "b": 0.5}
        factors = {"a": wk.Factor(1.0, "x"), "b": wk.Factor(None, "silent")}
        score, coverage, unknowns = wk.compose(factors, weights, 0.0)
        # 0.5 would be the answer if the silent factor had been scored 0.5.
        self.assertEqual(score, 100.0)
        self.assertEqual(coverage, 0.5)
        self.assertEqual(unknowns, ["b"])

    def test_coverage_is_known_weight_over_total_weight(self):
        weights = {"a": 0.75, "b": 0.25}
        factors = {"a": wk.Factor(1.0, "x"), "b": wk.Factor(None, "silent")}
        _score, coverage, _unknowns = wk.compose(factors, weights, 0.0)
        self.assertAlmostEqual(coverage, 0.75)

    def test_below_min_coverage_there_is_no_score_at_all(self):
        weights = {"a": 0.2, "b": 0.8}
        factors = {"a": wk.Factor(1.0, "x"), "b": wk.Factor(None, "silent")}
        score, coverage, _unknowns = wk.compose(factors, weights, 0.5)
        self.assertIsNone(score)
        self.assertAlmostEqual(coverage, 0.2)

    def test_everything_silent_gives_no_score(self):
        factors = {"a": wk.Factor(None, "silent")}
        score, coverage, unknowns = wk.compose(factors, {"a": 1.0}, 0.0)
        self.assertIsNone(score)
        self.assertEqual(coverage, 0.0)
        self.assertEqual(unknowns, ["a"])

    def test_zero_total_weight_does_not_divide_by_zero(self):
        score, coverage, _unknowns = wk.compose({}, {}, 0.5)
        self.assertIsNone(score)
        self.assertEqual(coverage, 0.0)


class ClassifyTests(TestCase):
    def test_the_thresholds_are_inclusive_at_their_boundaries(self):
        t = wk.DEFAULT_PARAMS["class_thresholds"]
        self.assertEqual(wk.classify(70.0, t), "comfortable")
        self.assertEqual(wk.classify(69.9, t), "usable")
        self.assertEqual(wk.classify(50.0, t), "usable")
        self.assertEqual(wk.classify(49.9, t), "tight")
        self.assertEqual(wk.classify(30.0, t), "tight")
        self.assertEqual(wk.classify(29.9, t), "hostile")

    def test_no_score_is_its_own_class_not_a_middling_one(self):
        self.assertEqual(wk.classify(None, wk.DEFAULT_PARAMS["class_thresholds"]), "unknown")

    def test_bands_are_words(self):
        t = wk.DEFAULT_PARAMS["class_thresholds"]
        self.assertEqual(wk.band(80.0, t), "good")
        self.assertEqual(wk.band(55.0, t), "fair")
        self.assertEqual(wk.band(10.0, t), "poor")
        self.assertEqual(wk.band(None, t), "unknown")


# ─── The footway join ────────────────────────────────────────────────────────


class FootwayJoinTests(TestCase):
    def test_a_street_tag_record_matches_by_osm_id(self):
        for centre in CENTRES:
            with self.subTest(centre=centre):
                fc = _build(
                    centre,
                    [_street(centre, osm_id=7)],
                    footway_features=[
                        _footway(centre, osm_id=7, footway_present=True, sides="both")
                    ],
                )
                self.assertEqual(_only(fc)["footway_match"], "osm_id")

    def test_a_separate_pavement_is_picked_up_by_proximity(self):
        for centre in CENTRES:
            with self.subTest(centre=centre):
                fc = _build(
                    centre,
                    [_street(centre, osm_id=7)],
                    footway_features=[
                        _footway(
                            centre,
                            osm_id=7,
                            footway_present=None,
                            sides="separate",
                        ),
                        _footway(
                            centre,
                            osm_id=99,
                            scheme="separate_way",
                            offset_m=8.0,
                            footway_present=True,
                            sides="both",
                            width_m=3.0,
                            width_source="tagged",
                        ),
                    ],
                )
                props = _only(fc)
                self.assertEqual(props["footway_match"], "proximity")
                self.assertEqual(props["factors"]["footway_width"]["value"], 1.0)

    def test_a_proximity_match_never_claims_high_confidence(self):
        centre = CENTRES[0]
        fc = _build(
            centre,
            [
                _street(
                    centre,
                    osm_id=7,
                    lanes=2,
                    maxspeed_kmh=30.0,
                    maxspeed_source="tagged",
                )
            ],
            footway_features=[
                _footway(centre, osm_id=7, footway_present=None, sides="separate"),
                _footway(
                    centre,
                    osm_id=99,
                    scheme="separate_way",
                    offset_m=8.0,
                    footway_present=True,
                    sides="both",
                    width_m=3.0,
                    width_source="tagged",
                    surface="asphalt",
                    lit=True,
                ),
            ],
            crossing_features=[_crossing(centre, along_m=100.0)],
            obstacle_features=[],
            parking_features=[
                {
                    "type": "Feature",
                    "geometry": None,
                    "properties": {"osm_id": 7, "parking_present": False},
                }
            ],
        )
        props = _only(fc)
        self.assertEqual(props["footway_match"], "proximity")
        self.assertNotEqual(props["confidence"], "high")

    def test_a_surveyed_absence_is_never_overridden_by_a_nearby_line(self):
        """Evidence outranks proximity. This is the single most important
        assertion in the join: a street surveyed as having no pavement must not
        be rescued by a footway drawn eight metres away."""
        for centre in CENTRES:
            with self.subTest(centre=centre):
                fc = _build(
                    centre,
                    [_street(centre, osm_id=7)],
                    footway_features=[
                        _footway(centre, osm_id=7, footway_present=False, sides="none"),
                        _footway(
                            centre,
                            osm_id=99,
                            scheme="separate_way",
                            offset_m=8.0,
                            footway_present=True,
                            sides="both",
                        ),
                    ],
                )
                props = _only(fc)
                self.assertEqual(props["footway_match"], "osm_id")
                self.assertEqual(props["factors"]["footway_separation"]["value"], 0.0)

    def test_a_footway_beyond_the_snap_radius_is_not_claimed(self):
        centre = CENTRES[0]
        fc = _build(
            centre,
            [_street(centre, osm_id=7)],
            footway_features=[
                _footway(
                    centre,
                    osm_id=99,
                    scheme="separate_way",
                    offset_m=400.0,
                    footway_present=True,
                    sides="both",
                )
            ],
        )
        self.assertEqual(_only(fc)["footway_match"], "none")

    def test_a_street_with_no_record_and_no_neighbour_says_none(self):
        centre = CENTRES[0]
        fc = _build(centre, [_street(centre, osm_id=7)])
        self.assertEqual(_only(fc)["footway_match"], "none")


class CrossingJoinTests(TestCase):
    def test_a_crossing_on_the_street_is_counted(self):
        for centre in CENTRES:
            with self.subTest(centre=centre):
                fc = _build(
                    centre,
                    [_street(centre, osm_id=7, length_m=300.0)],
                    crossing_features=[
                        _crossing(centre, along_m=100.0, has_signals=True),
                        _crossing(centre, along_m=200.0),
                    ],
                )
                self.assertEqual(
                    _only(fc)["factors"]["crossings"]["inputs"]["count"], 2
                )

    def test_a_crossing_on_another_street_is_not_borrowed(self):
        centre = CENTRES[0]
        fc = _build(
            centre,
            [_street(centre, osm_id=7, length_m=300.0)],
            crossing_features=[_crossing(centre, along_m=100.0, offset_m=500.0)],
        )
        self.assertEqual(_only(fc)["factors"]["crossings"]["inputs"].get("count"), None)


# ─── The whole build ─────────────────────────────────────────────────────────


class BuildTests(TestCase):
    def test_a_street_network_alone_still_returns_a_collection(self):
        """A workspace with nothing but streets gets an honest answer, not an
        error: every street unknown, with the gaps named."""
        for centre in CENTRES:
            with self.subTest(centre=centre):
                fc = _build(centre, [_street(centre)])
                self.assertEqual(fc["type"], "FeatureCollection")
                props = _only(fc)
                self.assertEqual(props["walk_class"], "unknown")
                self.assertTrue(props["unknowns"])
                self.assertIsNone(props["score"])

    def test_an_empty_workspace_does_not_divide_by_zero(self):
        fc = _build(CENTRES[0], [])
        self.assertEqual(fc["features"], [])
        self.assertEqual(fc["coverage"], 0.0)
        self.assertEqual(fc["space_split_coverage"], 0.0)

    def test_an_unknown_street_names_what_it_is_missing(self):
        fc = _build(CENTRES[0], [_street(CENTRES[0])])
        unknowns = _only(fc)["unknowns"]
        self.assertIn("footway_separation", unknowns)
        self.assertIn("traffic_speed", unknowns)

    def test_a_well_mapped_calm_street_comes_out_comfortable(self):
        for centre in CENTRES:
            with self.subTest(centre=centre):
                fc = _build(
                    centre,
                    [
                        _street(
                            centre,
                            osm_id=7,
                            length_m=120.0,
                            lanes=2,
                            maxspeed_kmh=30.0,
                            maxspeed_source="tagged",
                        )
                    ],
                    footway_features=[
                        _footway(
                            centre,
                            osm_id=7,
                            footway_present=True,
                            sides="both",
                            width_m=3.0,
                            width_source="tagged",
                            surface="asphalt",
                            lit=True,
                            incline_pct=0.0,
                        )
                    ],
                    crossing_features=[_crossing(centre, along_m=60.0, kerb="flush")],
                    obstacle_features=[],
                    parking_features=[
                        {
                            "type": "Feature",
                            "geometry": None,
                            "properties": {"osm_id": 7, "parking_present": False},
                        }
                    ],
                )
                props = _only(fc)
                self.assertEqual(props["walk_class"], "comfortable")
                self.assertEqual(props["confidence"], "high")
                self.assertEqual(props["unknowns"], [])

    def test_a_fast_wide_street_with_no_pavement_comes_out_hostile(self):
        centre = CENTRES[0]
        fc = _build(
            centre,
            [
                _street(
                    centre,
                    osm_id=7,
                    length_m=600.0,
                    lanes=6,
                    maxspeed_kmh=80.0,
                    maxspeed_source="tagged",
                )
            ],
            footway_features=[
                _footway(centre, osm_id=7, footway_present=False, sides="none")
            ],
            crossing_features=[_crossing(centre, along_m=5000.0)],
        )
        self.assertEqual(_only(fc)["walk_class"], "hostile")

    def test_without_a_footways_layer_even_a_bad_road_stays_unknown(self):
        """Comfort is 40 percent of the picture. Without it no street can reach
        the coverage threshold, so a workspace that has not synced footways gets
        "not enough data" rather than a confident-looking verdict built on half
        the inputs. The collection's note says so."""
        centre = CENTRES[0]
        fc = _build(
            centre,
            [
                _street(
                    centre,
                    osm_id=7,
                    length_m=600.0,
                    lanes=6,
                    maxspeed_kmh=None,
                    maxspeed_source="unlimited",
                )
            ],
            crossing_features=[],
            obstacle_features=[],
        )
        props = _only(fc)
        self.assertEqual(props["walk_class"], "unknown")
        self.assertEqual(props["safety_band"], "poor")
        self.assertEqual(props["comfort_band"], "unknown")
        self.assertIn("footways layer", fc["note"])

    def test_counts_add_up_to_the_street_total(self):
        centre = CENTRES[0]
        streets = [_street(centre, osm_id=i, offset_m=i * 300.0) for i in range(5)]
        fc = _build(centre, streets)
        self.assertEqual(sum(fc["counts"].values()), fc["streets"])
        self.assertEqual(fc["streets"], 5)

    def test_the_class_filter_narrows_the_features_not_the_counts(self):
        centre = CENTRES[0]
        streets = [_street(centre, osm_id=i, offset_m=i * 300.0) for i in range(3)]
        fc = _build(centre, streets, classes=["comfortable"])
        self.assertEqual(fc["features"], [])
        # The counts still describe the whole network, so a legend can say how
        # much of it the filter is hiding.
        self.assertEqual(fc["counts"]["unknown"], 3)

    def test_safety_alone_is_not_enough_coverage_for_a_class(self):
        """A street with good safety data and no comfort data at all lands at
        0.45 coverage — under the threshold — so it is reported as unknown
        rather than classed on half the picture."""
        centre = CENTRES[0]
        fc = _build(
            centre,
            [
                _street(
                    centre, osm_id=7, lanes=2, maxspeed_kmh=30.0, maxspeed_source="tagged"
                )
            ],
            footway_features=[
                _footway(centre, osm_id=7, footway_present=True, sides="both")
            ],
        )
        props = _only(fc)
        self.assertEqual(props["walk_class"], "unknown")
        self.assertIsNone(props["score"])
        # The safety half is still computed and published, so a reader can see
        # what *is* known rather than being told only that something is missing.
        self.assertEqual(props["safety"], 100.0)
        self.assertEqual(props["safety_band"], "good")
        self.assertEqual(props["comfort_band"], "unknown")

    def test_the_numbers_are_in_the_payload_for_auditing(self):
        centre = CENTRES[0]
        fc = _build(
            centre,
            [
                _street(
                    centre,
                    osm_id=7,
                    length_m=120.0,
                    lanes=2,
                    maxspeed_kmh=30.0,
                    maxspeed_source="tagged",
                )
            ],
            footway_features=[
                _footway(
                    centre,
                    osm_id=7,
                    footway_present=True,
                    sides="both",
                    width_m=3.0,
                    width_source="tagged",
                    surface="asphalt",
                    lit=True,
                )
            ],
        )
        props = _only(fc)
        self.assertIsInstance(props["score"], float)
        self.assertIn("factors", props)
        self.assertIn("method", props["factors"]["traffic_speed"])

    def test_the_same_input_gives_byte_identical_output(self):
        centre = CENTRES[0]
        streets = [_street(centre, osm_id=i, offset_m=i * 60.0) for i in range(4)]
        footways = [
            _footway(centre, osm_id=i, footway_present=True, sides="both")
            for i in range(4)
        ]
        first = json.dumps(_build(centre, streets, footway_features=footways), sort_keys=True)
        second = json.dumps(_build(centre, streets, footway_features=footways), sort_keys=True)
        self.assertEqual(first, second)

    def test_the_collection_reports_which_layers_it_had(self):
        centre = CENTRES[0]
        fc = _build(centre, [_street(centre)], crossing_features=[_crossing(centre)])
        self.assertTrue(fc["layers_used"]["pedestrian_crossings"])
        self.assertFalse(fc["layers_used"]["footways"])

    def test_a_synced_but_empty_layer_is_not_the_same_as_no_layer(self):
        """"Nobody has looked" and "somebody looked and found none" are
        different claims, and only the second one may score the street."""
        centre = CENTRES[0]
        street = [_street(centre, osm_id=7, length_m=600.0)]
        absent = _build(centre, street, crossing_features=None)
        empty = _build(centre, street, crossing_features=[])
        self.assertIsNone(_only(absent)["factors"]["crossings"]["value"])
        self.assertEqual(_only(absent)["factors"]["crossings"]["method"], "layer_absent")
        self.assertEqual(_only(empty)["factors"]["crossings"]["value"], 0.0)

    def test_the_review_flag_and_source_travel_with_the_result(self):
        fc = _build(CENTRES[0], [_street(CENTRES[0])])
        self.assertTrue(fc["needs_review"])
        self.assertIn("title", fc["source"])

    def test_a_workspace_override_reaches_the_score(self):
        centre = CENTRES[0]
        ws = _Ws(settings={"walkability": {"class_thresholds": {"comfortable": 99}}})
        streets = [
            _street(centre, osm_id=7, lanes=2, maxspeed_kmh=30.0, maxspeed_source="tagged")
        ]
        footways = [_footway(centre, osm_id=7, footway_present=True, sides="both")]
        strict = _build(
            centre, streets, footway_features=footways, params=wk.params_for(ws)
        )
        self.assertNotEqual(_only(strict)["walk_class"], "comfortable")

    def test_only_walking_obstacles_are_considered(self):
        centre = CENTRES[0]
        cycling_only = {
            "type": "Feature",
            "geometry": None,
            "properties": {"osm_id": 7, "affects": "cycling", "obstacle_type": "tram_tracks"},
        }
        fc = _build(centre, [_street(centre, osm_id=7)], obstacle_features=[cycling_only])
        # The layer is present, so the factor is a pass — but the cycling-only
        # obstacle must not have been counted against the walker.
        self.assertEqual(_only(fc)["factors"]["obstacles"]["value"], 1.0)


# ─── The space split ─────────────────────────────────────────────────────────


class SpaceSplitTests(TestCase):
    def test_both_widths_known_gives_a_balance(self):
        foot, park, balance = wk.space_split(
            {"width_source": "tagged", "width_m": 2.0, "sides": "both"},
            {"parking_present": True, "orientation": "parallel", "side": "both"},
            street_params=street_space.DEFAULT_PARAMS,
        )
        self.assertEqual(foot, 4.0)
        self.assertEqual(park, 4.0)
        self.assertEqual(balance, 0.0)

    def test_more_pavement_than_parking_reads_positive(self):
        _foot, _park, balance = wk.space_split(
            {"width_source": "tagged", "width_m": 4.0, "sides": "both"},
            {"parking_present": True, "orientation": "parallel", "side": "left"},
            street_params=street_space.DEFAULT_PARAMS,
        )
        self.assertGreater(balance, 0.0)

    def test_more_parking_than_pavement_reads_negative(self):
        _foot, _park, balance = wk.space_split(
            {"width_source": "tagged", "width_m": 1.0, "sides": "left"},
            {"parking_present": True, "orientation": "perpendicular", "side": "both"},
            street_params=street_space.DEFAULT_PARAMS,
        )
        self.assertLess(balance, 0.0)

    def test_a_separately_mapped_pavement_is_not_counted_twice(self):
        foot_tag, _p, _b = wk.space_split(
            {"width_source": "tagged", "width_m": 2.0, "sides": "both"},
            {"parking_present": False},
            street_params=street_space.DEFAULT_PARAMS,
        )
        foot_sep, _p2, _b2 = wk.space_split(
            {
                "width_source": "tagged",
                "width_m": 2.0,
                "sides": "both",
                "foot_scheme": "separate_way",
            },
            {"parking_present": False},
            street_params=street_space.DEFAULT_PARAMS,
        )
        self.assertEqual(foot_tag, 4.0)
        self.assertEqual(foot_sep, 2.0)

    def test_an_untagged_pavement_width_yields_no_balance(self):
        foot, _park, balance = wk.space_split(
            {"width_source": "unknown", "width_m": None, "sides": "both"},
            {"parking_present": True, "orientation": "parallel", "side": "both"},
            street_params=street_space.DEFAULT_PARAMS,
        )
        self.assertIsNone(foot)
        self.assertIsNone(balance)

    def test_no_parking_record_yields_no_balance(self):
        _foot, park, balance = wk.space_split(
            {"width_source": "tagged", "width_m": 2.0, "sides": "both"},
            None,
            street_params=street_space.DEFAULT_PARAMS,
        )
        self.assertIsNone(park)
        self.assertIsNone(balance)

    def test_a_pavement_with_surveyed_no_parking_is_all_pedestrian(self):
        _foot, park, balance = wk.space_split(
            {"width_source": "tagged", "width_m": 2.0, "sides": "both"},
            {"parking_present": False},
            street_params=street_space.DEFAULT_PARAMS,
        )
        self.assertEqual(park, 0.0)
        self.assertEqual(balance, 1.0)

    def test_the_balance_stays_inside_minus_one_and_one(self):
        for width, orientation in ((0.5, "perpendicular"), (8.0, "parallel")):
            with self.subTest(width=width):
                _f, _p, balance = wk.space_split(
                    {"width_source": "tagged", "width_m": width, "sides": "both"},
                    {"parking_present": True, "orientation": orientation, "side": "both"},
                    street_params=street_space.DEFAULT_PARAMS,
                )
                self.assertGreaterEqual(balance, -1.0)
                self.assertLessEqual(balance, 1.0)

    def test_the_collection_reports_its_own_split_coverage(self):
        centre = CENTRES[0]
        fc = _build(
            centre,
            [_street(centre, osm_id=7), _street(centre, osm_id=8, offset_m=500.0)],
            footway_features=[
                _footway(
                    centre,
                    osm_id=7,
                    footway_present=True,
                    sides="both",
                    width_m=2.0,
                    width_source="tagged",
                )
            ],
            parking_features=[
                {
                    "type": "Feature",
                    "geometry": None,
                    "properties": {
                        "osm_id": 7,
                        "parking_present": True,
                        "orientation": "parallel",
                        "side": "left",
                    },
                }
            ],
            mode="space_split",
        )
        self.assertEqual(fc["space_split_coverage"], 0.5)
