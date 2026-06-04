"""Tests for workspace management commands.

Covers the `seed_unfallatlas` command end-to-end without hitting the network.
"""

from __future__ import annotations

from io import StringIO
from unittest import mock

from django.contrib.gis.geos import Polygon
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from datasets.models import DataSource
from workspaces.management.commands.seed_unfallatlas import (
    _disable_demo_accidents,
    _parse_years,
)
from workspaces.models import Workspace


class ParseYearsTests(TestCase):
    def test_single_year(self):
        self.assertEqual(_parse_years("2024"), [2024])

    def test_comma_list(self):
        self.assertEqual(_parse_years("2021,2023,2024"), [2021, 2023, 2024])

    def test_range(self):
        self.assertEqual(_parse_years("2021-2024"), [2021, 2022, 2023, 2024])

    def test_descending_range_normalized(self):
        self.assertEqual(_parse_years("2024-2021"), [2021, 2022, 2023, 2024])

    def test_dedup_and_sort(self):
        self.assertEqual(_parse_years("2024,2021,2024"), [2021, 2024])

    def test_blank_returns_empty(self):
        self.assertEqual(_parse_years(""), [])
        self.assertEqual(_parse_years("   "), [])

    def test_invalid_returns_empty(self):
        self.assertEqual(_parse_years("not-years"), [])
        self.assertEqual(_parse_years("2021,abc"), [])


class DisableDemoAccidentsTests(TestCase):
    def setUp(self):
        self.ws = Workspace.objects.create(
            slug="testtown",
            name="Test Town",
            country_code="DE",
            language_code="de",
            timezone="Europe/Berlin",
            bounds=Polygon.from_bbox((12.0, 51.0, 13.0, 52.0)),
        )

    def _accident_source(self, name, source_type=DataSource.SourceType.MANUAL, attribution=""):
        return DataSource.objects.create(
            workspace=self.ws,
            name=name,
            source_type=source_type,
            layer_kind=DataSource.LayerKind.ACCIDENTS,
            attribution=attribution,
        )

    def test_only_demo_named_manual_accident_sources_are_removed(self):
        keeper_curated = self._accident_source("Manuelle Zusatzdaten Bürgermeldung")
        keeper_unfallat = self._accident_source(
            "Unfallatlas 2024", source_type="unfallat"
        )
        target_demo_de = self._accident_source("Beispiel — Unfälle (Demo)")
        target_demo_en = self._accident_source("Example accidents")
        target_attr = self._accident_source(
            "Crowd-curated points", attribution="Illustrative demo data only"
        )

        removed = _disable_demo_accidents(self.ws)
        self.assertEqual(removed, 3)

        remaining = set(self.ws.data_sources.values_list("name", flat=True))
        self.assertIn(keeper_curated.name, remaining)
        self.assertIn(keeper_unfallat.name, remaining)
        self.assertNotIn(target_demo_de.name, remaining)
        self.assertNotIn(target_demo_en.name, remaining)
        self.assertNotIn(target_attr.name, remaining)


class SeedUnfallatlasCommandTests(TestCase):
    def setUp(self):
        self.ws = Workspace.objects.create(
            slug="leipzig",
            name="Leipzig",
            country_code="DE",
            language_code="de",
            timezone="Europe/Berlin",
            bounds=Polygon.from_bbox((12.295, 51.236, 12.549, 51.443)),
        )

    def _call(self, **kwargs):
        out = StringIO()
        err = StringIO()
        call_command("seed_unfallatlas", stdout=out, stderr=err, **kwargs)
        return out.getvalue() + err.getvalue()

    def test_missing_workspace_raises_command_error(self):
        with self.assertRaises(CommandError) as ctx:
            self._call(workspace="ghost", years="2024", **{"no_sync": True})
        self.assertIn("not found", str(ctx.exception))

    def test_workspace_without_bounds_raises(self):
        ws = Workspace.objects.create(
            slug="boundsless",
            name="No Bounds",
            country_code="DE",
            language_code="de",
            timezone="Europe/Berlin",
        )
        with self.assertRaises(CommandError) as ctx:
            self._call(workspace=ws.slug, years="2024", **{"no_sync": True})
        self.assertIn("bounding box", str(ctx.exception))

    def test_url_pattern_path_creates_one_source_per_year(self):
        self._call(
            workspace="leipzig",
            years="2023-2024",
            url_pattern="https://example.org/u/{year}.csv",
            **{"no_sync": True},
        )
        sources = list(
            self.ws.data_sources.filter(source_type="unfallat").order_by("name")
        )
        self.assertEqual([s.name for s in sources], ["Unfallatlas 2023", "Unfallatlas 2024"])
        self.assertEqual(sources[0].config["url"], "https://example.org/u/2023.csv")
        self.assertEqual(sources[1].config["url"], "https://example.org/u/2024.csv")
        self.assertEqual(sources[0].config["encoding"], "utf-8")
        self.assertTrue(sources[0].config["clip_to_workspace"])
        self.assertEqual(sources[0].layer_kind, DataSource.LayerKind.ACCIDENTS)
        self.assertEqual(sources[0].license, "dl-de/by-2-0")

    def test_url_pattern_requires_year_placeholder(self):
        with self.assertRaises(CommandError):
            self._call(
                workspace="leipzig",
                years="2024",
                url_pattern="https://example.org/static.csv",
                **{"no_sync": True},
            )

    def test_demo_accidents_replaced_by_default(self):
        DataSource.objects.create(
            workspace=self.ws,
            name="Beispiel — Unfälle (Demo-Daten 2021–2025)",
            source_type=DataSource.SourceType.MANUAL,
            layer_kind=DataSource.LayerKind.ACCIDENTS,
            attribution="Illustrative demo data only",
        )
        self.assertEqual(self.ws.data_sources.count(), 1)
        self._call(
            workspace="leipzig",
            years="2024",
            url_pattern="https://example.org/u/{year}.csv",
            **{"no_sync": True},
        )
        names = list(self.ws.data_sources.values_list("name", flat=True))
        self.assertEqual(names, ["Unfallatlas 2024"])

    def test_keep_demo_flag_preserves_existing_demo(self):
        DataSource.objects.create(
            workspace=self.ws,
            name="Beispiel — Unfälle (Demo-Daten 2021–2025)",
            source_type=DataSource.SourceType.MANUAL,
            layer_kind=DataSource.LayerKind.ACCIDENTS,
            attribution="Illustrative demo data only",
        )
        self._call(
            workspace="leipzig",
            years="2024",
            url_pattern="https://example.org/u/{year}.csv",
            replace_demo=False,
            **{"no_sync": True},
        )
        names = sorted(self.ws.data_sources.values_list("name", flat=True))
        self.assertEqual(
            names,
            ["Beispiel — Unfälle (Demo-Daten 2021–2025)", "Unfallatlas 2024"],
        )

    def test_idempotent_run(self):
        kwargs = {
            "workspace": "leipzig",
            "years": "2024",
            "url_pattern": "https://example.org/u/{year}.csv",
            "no_sync": True,
        }
        self._call(**kwargs)
        self._call(**kwargs)
        self.assertEqual(
            self.ws.data_sources.filter(source_type="unfallat").count(), 1
        )

    @mock.patch("workspaces.management.commands.seed_unfallatlas._run_sync")
    def test_sync_runs_unless_no_sync(self, mock_sync):
        mock_sync.return_value = (True, "Synced 1234 records.")
        self._call(
            workspace="leipzig",
            years="2024",
            url_pattern="https://example.org/u/{year}.csv",
        )
        self.assertEqual(mock_sync.call_count, 1)
        synced_source = mock_sync.call_args.args[0]
        self.assertEqual(synced_source.name, "Unfallatlas 2024")

    def test_yaml_config_path_with_missing_year_raises(self):
        # No url-pattern, no per-workspace YAML, default config has empty sources →
        # all years are missing.
        with self.assertRaises(CommandError) as ctx:
            self._call(workspace="leipzig", years="2024", **{"no_sync": True})
        self.assertIn("No URL configured", str(ctx.exception))


@override_settings()
class SeedUnfallatlasYamlConfigTests(TestCase):
    """Exercises the YAML config-loading branch with a tmp config dir."""

    def setUp(self):
        self.ws = Workspace.objects.create(
            slug="leipzig",
            name="Leipzig",
            country_code="DE",
            language_code="de",
            timezone="Europe/Berlin",
            bounds=Polygon.from_bbox((12.295, 51.236, 12.549, 51.443)),
        )

    def test_yaml_config_loads_year_urls(self):
        from django.conf import settings
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "config").mkdir()
            (tmp_path / "config" / "unfallatlas.yaml").write_text(
                "default_encoding: latin-1\n"
                "sources:\n"
                "  2023:\n"
                "    url: https://example.org/2023.csv\n"
                "  2024:\n"
                "    url: https://example.org/2024.csv\n"
                "    encoding: utf-8\n"
            )
            with override_settings(REPO_ROOT=tmp_path):
                # Sanity-check: settings.REPO_ROOT got swapped.
                self.assertEqual(settings.REPO_ROOT, tmp_path)
                out = StringIO()
                call_command(
                    "seed_unfallatlas",
                    workspace="leipzig",
                    years="2023,2024",
                    no_sync=True,
                    stdout=out,
                )
        sources = {
            s.name: s
            for s in self.ws.data_sources.filter(source_type="unfallat")
        }
        self.assertEqual(set(sources), {"Unfallatlas 2023", "Unfallatlas 2024"})
        self.assertEqual(sources["Unfallatlas 2023"].config["encoding"], "latin-1")
        self.assertEqual(sources["Unfallatlas 2024"].config["encoding"], "utf-8")


# A trimmed-down sample of a Nominatim ``jsonv2`` response for "Lyon, France".
# boundingbox is [south, north, west, east] as strings, per the Nominatim API.
_NOMINATIM_LYON = [
    {
        "lat": "45.7578137",
        "lon": "4.8320114",
        "name": "Lyon",
        "display_name": "Lyon, Métropole de Lyon, France",
        "boundingbox": ["45.7073666", "45.8082628", "4.7718134", "4.8983774"],
        "address": {"city": "Lyon", "country": "France", "country_code": "fr"},
    }
]


class GeocodePlaceTests(TestCase):
    """Unit tests for the Nominatim parsing helper (no network)."""

    def _patch(self, payload, status=200):
        resp = mock.Mock()
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        return mock.patch("workspaces.geocoding.requests.get", return_value=resp)

    def test_parses_bbox_and_center(self):
        from workspaces.geocoding import geocode_place

        with self._patch(_NOMINATIM_LYON):
            results = geocode_place("Lyon")

        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r.name, "Lyon")
        self.assertEqual(r.country_code, "FR")
        # bbox is (west, south, east, north)
        self.assertEqual(r.bbox, (4.7718134, 45.7073666, 4.8983774, 45.8082628))
        self.assertEqual(r.center, (4.8320114, 45.7578137))

    def test_as_dict_shape(self):
        from workspaces.geocoding import geocode_place

        with self._patch(_NOMINATIM_LYON):
            d = geocode_place("Lyon")[0].as_dict()

        self.assertEqual(d["country_code"], "FR")
        self.assertEqual(d["bbox"]["minx"], 4.7718134)
        self.assertEqual(d["bbox"]["maxy"], 45.8082628)
        self.assertEqual(d["center"]["lat"], 45.7578137)

    def test_blank_query_skips_request(self):
        from workspaces.geocoding import geocode_place

        with mock.patch("workspaces.geocoding.requests.get") as get:
            self.assertEqual(geocode_place("   "), [])
            get.assert_not_called()

    def test_unparseable_records_are_dropped(self):
        from workspaces.geocoding import geocode_place

        bad = [{"display_name": "no coords here"}]
        with self._patch(bad):
            self.assertEqual(geocode_place("nowhere"), [])

    def test_network_error_raises_geocoding_error(self):
        import requests as _requests

        from workspaces.geocoding import GeocodingError, geocode_place

        with mock.patch(
            "workspaces.geocoding.requests.get",
            side_effect=_requests.RequestException("boom"),
        ):
            with self.assertRaises(GeocodingError):
                geocode_place("Lyon")


@override_settings(ADMIN_TOKEN="test-token")
class WizardGeocodeViewTests(TestCase):
    """The geocode endpoint used by the new-workspace wizard."""

    def _auth(self):
        return {"HTTP_AUTHORIZATION": "Bearer test-token"}

    def test_requires_admin(self):
        resp = self.client.get(reverse("workspace_geocode"), {"q": "Lyon"})
        self.assertEqual(resp.status_code, 403)

    def test_returns_results_as_json(self):
        resp_obj = mock.Mock()
        resp_obj.json.return_value = _NOMINATIM_LYON
        resp_obj.raise_for_status.return_value = None
        with mock.patch("workspaces.geocoding.requests.get", return_value=resp_obj):
            resp = self.client.get(reverse("workspace_geocode"), {"q": "Lyon"}, **self._auth())

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["country_code"], "FR")
        self.assertEqual(data["results"][0]["bbox"]["minx"], 4.7718134)

    def test_blank_query_returns_empty(self):
        resp = self.client.get(reverse("workspace_geocode"), {"q": ""}, **self._auth())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"results": []})

    def test_geocoder_failure_returns_502(self):
        import requests as _requests

        with mock.patch(
            "workspaces.geocoding.requests.get",
            side_effect=_requests.RequestException("down"),
        ):
            resp = self.client.get(reverse("workspace_geocode"), {"q": "Lyon"}, **self._auth())

        self.assertEqual(resp.status_code, 502)
        self.assertIn("error", resp.json())
