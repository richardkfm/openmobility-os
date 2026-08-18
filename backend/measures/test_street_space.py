"""Street-space budget tests.

Pure functions — no DB, no network — per the CLAUDE.md testing rule.

The load-bearing case here is the last one: when the data does not state a
width, the module must say "unknown" rather than produce a number. These
figures are used to argue for removing people's parking, so a confident-looking
guess is worse than an admitted gap.
"""

from unittest import TestCase

from measures import street_space as ss


class ParkingEstimateTests(TestCase):
    def test_parallel_parking_uses_bay_length(self):
        # 100 m of kerb at 5.75 m per car.
        self.assertEqual(ss.estimated_parking_spaces(100, "parallel"), 17)

    def test_perpendicular_parking_fits_more_cars(self):
        self.assertGreater(
            ss.estimated_parking_spaces(100, "perpendicular"),
            ss.estimated_parking_spaces(100, "parallel"),
        )

    def test_missing_length_is_unknown_not_zero(self):
        self.assertIsNone(ss.estimated_parking_spaces(None))

    def test_zero_length_is_zero_not_unknown(self):
        self.assertEqual(ss.estimated_parking_spaces(0), 0)

    def test_unknown_orientation_falls_back_to_parallel(self):
        self.assertEqual(
            ss.estimated_parking_spaces(100, "herringbone"),
            ss.estimated_parking_spaces(100, "parallel"),
        )


class AvailableWidthTests(TestCase):
    def test_tagged_width_wins(self):
        width, confidence = ss.available_width({"width_m": 8.5, "lanes": 2})
        self.assertEqual(width, 8.5)
        self.assertEqual(confidence, "tagged")

    def test_lane_count_gives_an_estimate(self):
        width, confidence = ss.available_width({"lanes": 2})
        self.assertEqual(width, 6.0)
        self.assertEqual(confidence, "estimated")

    def test_no_width_and_no_lanes_is_unknown(self):
        width, confidence = ss.available_width({"highway": "residential"})
        self.assertIsNone(width)
        self.assertEqual(confidence, "unknown")

    def test_width_string_with_unit_is_parsed(self):
        width, confidence = ss.available_width({"width": "7.5 m"})
        self.assertEqual(width, 7.5)
        self.assertEqual(confidence, "tagged")


class PlanSpaceTests(TestCase):
    def _parking(self, length_m=100, orientation="parallel", side="right"):
        return {
            "properties": {
                "parking_present": True,
                "orientation": orientation,
                "side": side,
                "length_m": length_m,
            }
        }

    def test_parking_is_taken_before_a_traffic_lane(self):
        # Parking on both sides frees 4.0 m, which covers the 2.3 m a protected
        # lane needs — so no motor-traffic lane should be touched.
        budget = ss.plan_space(
            "protected_bike_lane",
            {"width_m": 9.0, "lanes": 2},
            parking_features=[self._parking(side="both")],
        )
        self.assertEqual(budget.space_source, "parking_removal")
        self.assertGreater(budget.parking_spaces_removed, 0)
        self.assertEqual(budget.car_lanes_reallocated, 0)

    def test_one_side_of_parking_alone_is_not_enough_and_a_lane_follows(self):
        # A single parallel lane of parking frees only 2.0 m of the 2.3 m
        # needed. The shortfall must be met by a traffic lane, and both costs
        # have to be reported — not just the larger one.
        budget = ss.plan_space(
            "protected_bike_lane",
            {"width_m": 9.0, "lanes": 2},
            parking_features=[self._parking(side="right")],
        )
        self.assertGreater(budget.parking_spaces_removed, 0)
        self.assertEqual(budget.car_lanes_reallocated, 1)
        self.assertEqual(budget.space_source, "lane_reallocation")

    def test_lane_is_reallocated_when_there_is_no_parking(self):
        budget = ss.plan_space(
            "protected_bike_lane", {"width_m": 9.0, "lanes": 3}, parking_features=[]
        )
        self.assertEqual(budget.space_source, "lane_reallocation")
        self.assertEqual(budget.car_lanes_reallocated, 1)

    def test_the_last_traffic_lane_is_never_taken(self):
        budget = ss.plan_space(
            "protected_bike_lane", {"width_m": 3.2, "lanes": 1}, parking_features=[]
        )
        self.assertEqual(budget.car_lanes_reallocated, 0)
        self.assertEqual(budget.space_source, "insufficient")

    def test_narrow_street_without_parking_reports_insufficient(self):
        budget = ss.plan_space(
            "protected_bike_lane", {"width_m": 4.0, "lanes": 1}, parking_features=[]
        )
        self.assertEqual(budget.space_source, "insufficient")

    def test_unknown_width_is_reported_as_unknown_never_guessed(self):
        budget = ss.plan_space(
            "protected_bike_lane", {"highway": "residential"}, parking_features=[]
        )
        self.assertEqual(budget.space_source, "unknown")
        self.assertIsNone(budget.available_width_m)
        self.assertEqual(budget.width_confidence, "unknown")
        self.assertTrue(budget.needs_site_check)

    def test_intervention_needing_no_width_is_not_blocked(self):
        budget = ss.plan_space("speed_limit_30", {"highway": "residential"})
        self.assertEqual(budget.space_source, "not_needed")

    def test_obstacles_are_carried_through(self):
        budget = ss.plan_space(
            "protected_bike_lane",
            {"width_m": 9.0, "lanes": 2},
            parking_features=[self._parking()],
            obstacles=[{"obstacle_type": "tram_track"}],
        )
        self.assertEqual(budget.obstacles[0]["obstacle_type"], "tram_track")


class WorkspaceOverrideTests(TestCase):
    class _Workspace:
        def __init__(self, settings):
            self.settings = settings

    def test_overrides_merge_over_defaults(self):
        ws = self._Workspace(
            {"street_space": {"car_lane_width_m": 3.5, "parking_space_length_m": {"parallel": 6.0}}}
        )
        params = ss.params_for(ws)
        self.assertEqual(params["car_lane_width_m"], 3.5)
        self.assertEqual(params["parking_space_length_m"]["parallel"], 6.0)
        # Untouched sub-keys survive the merge.
        self.assertEqual(params["parking_space_length_m"]["perpendicular"], 2.5)

    def test_no_workspace_yields_defaults(self):
        self.assertEqual(ss.params_for(None), ss.DEFAULT_PARAMS)
