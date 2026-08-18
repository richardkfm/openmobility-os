"""Area engine tests.

Covers the two structural rules end to end:

* a segment where someone was killed or seriously injured is ranked ahead of a
  higher-volume slight-injury segment, and
* a segment whose rebuild does not fit stays in the plan instead of vanishing.

Plus the arithmetic that the projection rests on, and idempotency, since the
plan is regenerated from the UI and must not accumulate duplicates.
"""

import json

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Point, Polygon
from django.test import TestCase

from datasets.models import DataSource, NormalizedFeatureSet
from goals.models import AreaTarget
from measures import effects
from measures.area_clip import clip_features, inside_fraction
from measures.area_engine import build_area_plan
from measures.models import AreaPlanItem, Measure
from workspaces.models import FocusArea, Workspace

# A small area near the equator keeps the metric projection intuitive.
AREA_BBOX = (0.0, 0.0, 0.02, 0.02)


def _area_geom():
    return MultiPolygon(Polygon.from_bbox(AREA_BBOX), srid=4326)


def _street(name, coords, **props):
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {"name": name, **props},
    }


def _accident(lon, lat, *, severity, year=2023, modes=("cyclist",)):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "severity": severity,
            "year": year,
            "involved_modes": list(modes),
        },
    }


class AreaClipTests(TestCase):
    def test_point_inside_is_kept_and_outside_dropped(self):
        area = _area_geom()
        inside = _accident(0.01, 0.01, severity="fatal")
        outside = _accident(5.0, 5.0, severity="fatal")
        kept = clip_features([inside, outside], area)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["geometry"]["coordinates"], [0.01, 0.01])

    def test_street_crossing_the_boundary_is_kept_whole(self):
        """Intersection, not containment — a corridor must not be lost."""
        area = _area_geom()
        crossing = _street("Long Road", [[0.01, 0.01], [0.5, 0.01]])
        kept = clip_features([crossing], area)
        self.assertEqual(len(kept), 1)
        # Geometry untouched, so the feature's own length/lane properties stay valid.
        self.assertEqual(kept[0]["geometry"]["coordinates"][-1], [0.5, 0.01])

    def test_malformed_geometry_does_not_sink_the_clip(self):
        area = _area_geom()
        broken = {"type": "Feature", "geometry": {"type": "LineString"}}
        good = _accident(0.01, 0.01, severity="minor")
        self.assertEqual(len(clip_features([broken, good], area)), 1)

    def test_inside_fraction_is_proportional(self):
        area = _area_geom()
        half_out = _street("Half", [[0.01, 0.01], [0.03, 0.01]])
        fraction = inside_fraction(half_out, area)
        self.assertGreater(fraction, 0.4)
        self.assertLess(fraction, 0.6)

    def test_no_area_returns_everything(self):
        feats = [_accident(9.0, 9.0, severity="minor")]
        self.assertEqual(len(clip_features(feats, None)), 1)


class EffectCombinationTests(TestCase):
    def test_disjoint_shares_add_up(self):
        factor = {"low": 0.2, "central": 0.4, "high": 0.6}
        out = effects.combine([(0.5, factor), (0.25, factor)])
        self.assertAlmostEqual(out["central"], 0.3, places=4)
        self.assertAlmostEqual(out["share_addressed"], 0.75, places=4)

    def test_reduction_is_capped_at_one(self):
        factor = {"low": 1.0, "central": 1.0, "high": 1.0}
        out = effects.combine([(0.8, factor), (0.8, factor)])
        self.assertEqual(out["central"], 1.0)

    def test_missing_factor_contributes_nothing(self):
        out = effects.combine([(0.5, None)])
        self.assertEqual(out["central"], 0.0)

    def test_workspace_override_replaces_the_band_and_clears_review_flag(self):
        ws = Workspace(
            slug="x",
            name="X",
            settings={
                "effect_factors": {
                    "protected_bike_lane": {"low": 0.5, "central": 0.6, "high": 0.7}
                }
            },
        )
        factor = effects.factors_for(ws)["protected_bike_lane"]
        self.assertEqual(factor["central"], 0.6)
        self.assertTrue(factor["overridden"])
        self.assertFalse(factor["needs_review"])
        # The source survives the override rather than being blanked out.
        self.assertIn("title", factor["source"])


class AreaPlanEngineTests(TestCase):
    def setUp(self):
        self.ws = Workspace.objects.create(
            slug="testville",
            name="Testville",
            center=Point(0.01, 0.01, srid=4326),
            bounds=Polygon.from_bbox(AREA_BBOX),
        )
        self.area = FocusArea.objects.create(
            workspace=self.ws, slug="core", name="Core", geometry=_area_geom()
        )

    def _publish(self, layer_kind, features):
        source = DataSource.objects.create(
            workspace=self.ws,
            name=f"src-{layer_kind}",
            source_type=DataSource.SourceType.MANUAL,
            layer_kind=layer_kind,
        )
        NormalizedFeatureSet.objects.create(
            source=source,
            workspace=self.ws,
            layer_kind=layer_kind,
            feature_collection={"type": "FeatureCollection", "features": features},
            record_count=len(features),
        )

    def _target(self, indicator="cyclist_fatal_serious", **kwargs):
        target = AreaTarget(
            workspace=self.ws,
            focus_area=self.area,
            code="primary",
            indicator=indicator,
            target_mode=AreaTarget.TargetMode.ZERO,
            target_value=0,
            **kwargs,
        )
        target.save()
        return target

    def _two_streets(self):
        """A fatal street with one case, and a slight-injury street with four."""
        self._publish(
            "streets_with_speed",
            [
                _street("Fatal Street", [[0.005, 0.005], [0.005, 0.008]], maxspeed="50"),
                _street("Busy Street", [[0.015, 0.015], [0.015, 0.018]], maxspeed="50"),
            ],
        )
        self._publish(
            "accidents",
            [
                _accident(0.005, 0.006, severity="fatal"),
                _accident(0.015, 0.016, severity="minor"),
                _accident(0.015, 0.0165, severity="minor"),
                _accident(0.015, 0.017, severity="minor"),
                _accident(0.015, 0.0175, severity="minor"),
            ],
        )

    def test_empty_workspace_yields_an_empty_plan_not_an_error(self):
        plan = build_area_plan(self._target())
        self.assertEqual(plan.items.count(), 0)
        self.assertEqual(plan.projection["baseline"], 0.0)

    def test_severe_segment_outranks_a_higher_volume_slight_injury_segment(self):
        self._two_streets()
        # An all-severity indicator, so both streets qualify and only the
        # severity rule can decide the order.
        plan = build_area_plan(self._target(indicator="all_accidents"))
        items = list(plan.items.order_by("rank"))
        self.assertGreaterEqual(len(items), 2)
        first = items[0]
        self.assertEqual(
            first.affected_severity, AreaPlanItem.AffectedSeverity.FATAL_SERIOUS
        )
        # ...even though the slight-injury street carries four times the cases.
        busiest = max(items, key=lambda i: i.affected_baseline)
        self.assertGreater(busiest.affected_baseline, first.affected_baseline)
        self.assertGreater(busiest.rank, first.rank)

    def test_segment_that_does_not_fit_stays_in_the_plan(self):
        self._publish(
            "streets_with_speed",
            [
                _street(
                    "Narrow Lane",
                    [[0.005, 0.005], [0.005, 0.008]],
                    maxspeed="50",
                    width="3.2",
                    lanes="1",
                )
            ],
        )
        self._publish("accidents", [_accident(0.005, 0.006, severity="fatal")])
        plan = build_area_plan(self._target())
        sources = {i.space_source for i in plan.items.all()}
        self.assertTrue(plan.items.exists(), "a hard segment must not be dropped")
        self.assertTrue(
            sources & {"insufficient", "unknown", "not_needed"},
            f"expected an honest space verdict, got {sources}",
        )

    def test_residual_is_reported_and_vision_zero_is_not_met(self):
        self._two_streets()
        target = self._target()
        plan = build_area_plan(target)
        projection = plan.projection
        self.assertGreater(projection["baseline"], 0)
        self.assertIn("residual_absolute", projection)
        # Nothing in the catalogue eliminates all harm, so a zero target cannot
        # be met — and the plan must say so rather than round it away.
        self.assertGreater(projection["residual_absolute"], 0)
        self.assertFalse(projection["meets_target"])
        self.assertFalse(plan.reaches_target)

    def test_residual_uses_the_pessimistic_band(self):
        self._two_streets()
        plan = build_area_plan(self._target())
        projection = plan.projection
        self.assertEqual(projection["residual_absolute"], projection["low"])
        self.assertGreaterEqual(projection["low"], projection["central"])

    def test_segment_shares_are_per_year_and_never_exceed_the_whole(self):
        """The baseline is a rate per year; segment counts are raw totals over
        the window. If they are not put on the same footing, every segment
        overstates its share and the plan promises more than it can deliver."""
        # Five severe cases on five separate streets, spread over three years:
        # baseline is 5/3 per year, and each street holds exactly 1/3 per year,
        # i.e. one fifth of the baseline.
        streets, accidents = [], []
        for i in range(5):
            lat = 0.004 + i * 0.002
            streets.append(
                _street(f"Street {i}", [[0.005, lat - 0.0005], [0.005, lat + 0.0005]],
                        maxspeed="50")
            )
            accidents.append(
                _accident(0.005, lat, severity="serious", year=2021 + (i % 3))
            )
        self._publish("streets_with_speed", streets)
        self._publish("accidents", accidents)

        plan = build_area_plan(self._target())
        shares = [i.affected_baseline for i in plan.items.all()]
        self.assertTrue(shares, "expected the engine to propose segments")
        for share in shares:
            self.assertLessEqual(share, 1.0)
            self.assertAlmostEqual(share, 0.2, places=1)
        # Disjoint shares: the plan cannot address more harm than exists.
        self.assertLessEqual(round(sum(shares), 4), 1.0001)
        self.assertLessEqual(plan.projection["reduction"]["share_addressed"], 1.0)

    def test_projection_never_goes_below_zero_harm(self):
        self._two_streets()
        plan = build_area_plan(self._target(indicator="all_accidents"))
        for band in ("low", "central", "high"):
            self.assertGreaterEqual(plan.projection[band], 0.0)

    def test_regenerating_does_not_duplicate_measures(self):
        self._two_streets()
        target = self._target()
        build_area_plan(target)
        first_measures = Measure.objects.filter(focus_area=self.area).count()
        first_items = AreaPlanItem.objects.count()

        build_area_plan(target)
        self.assertEqual(Measure.objects.filter(focus_area=self.area).count(), first_measures)
        self.assertEqual(AreaPlanItem.objects.count(), first_items)

    def test_plan_records_its_assumptions_and_sources(self):
        self._two_streets()
        plan = build_area_plan(self._target())
        self.assertIn("effect_factors", plan.assumptions)
        self.assertIn("street_space", plan.assumptions)
        self.assertIn("years", plan.baseline)
        for source in plan.sources:
            self.assertTrue(source.get("title"))

    def test_measures_carry_the_space_budget_as_evidence(self):
        self._two_streets()
        plan = build_area_plan(self._target())
        item = plan.items.first()
        self.assertIsNotNone(item)
        self.assertIn("space_budget", item.measure.evidence)
        self.assertIn("share_of_area_baseline", item.measure.evidence)

    def test_parking_removal_is_quantified_when_the_data_is_there(self):
        self._publish(
            "streets_with_speed",
            [
                _street(
                    "Wide Street",
                    [[0.005, 0.005], [0.005, 0.008]],
                    maxspeed="50",
                    osm_id=42,
                    width="12.0",
                    lanes="2",
                )
            ],
        )
        self._publish("accidents", [_accident(0.005, 0.006, severity="fatal")])
        self._publish(
            "street_parking",
            [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[0.005, 0.005], [0.005, 0.008]],
                    },
                    "properties": {
                        "osm_id": 42,
                        "parking_present": True,
                        "side": "both",
                        "orientation": "parallel",
                        "length_m": 330.0,
                    },
                }
            ],
        )
        plan = build_area_plan(self._target())
        item = plan.items.first()
        self.assertIsNotNone(item)
        self.assertEqual(item.space_source, "parking_removal")
        self.assertGreater(item.parking_spaces_removed, 0)
        self.assertGreater(plan.space_budget["parking_spaces_removed"], 0)

    def test_geometry_of_generated_measures_is_valid_geojson(self):
        self._two_streets()
        plan = build_area_plan(self._target(indicator="all_accidents"))
        for item in plan.items.select_related("measure"):
            if item.measure.geometry is None:
                continue
            parsed = json.loads(item.measure.geometry.geojson)
            self.assertIn(parsed["type"], ("LineString", "MultiLineString"))
            self.assertIsNotNone(GEOSGeometry(json.dumps(parsed)))
