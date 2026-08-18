"""Area-target tests, with the ethical rules as regression tests.

The rules under test here are not style preferences — they are the reason the
feature is safe to ship. A target that declares a share of road deaths
acceptable must be impossible to store, and a plan that still leaves people
being killed must never render as "done". Both are asserted below so a later
refactor cannot quietly relax them.
"""

from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.exceptions import ValidationError
from django.test import TestCase

from goals import indicators
from goals.models import AreaTarget
from workspaces.models import FocusArea, Workspace


def _square(x=0.0, y=0.0, size=0.01):
    return MultiPolygon(
        Polygon.from_bbox((x, y, x + size, y + size)), srid=4326
    )


class VisionZeroTargetTests(TestCase):
    def setUp(self):
        self.ws = Workspace.objects.create(slug="testville", name="Testville")
        self.area = FocusArea.objects.create(
            workspace=self.ws, slug="core", name="Core", geometry=_square()
        )

    def _target(self, **kwargs):
        defaults = {
            "workspace": self.ws,
            "focus_area": self.area,
            "code": "primary",
            "indicator": "cyclist_fatal_serious",
            "target_mode": AreaTarget.TargetMode.ZERO,
            "target_value": 0,
        }
        return AreaTarget(**{**defaults, **kwargs})

    def test_percentage_target_on_deaths_is_rejected(self):
        """'90 % fewer deaths' declares the other 10 % acceptable. Refuse it."""
        with self.assertRaises(ValidationError) as ctx:
            self._target(
                target_mode=AreaTarget.TargetMode.PERCENT, target_value=90
            ).save()
        self.assertIn("target_mode", ctx.exception.message_dict)

    def test_nonzero_absolute_target_on_deaths_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._target(
                target_mode=AreaTarget.TargetMode.ABSOLUTE, target_value=2
            ).save()

    def test_zero_target_on_deaths_is_accepted(self):
        target = self._target()
        target.save()
        self.assertEqual(target.target_value, 0)
        self.assertTrue(target.is_vision_zero)

    def test_percentage_target_is_allowed_for_slight_injury_indicators(self):
        target = self._target(
            indicator="cyclist_accidents_all",
            target_mode=AreaTarget.TargetMode.PERCENT,
            target_value=40,
        )
        target.save()
        self.assertEqual(target.target_value, 40)
        self.assertFalse(target.is_vision_zero)

    def test_unknown_indicator_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._target(indicator="not_a_real_indicator").save()

    def test_every_fatal_or_serious_indicator_is_flagged_vision_zero(self):
        """A new indicator counting deaths must not slip in unflagged."""
        for key, spec in indicators.INDICATORS.items():
            if "fatal" in key or "serious" in key:
                self.assertEqual(
                    spec["harm_class"],
                    "fatal_or_serious",
                    f"{key} counts severe harm but is not flagged as Vision Zero",
                )
                self.assertTrue(indicators.is_vision_zero(key))


class IndicatorCatalogueTests(TestCase):
    def test_baseline_counts_per_year_over_the_window(self):
        features = [
            _accident(2021, "serious", ["cyclist"]),
            _accident(2022, "serious", ["cyclist"]),
            _accident(2023, "fatal", ["cyclist"]),
        ]
        value, meta = indicators.compute_baseline(
            "cyclist_fatal_serious", {"accidents": features}
        )
        self.assertEqual(meta["years"], [2021, 2022, 2023])
        self.assertEqual(meta["matched_cases"], 3)
        self.assertEqual(value, 1.0)

    def test_slight_injuries_are_excluded_from_a_severe_indicator(self):
        features = [
            _accident(2023, "minor", ["cyclist"]),
            _accident(2023, "fatal", ["cyclist"]),
        ]
        _value, meta = indicators.compute_baseline(
            "cyclist_fatal_serious", {"accidents": features}
        )
        self.assertEqual(meta["matched_cases"], 1)

    def test_mode_filter_applies(self):
        features = [
            _accident(2023, "serious", ["car"]),
            _accident(2023, "serious", ["cyclist"]),
        ]
        _value, meta = indicators.compute_baseline(
            "cyclist_fatal_serious", {"accidents": features}
        )
        self.assertEqual(meta["matched_cases"], 1)

    def test_thin_evidence_is_marked_not_robust(self):
        features = [_accident(2023, "fatal", ["cyclist"])]
        _value, meta = indicators.compute_baseline(
            "cyclist_fatal_serious", {"accidents": features}
        )
        self.assertFalse(meta["robust"])

    def test_indicators_are_gated_by_available_layers(self):
        self.assertEqual(indicators.available_indicators([]), [])
        self.assertIn(
            "cyclist_fatal_serious", indicators.available_indicators(["accidents"])
        )

    def test_no_accidents_yields_zero_not_an_error(self):
        value, meta = indicators.compute_baseline("all_accidents", {})
        self.assertEqual(value, 0.0)
        self.assertEqual(meta["matched_cases"], 0)


def _accident(year, severity, modes):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
        "properties": {
            "year": year,
            "severity": severity,
            "involved_modes": modes,
        },
    }
