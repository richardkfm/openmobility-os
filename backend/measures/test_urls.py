"""URL routing regression tests for the measures app.

Guards against the slug catch-all (`measures/<slug:measure_slug>/`) swallowing
static measure sub-paths such as `measures/generate/`, which previously caused
the Generate button to 404 as a missing measure.
"""

from django.test import SimpleTestCase
from django.urls import resolve


class MeasuresUrlRoutingTests(SimpleTestCase):
    def test_generate_resolves_to_engine_trigger_not_detail(self):
        match = resolve("/demo/measures/generate/")
        self.assertEqual(match.url_name, "measures_generate")
        self.assertEqual(match.func.__name__, "generate_measures_view")

    def test_measure_slug_still_resolves_to_detail(self):
        match = resolve("/demo/measures/some-measure/")
        self.assertEqual(match.url_name, "measure_detail")
        self.assertEqual(match.kwargs["measure_slug"], "some-measure")
