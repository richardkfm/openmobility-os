"""Unit tests for connectors.

Includes the GTFS static connector (in-memory zip fixture), the BikeMaps.org
crowdsourced cycling-incident connector (mocked HTTP), and bbox-clipping
behaviour for the Unfallatlas connector.
"""

import io
import zipfile
from dataclasses import dataclass
from unittest import TestCase, mock

from connectors.bikemaps_connector import BikeMapsConnector, _record_to_feature
from connectors.gtfs_connector import GTFSConnector, _circle_ring, _is_night_time
from connectors.unfallat_connector import UnfallatlasConnector, _parse_bbox, _row_to_feature


STOPS_TXT = """stop_id,stop_name,stop_lat,stop_lon,wheelchair_boarding,location_type
A,Central Station,50.0000,10.0000,1,0
B,City Hall,50.0100,10.0100,2,0
C,Parent Station,50.0200,10.0200,0,1
D,West Depot,50.0050,9.9900,,0
"""

ROUTES_TXT = """route_id,agency_id,route_short_name,route_long_name,route_type,route_color
R1,AG1,1,Central–City Hall,3,ff0000
R2,AG1,2,East Tram,0,
"""

TRIPS_TXT = """route_id,service_id,trip_id,shape_id
R1,WEEKDAY,T1,S1
R1,WEEKDAY,T2,S1
R2,WEEKDAY,T3,
"""

# T1/T2 travel A→B twice (morning + late-night); T3 travels D→A.
STOP_TIMES_TXT = """trip_id,arrival_time,departure_time,stop_id,stop_sequence
T1,06:10:00,06:10:00,A,1
T1,06:20:00,06:20:00,B,2
T2,23:10:00,23:10:00,A,1
T2,23:20:00,23:20:00,B,2
T3,08:00:00,08:00:00,D,1
T3,08:15:00,08:15:00,A,2
"""

SHAPES_TXT = """shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence
S1,50.0000,10.0000,1
S1,50.0050,10.0050,2
S1,50.0100,10.0100,3
"""

CALENDAR_TXT = """service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date
WEEKDAY,1,1,1,1,1,0,0,20260101,20261231
"""


def _build_archive(
    stops: str = STOPS_TXT,
    routes: str = ROUTES_TXT,
    trips: str = TRIPS_TXT,
    stop_times: str = STOP_TIMES_TXT,
    shapes: str = SHAPES_TXT,
    calendar: str = CALENDAR_TXT,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("stops.txt", stops)
        zf.writestr("routes.txt", routes)
        zf.writestr("trips.txt", trips)
        zf.writestr("stop_times.txt", stop_times)
        if shapes:
            zf.writestr("shapes.txt", shapes)
        if calendar:
            zf.writestr("calendar.txt", calendar)
    return buf.getvalue()


@dataclass
class _FakeResponse:
    content: bytes

    def raise_for_status(self):
        return None


class GTFSStopsTests(TestCase):
    def setUp(self):
        self.patcher = mock.patch(
            "connectors.gtfs_connector.requests.get",
            return_value=_FakeResponse(_build_archive()),
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_stops_layer_enriches_properties(self):
        result = GTFSConnector().fetch(
            {"url": "http://example/gtfs.zip", "layer": "transit_stops"}
        )
        stops = {f["properties"]["stop_id"]: f for f in result.feature_collection["features"]}

        # Parent station (location_type=1) is filtered out.
        self.assertIn("A", stops)
        self.assertIn("B", stops)
        self.assertIn("D", stops)
        self.assertNotIn("C", stops)

        a = stops["A"]["properties"]
        self.assertEqual(a["wheelchair_boarding"], "yes")
        self.assertEqual(a["daily_trips"], 3)  # T1, T2, T3 all stop at A
        self.assertIn("bus", a["modes"])  # R1 (route_type=3)
        self.assertTrue(a["night_service"])  # T2 at 23:10
        self.assertIsNotNone(a["avg_headway_min"])

        b = stops["B"]["properties"]
        self.assertEqual(b["wheelchair_boarding"], "no")
        self.assertEqual(b["daily_trips"], 2)
        self.assertTrue(b["night_service"])

        d = stops["D"]["properties"]
        self.assertEqual(d["wheelchair_boarding"], "unknown")
        self.assertFalse(d["night_service"])

    def test_routes_layer_uses_shape_when_available(self):
        result = GTFSConnector().fetch(
            {"url": "http://example/gtfs.zip", "layer": "transit_routes"}
        )
        routes = {f["properties"]["route_id"]: f for f in result.feature_collection["features"]}

        # R1 has a shape (S1) with 3 points.
        self.assertIn("R1", routes)
        self.assertEqual(len(routes["R1"]["geometry"]["coordinates"]), 3)
        self.assertEqual(routes["R1"]["properties"]["mode"], "bus")
        self.assertEqual(routes["R1"]["properties"]["color"], "#ff0000")

        # R2 has no shape — falls back to stop sequence (D, A).
        self.assertIn("R2", routes)
        self.assertEqual(len(routes["R2"]["geometry"]["coordinates"]), 2)
        self.assertEqual(routes["R2"]["properties"]["mode"], "tram")

    def test_coverage_layer_emits_buffers_around_active_stops(self):
        result = GTFSConnector().fetch(
            {
                "url": "http://example/gtfs.zip",
                "layer": "transit_coverage",
                "coverage_buffer_m": 500,
            }
        )
        features = result.feature_collection["features"]
        # Parent station C is filtered (location_type=1 has no stop_times rows).
        stop_ids = {f["properties"]["stop_id"] for f in features}
        self.assertEqual(stop_ids, {"A", "B", "D"})
        first = features[0]
        self.assertEqual(first["geometry"]["type"], "Polygon")
        self.assertEqual(first["properties"]["buffer_m"], 500)
        # Polygon rings close on themselves.
        ring = first["geometry"]["coordinates"][0]
        self.assertEqual(ring[0], ring[-1])

    def test_route_type_filter_restricts_output(self):
        result = GTFSConnector().fetch(
            {
                "url": "http://example/gtfs.zip",
                "layer": "transit_routes",
                "route_type_filter": [3],  # only bus
            }
        )
        route_ids = {f["properties"]["route_id"] for f in result.feature_collection["features"]}
        self.assertEqual(route_ids, {"R1"})

    def test_validate_config_flags_missing_fields(self):
        errors = GTFSConnector().validate_config({"url": ""})
        self.assertTrue(any("URL" in e for e in errors))
        self.assertTrue(any("layer" in e.lower() for e in errors))

    def test_validate_config_rejects_unknown_layer(self):
        errors = GTFSConnector().validate_config(
            {"url": "http://x", "layer": "bogus"}
        )
        self.assertTrue(any("bogus" in e for e in errors))


class GTFSHelpersTests(TestCase):
    def test_night_time_detection_handles_overnight_trips(self):
        self.assertTrue(_is_night_time("22:30:00"))
        self.assertTrue(_is_night_time("03:00:00"))
        self.assertTrue(_is_night_time("25:30:00"))  # 25:30 → 01:30
        self.assertFalse(_is_night_time("08:00:00"))
        self.assertFalse(_is_night_time("21:59:00"))
        self.assertFalse(_is_night_time(""))
        self.assertFalse(_is_night_time(None))

    def test_circle_ring_is_closed_and_has_expected_step_count(self):
        ring = _circle_ring(10.0, 50.0, radius_m=400, steps=24)
        self.assertEqual(len(ring), 25)  # 24 steps + closing point
        self.assertEqual(ring[0], ring[-1])
        # Radius in degrees should be roughly ~0.0036 lat and a bit more lon.
        max_lat = max(p[1] for p in ring)
        min_lat = min(p[1] for p in ring)
        self.assertAlmostEqual((max_lat - min_lat) / 2, 400 / 110_574, places=5)


# --------------------------------------------------------------------------- #
# BikeMaps.org connector
# --------------------------------------------------------------------------- #

# Sample GeoJSON-style payload — what the BikeMaps incidents.json endpoint
# typically returns (a FeatureCollection of incident points).
BIKEMAPS_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [12.40, 51.34]},
            "properties": {
                "incident_type": "Collision",
                "injury": "Injury, hospital visit requiring an overnight stay",
                "incident_with": "Vehicle, side",
                "incident_date": "2024-05-12",
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [12.38, 51.33]},
            "properties": {
                "incident_type": "Near miss",
                "injury": "No injury",
                "incident_with": "Vehicle door",
                "incident_date": "2025-06-01",
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [12.36, 51.35]},
            "properties": {
                "incident_type": "Hazard",
                "injury": "No injury",
                "incident_with": "",
                "incident_date": "2025-03-22",
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [12.41, 51.34]},
            "properties": {
                "incident_type": "Collision",
                "injury": "Fatal",
                "incident_with": "Pedestrian",
                "incident_date": "2023-11-08",
            },
        },
    ],
}


# Sample paginated DRF-style payload (used to verify pagination handling).
BIKEMAPS_PAGINATED_PAGE_1 = {
    "count": 3,
    "next": "https://bikemaps.org/api/v1/incidents/?page=2",
    "results": [
        {
            "geometry": {"type": "Point", "coordinates": [12.40, 51.34]},
            "properties": {
                "incident_type": "collision",
                "injury": "Fatal",
                "incident_date": "2024-01-01",
            },
        },
        {
            "geometry": {"type": "Point", "coordinates": [12.41, 51.35]},
            "properties": {
                "incident_type": "nearmiss",
                "injury": "No injury",
                "incident_date": "2024-02-02",
            },
        },
    ],
}
BIKEMAPS_PAGINATED_PAGE_2 = {
    "count": 3,
    "next": None,
    "results": [
        {
            "geometry": {"type": "Point", "coordinates": [12.42, 51.36]},
            "properties": {
                "incident_type": "collision",
                "injury": "Injury, hospital visit not requiring an overnight stay",
                "incident_date": "2024-03-03",
            },
        },
    ],
}


@dataclass
class _Bounds:
    """Stand-in for a GeoDjango Polygon — only `extent` is consulted."""

    extent: tuple

    def __iter__(self):
        return iter(self.extent)


@dataclass
class _Workspace:
    bounds: object


class _MockJSONResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class BikeMapsTests(TestCase):
    def setUp(self):
        self.workspace = _Workspace(bounds=_Bounds(extent=(12.30, 51.24, 12.55, 51.45)))

    def _patched_get(self, payload):
        return mock.patch(
            "connectors.bikemaps_connector.requests.get",
            return_value=_MockJSONResponse(payload),
        )

    def test_geojson_payload_normalizes_to_accident_schema(self):
        with self._patched_get(BIKEMAPS_GEOJSON):
            result = BikeMapsConnector().fetch({}, workspace=self.workspace)

        # Default config drops "Hazard" but keeps the two collisions and the near miss.
        features = result.feature_collection["features"]
        self.assertEqual(len(features), 3)
        types = sorted(f["properties"]["incident_type"] for f in features)
        self.assertEqual(types, ["collision", "collision", "near_miss"])

        # All features carry crowdsource provenance and VRU flag.
        for f in features:
            self.assertEqual(f["properties"]["data_origin"], "crowdsourced")
            self.assertEqual(f["properties"]["source_platform"], "bikemaps.org")
            self.assertTrue(f["properties"]["vulnerable_road_user"])
            self.assertIn("cyclist", f["properties"]["involved_modes"])

        # Severity mapping: hospital-overnight → serious, near miss → minor (forced),
        # fatal → fatal.
        sev = {f["properties"]["date"]: f["properties"]["severity"] for f in features}
        self.assertEqual(sev["2024-05-12"], "serious")
        self.assertEqual(sev["2025-06-01"], "minor")
        self.assertEqual(sev["2023-11-08"], "fatal")

    def test_include_hazards_opt_in(self):
        with self._patched_get(BIKEMAPS_GEOJSON):
            result = BikeMapsConnector().fetch(
                {"include_hazards": True}, workspace=self.workspace
            )
        types = {f["properties"]["incident_type"] for f in result.feature_collection["features"]}
        self.assertIn("hazard", types)

    def test_year_filter(self):
        with self._patched_get(BIKEMAPS_GEOJSON):
            result = BikeMapsConnector().fetch(
                {"start_year": 2024, "end_year": 2025}, workspace=self.workspace
            )
        years = {f["properties"]["year"] for f in result.feature_collection["features"]}
        # The 2023 fatal collision is filtered out.
        self.assertEqual(years, {2024, 2025})

    def test_disabling_near_misses(self):
        with self._patched_get(BIKEMAPS_GEOJSON):
            result = BikeMapsConnector().fetch(
                {"include_near_misses": False}, workspace=self.workspace
            )
        types = {f["properties"]["incident_type"] for f in result.feature_collection["features"]}
        self.assertEqual(types, {"collision"})

    def test_paginated_drf_envelope(self):
        responses = [
            _MockJSONResponse(BIKEMAPS_PAGINATED_PAGE_1),
            _MockJSONResponse(BIKEMAPS_PAGINATED_PAGE_2),
        ]
        with mock.patch(
            "connectors.bikemaps_connector.requests.get", side_effect=responses
        ) as m:
            result = BikeMapsConnector().fetch({}, workspace=self.workspace)
        self.assertEqual(result.record_count, 3)
        # Pagination chains: page 1 then page 2.
        self.assertEqual(m.call_count, 2)
        self.assertIn("page=2", m.call_args_list[1][0][0])

    def test_fetch_without_bbox_or_workspace_raises(self):
        with self.assertRaises(ValueError):
            BikeMapsConnector().fetch({}, workspace=None)

    def test_explicit_bbox_overrides_workspace(self):
        with self._patched_get(BIKEMAPS_GEOJSON) as m:
            BikeMapsConnector().fetch(
                {"bbox": "12.0,51.0,13.0,52.0"}, workspace=self.workspace
            )
        params = m.call_args.kwargs.get("params") or m.call_args[1].get("params")
        self.assertEqual(params["bbox"], "12.0,51.0,13.0,52.0")

    def test_validate_config_rejects_bad_bbox(self):
        errors = BikeMapsConnector().validate_config({"bbox": "1,2,3"})
        self.assertTrue(any("bbox" in e for e in errors))

    def test_record_to_feature_handles_flat_record(self):
        feature = _record_to_feature(
            {
                "p_x": 12.4,
                "p_y": 51.3,
                "p_type": "collision",
                "p_injury": "Fatal",
                "p_incident_with": "Truck",
                "p_date": "2024-08-15",
            },
            filters={"collision": True, "near_miss": True, "hazard": False, "theft": False,
                     "start_year": None, "end_year": None},
        )
        self.assertIsNotNone(feature)
        self.assertEqual(feature["properties"]["severity"], "fatal")
        self.assertIn("truck", feature["properties"]["involved_modes"])

    def test_test_connection_without_bounds_returns_helpful_error(self):
        result = BikeMapsConnector().test_connection({}, workspace=None)
        self.assertFalse(result.success)
        self.assertIn("bbox", result.message.lower())


# --------------------------------------------------------------------------- #
# Unfallatlas connector — bbox-clipping
# --------------------------------------------------------------------------- #

UNFALLATLAS_CSV = (
    # Header — Destatis uses German semicolon-delimited CSV with a fixed
    # set of UPPERCASE column names.
    "OBJECTID;UJAHR;UMONAT;USTUNDE;UWOCHENTAG;UKATEGORIE;UART;UTYP1;ULICHTVERH;"
    "IstRad;IstPKW;IstFuss;IstKrad;IstGkfz;IstSonstige;USTRZUSTAND;LINREFX;LINREFY;"
    "XGCSWGS84;YGCSWGS84\n"
    # Inside Leipzig bbox (12.295/51.236 .. 12.549/51.443).
    "1;2024;5;14;3;2;5;1;0;1;1;0;0;0;0;0;0;0;12,3731;51,3397\n"
    "2;2024;7;22;5;3;1;2;0;0;1;1;0;0;0;0;0;0;12,4000;51,3500\n"
    # Outside the bbox — Berlin coordinates, must be dropped when clipping.
    "3;2024;9;9;1;1;5;3;0;0;1;0;0;0;0;0;0;0;13,4050;52,5200\n"
)


class UnfallatlasBboxTests(TestCase):
    def setUp(self):
        self.workspace = _Workspace(
            bounds=_Bounds(extent=(12.295, 51.236, 12.549, 51.443))
        )
        self.patcher = mock.patch(
            "connectors.unfallat_connector.requests.get",
            return_value=_FakeResponse(UNFALLATLAS_CSV.encode("utf-8")),
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_no_bbox_keeps_all_rows(self):
        result = UnfallatlasConnector().fetch(
            {"url": "http://x/x.csv", "clip_to_workspace": False}, workspace=None
        )
        self.assertEqual(result.record_count, 3)

    def test_workspace_bounds_clip_when_no_explicit_bbox(self):
        result = UnfallatlasConnector().fetch(
            {"url": "http://x/x.csv"}, workspace=self.workspace
        )
        self.assertEqual(result.record_count, 2)
        coords = [f["geometry"]["coordinates"] for f in result.feature_collection["features"]]
        # Berlin row dropped — all kept points sit inside the Leipzig bbox.
        for lon, lat in coords:
            self.assertTrue(12.295 <= lon <= 12.549)
            self.assertTrue(51.236 <= lat <= 51.443)

    def test_explicit_bbox_overrides_workspace(self):
        # Tight box around the first feature only.
        result = UnfallatlasConnector().fetch(
            {"url": "http://x/x.csv", "bbox": "12.36,51.33,12.39,51.35"},
            workspace=self.workspace,
        )
        self.assertEqual(result.record_count, 1)

    def test_validate_rejects_malformed_bbox(self):
        errors = UnfallatlasConnector().validate_config(
            {"url": "http://x/x.csv", "bbox": "abc,def,ghi,jkl"}
        )
        self.assertTrue(any("bbox" in e.lower() for e in errors))

    def test_parse_bbox_helper(self):
        self.assertEqual(_parse_bbox("1,2,3,4"), (1.0, 2.0, 3.0, 4.0))
        self.assertEqual(_parse_bbox(" 1 , 2 , 3 , 4 "), (1.0, 2.0, 3.0, 4.0))
        self.assertIsNone(_parse_bbox("1,2,3"))
        self.assertIsNone(_parse_bbox(""))
        # west > east → invalid.
        self.assertIsNone(_parse_bbox("4,2,3,1"))
        self.assertEqual(_parse_bbox([1, 2, 3, 4]), (1.0, 2.0, 3.0, 4.0))

    def test_row_to_feature_drops_rows_outside_bbox(self):
        outside_row = {
            "XGCSWGS84": "13,4050",
            "YGCSWGS84": "52,5200",
            "UKATEGORIE": "1",
            "UJAHR": "2024",
            "UMONAT": "5",
            "USTUNDE": "10",
        }
        self.assertIsNone(_row_to_feature(outside_row, bbox=(12.0, 51.0, 13.0, 52.0)))
        self.assertIsNotNone(_row_to_feature(outside_row, bbox=None))


# --------------------------------------------------------------------------- #
# CKAN connector
# --------------------------------------------------------------------------- #


class _JsonResponse:
    """Minimal stand-in for a requests.Response that yields JSON."""

    def __init__(self, payload, status_code=200, content_type="application/json"):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _BytesResponse:
    """Stand-in for a binary response (used by CSV/GTFS connectors under the hood)."""

    def __init__(self, content):
        self.content = content if isinstance(content, bytes) else content.encode("utf-8")

    def raise_for_status(self):
        return None


CKAN_PACKAGE = {
    "success": True,
    "result": {
        "name": "bike-counters",
        "resources": [
            {
                "id": "r-pdf",
                "name": "Methodology",
                "format": "PDF",
                "url": "http://example/method.pdf",
            },
            {
                "id": "r-csv",
                "name": "Counts",
                "format": "CSV",
                "url": "http://example/counts.csv",
            },
            {
                "id": "r-geo",
                "name": "Stations",
                "format": "GeoJSON",
                "url": "http://example/stations.geojson",
            },
        ],
    },
}

STATIONS_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [12.37, 51.34]},
            "properties": {"id": "S1", "name": "Augustusplatz"},
        }
    ],
}


class CKANConnectorTests(TestCase):
    def test_resolves_geojson_resource_by_preference_and_delegates(self):
        from connectors.ckan_connector import CKANConnector

        # Note: connectors.ckan_connector.requests and
        # connectors.geojson_connector.requests refer to the same module object,
        # so we patch once and dispatch by URL.
        seen = []

        def dispatch(url, params=None, timeout=None, headers=None):
            seen.append(url)
            if "/api/3/action/" in url:
                return _JsonResponse(CKAN_PACKAGE)
            if url.endswith(".geojson"):
                return _JsonResponse(STATIONS_GEOJSON)
            raise AssertionError(f"Unexpected URL {url}")

        with mock.patch(
            "connectors.ckan_connector.requests.get", side_effect=dispatch
        ):
            result = CKANConnector().fetch(
                {
                    "portal_url": "https://opendata.example/",
                    "package_id": "bike-counters",
                }
            )

        self.assertEqual(result.record_count, 1)
        self.assertEqual(
            result.feature_collection["features"][0]["properties"]["name"],
            "Augustusplatz",
        )
        # First call hits the CKAN package_show endpoint, then the resource URL.
        self.assertTrue(any("/api/3/action/package_show" in u for u in seen))
        self.assertTrue(any(u.endswith(".geojson") for u in seen))

    def test_validate_config_requires_portal_and_id(self):
        from connectors.ckan_connector import CKANConnector

        errors = CKANConnector().validate_config({})
        self.assertTrue(any("portal_url" in e for e in errors))
        self.assertTrue(any("package_id or resource_id" in e for e in errors))


# --------------------------------------------------------------------------- #
# WFS connector
# --------------------------------------------------------------------------- #


WFS_RESPONSE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [12.4, 51.3]},
            "properties": {"id": "D1", "name": "Zentrum"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [12.5, 51.4]},
            "properties": {"id": "D2", "name": "Plagwitz"},
        },
    ],
}


@dataclass
class _StubBounds:
    extent: tuple


@dataclass
class _StubWorkspace:
    bounds: _StubBounds


class WFSConnectorTests(TestCase):
    def test_fetch_returns_feature_collection(self):
        from connectors.wfs_connector import WFSConnector

        with mock.patch(
            "connectors.wfs_connector.requests.get",
            return_value=_JsonResponse(WFS_RESPONSE),
        ):
            result = WFSConnector().fetch(
                {"url": "https://wfs.example/", "layer_name": "districts"}
            )
        self.assertEqual(result.record_count, 2)
        ids = {f["properties"]["id"] for f in result.feature_collection["features"]}
        self.assertEqual(ids, {"D1", "D2"})

    def test_workspace_bbox_is_added_to_params(self):
        from connectors.wfs_connector import WFSConnector

        captured = {}

        def fake_get(url, params=None, headers=None, timeout=None):
            captured["params"] = params
            return _JsonResponse(WFS_RESPONSE)

        ws = _StubWorkspace(bounds=_StubBounds(extent=(12.0, 51.0, 13.0, 52.0)))
        with mock.patch("connectors.wfs_connector.requests.get", side_effect=fake_get):
            WFSConnector().fetch(
                {"url": "https://wfs.example/", "layer_name": "districts"},
                workspace=ws,
            )
        self.assertIn("bbox", captured["params"])
        self.assertTrue(captured["params"]["bbox"].startswith("12.0,51.0,13.0,52.0,EPSG:4326"))

    def test_cql_filter_disables_workspace_bbox(self):
        from connectors.wfs_connector import WFSConnector

        captured = {}

        def fake_get(url, params=None, headers=None, timeout=None):
            captured["params"] = params
            return _JsonResponse(WFS_RESPONSE)

        ws = _StubWorkspace(bounds=_StubBounds(extent=(12.0, 51.0, 13.0, 52.0)))
        with mock.patch("connectors.wfs_connector.requests.get", side_effect=fake_get):
            WFSConnector().fetch(
                {
                    "url": "https://wfs.example/",
                    "layer_name": "districts",
                    "cql_filter": "population > 1000",
                },
                workspace=ws,
            )
        self.assertNotIn("bbox", captured["params"])
        self.assertEqual(captured["params"]["CQL_FILTER"], "population > 1000")

    def test_validate_config_flags_missing_fields(self):
        from connectors.wfs_connector import WFSConnector

        errors = WFSConnector().validate_config({})
        self.assertTrue(any("URL" in e for e in errors))
        self.assertTrue(any("layer_name" in e for e in errors))


# --------------------------------------------------------------------------- #
# REST connector
# --------------------------------------------------------------------------- #


UBA_LIKE_RESPONSE = {
    "stations": [
        {
            "id": "DESN001",
            "name": "Leipzig-Mitte",
            "coords": {"lat": "51.3397", "lon": "12.3731"},
            "no2_ugm3": 28.4,
        },
        {
            "id": "DESN002",
            "name": "Leipzig-West",
            "coords": {"lat": "51.3300", "lon": "12.3100"},
            "no2_ugm3": 22.1,
        },
        {
            "id": "BAD",
            "name": "no-coords",
            "coords": {"lat": None, "lon": None},
            "no2_ugm3": None,
        },
    ]
}


class RESTConnectorTests(TestCase):
    def test_fetch_with_lat_lon_mapping(self):
        from connectors.rest_connector import RESTConnector

        with mock.patch(
            "connectors.rest_connector.requests.get",
            return_value=_JsonResponse(UBA_LIKE_RESPONSE),
        ):
            result = RESTConnector().fetch(
                {
                    "url": "https://uba.example/stations",
                    "json_path": "stations",
                    "geometry_mapping": {"lat": "coords.lat", "lon": "coords.lon"},
                }
            )
        self.assertEqual(result.record_count, 2)  # BAD is dropped (no coords)
        f = result.feature_collection["features"][0]
        self.assertEqual(f["geometry"]["type"], "Point")
        # Comma-decimal would also work; here we use plain floats.
        self.assertAlmostEqual(f["geometry"]["coordinates"][0], 12.3731)
        self.assertEqual(f["properties"]["id"], "DESN001")

    def test_fetch_with_embedded_geojson_geometry(self):
        from connectors.rest_connector import RESTConnector

        payload = {
            "items": [
                {
                    "name": "Park A",
                    "shape": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                }
            ]
        }
        with mock.patch(
            "connectors.rest_connector.requests.get",
            return_value=_JsonResponse(payload),
        ):
            result = RESTConnector().fetch(
                {
                    "url": "https://example/",
                    "json_path": "items",
                    "geometry_mapping": {"geojson": "shape"},
                }
            )
        self.assertEqual(result.record_count, 1)
        self.assertEqual(result.feature_collection["features"][0]["geometry"]["type"], "Polygon")

    def test_validate_config_requires_geometry_mapping(self):
        from connectors.rest_connector import RESTConnector

        errors = RESTConnector().validate_config({"url": "https://x"})
        self.assertTrue(any("geometry_mapping" in e for e in errors))


# --------------------------------------------------------------------------- #
# Mobilithek connector
# --------------------------------------------------------------------------- #


class MobilithekConnectorTests(TestCase):
    def test_open_mode_dispatches_geojson_to_geojson_connector(self):
        from connectors.mobilithek_connector import MobilithekConnector

        with mock.patch(
            "connectors.geojson_connector.requests.get",
            return_value=_JsonResponse(STATIONS_GEOJSON),
        ):
            result = MobilithekConnector().fetch(
                {
                    "distribution_url": "https://mobilithek.example/stations.geojson",
                    "format_hint": "geojson",
                }
            )
        self.assertEqual(result.record_count, 1)
        self.assertEqual(
            result.feature_collection["features"][0]["properties"]["name"],
            "Augustusplatz",
        )

    def test_open_mode_dispatches_gtfs_to_gtfs_connector(self):
        from connectors.mobilithek_connector import MobilithekConnector

        archive = _build_archive()
        with mock.patch(
            "connectors.gtfs_connector.requests.get",
            return_value=_BytesResponse(archive),
        ):
            result = MobilithekConnector().fetch(
                {
                    "distribution_url": "https://mobilithek.example/gtfs.zip",
                    "format_hint": "gtfs",
                    "inner_options": {"layer": "transit_stops"},
                }
            )
        self.assertGreater(result.record_count, 0)
        ids = {f["properties"]["stop_id"] for f in result.feature_collection["features"]}
        self.assertIn("A", ids)

    def test_subscriber_mode_validates_cert_paths(self):
        from connectors.mobilithek_connector import MobilithekConnector

        errors = MobilithekConnector().validate_config(
            {
                "distribution_url": "https://x",
                "format_hint": "geojson",
                "mode": "subscriber",
            }
        )
        self.assertTrue(any("cert_path" in e and "key_path" in e for e in errors))

    def test_subscriber_mode_passes_cert_to_inner_connector(self):
        from connectors.mobilithek_connector import MobilithekConnector

        captured: dict = {}

        def fake_get(url, *args, **kwargs):
            captured["url"] = url
            captured["cert"] = kwargs.get("cert")
            return _JsonResponse(STATIONS_GEOJSON)

        with mock.patch(
            "connectors.geojson_connector.requests.get", side_effect=fake_get
        ):
            result = MobilithekConnector().fetch(
                {
                    "distribution_url": "https://mobilithek.example/restricted.geojson",
                    "format_hint": "geojson",
                    "mode": "subscriber",
                    "cert_path": "/run/secrets/cert.pem",
                    "key_path": "/run/secrets/key.pem",
                }
            )

        self.assertEqual(result.record_count, 1)
        self.assertEqual(
            captured["cert"], ("/run/secrets/cert.pem", "/run/secrets/key.pem")
        )
        self.assertEqual(
            captured["url"], "https://mobilithek.example/restricted.geojson"
        )

    def test_open_mode_does_not_send_cert(self):
        from connectors.mobilithek_connector import MobilithekConnector

        captured: dict = {}

        def fake_get(url, *args, **kwargs):
            captured["cert"] = kwargs.get("cert", "SENTINEL_NOT_PASSED")
            return _JsonResponse(STATIONS_GEOJSON)

        with mock.patch(
            "connectors.geojson_connector.requests.get", side_effect=fake_get
        ):
            MobilithekConnector().fetch(
                {
                    "distribution_url": "https://mobilithek.example/open.geojson",
                    "format_hint": "geojson",
                }
            )

        self.assertEqual(captured["cert"], "SENTINEL_NOT_PASSED")

    def test_subscriber_mode_test_connection_sends_cert_on_head(self):
        from connectors.mobilithek_connector import MobilithekConnector

        captured: dict = {}

        class _HeadResponse:
            headers = {"Content-Length": "1234"}

            def raise_for_status(self):
                return None

        def fake_head(url, *args, **kwargs):
            captured["cert"] = kwargs.get("cert")
            return _HeadResponse()

        with mock.patch(
            "connectors.mobilithek_connector.requests.head", side_effect=fake_head
        ):
            result = MobilithekConnector().test_connection(
                {
                    "distribution_url": "https://mobilithek.example/restricted.geojson",
                    "format_hint": "geojson",
                    "mode": "subscriber",
                    "cert_path": "/run/secrets/cert.pem",
                    "key_path": "/run/secrets/key.pem",
                }
            )

        self.assertTrue(result.success)
        self.assertEqual(
            captured["cert"], ("/run/secrets/cert.pem", "/run/secrets/key.pem")
        )
        self.assertIn("subscriber mode", result.message)

    def test_validate_rejects_unknown_format(self):
        from connectors.mobilithek_connector import MobilithekConnector

        errors = MobilithekConnector().validate_config(
            {"distribution_url": "https://x", "format_hint": "datex"}
        )
        self.assertTrue(any("format_hint" in e for e in errors))


class GermanPresetsTests(TestCase):
    """German federal preset connectors delegate correctly to CSV/REST."""

    BNETZA_CSV = (
        "Betreiber;Straße;Breitengrad;Längengrad;Nennleistung\n"
        "EnBW;Hauptstr. 1;51.3400;12.3700;22\n"
        "Ionity;Autobahnraststätte;51.3500;12.3800;350\n"
    )

    def _csv_response(self, text, encoding="cp1252"):
        class _Resp:
            content = text.encode(encoding)
            status_code = 200

            def raise_for_status(self):
                return None

        return _Resp()

    def test_bnetza_fetch_delegates_with_correct_columns(self):
        from connectors.german_presets import BNetzAChargingConnector

        with mock.patch(
            "connectors.csv_connector.requests.get",
            return_value=self._csv_response(self.BNETZA_CSV),
        ):
            result = BNetzAChargingConnector().fetch(
                {"url": "https://example.com/bnetza.csv"}
            )
        self.assertEqual(result.record_count, 2)
        feat = result.feature_collection["features"][0]
        self.assertEqual(feat["geometry"]["coordinates"], [12.37, 51.34])
        self.assertIn("Betreiber", feat["properties"])

    def test_bnetza_validate_requires_url(self):
        from connectors.german_presets import BNetzAChargingConnector

        errors = BNetzAChargingConnector().validate_config({})
        self.assertTrue(any("url" in e for e in errors))

    def test_uba_air_fetch_delegates_to_rest(self):
        from connectors.german_presets import UBAAirQualityConnector

        sample = {
            "data": [
                {
                    "station_name": "Leipzig-Mitte",
                    "station_code": "DESN049",
                    "station_city": "Leipzig",
                    "station_latitude": 51.34,
                    "station_longitude": 12.37,
                    "station_type": "background",
                    "station_setting": "urban",
                    "network_name": "Sachsen",
                },
            ]
        }

        class _Resp:
            status_code = 200
            headers = {"Content-Type": "application/json"}

            def raise_for_status(self):
                return None

            def json(self):
                return sample

        with mock.patch(
            "connectors.rest_connector.requests.get", return_value=_Resp()
        ):
            result = UBAAirQualityConnector().fetch({})
        self.assertEqual(result.record_count, 1)
        feat = result.feature_collection["features"][0]
        self.assertEqual(feat["properties"]["station_name"], "Leipzig-Mitte")
        self.assertEqual(feat["geometry"]["coordinates"], [12.37, 51.34])

    def test_dwd_validate_requires_url(self):
        from connectors.german_presets import DWDClimateConnector

        errors = DWDClimateConnector().validate_config({})
        self.assertTrue(any("url" in e for e in errors))

    def test_bast_validate_requires_url(self):
        from connectors.german_presets import BASTCountsConnector

        errors = BASTCountsConnector().validate_config({})
        self.assertTrue(any("url" in e for e in errors))


class ZensusGridConnectorTests(TestCase):
    """Zensus 2022 100m grid connector — parses INSPIRE grid IDs and
    converts EPSG:3035 cells to WGS84 polygons."""

    SAMPLE_CSV = (
        "Gitter_ID_100m;Einwohner;Alter_unter_18;Alter_65_und_aelter\n"
        "100mN28550E43900;45;12;8\n"
        "100mN28551E43900;0;0;0\n"
        "100mN28552E43901;30;5;10\n"
        # Outside Leipzig bbox (far north):
        "100mN35000E43000;100;20;20\n"
    )

    def _fake_get(self, csv_text):
        class _Resp:
            content = csv_text.encode("utf-8")
            status_code = 200

            def raise_for_status(self):
                return None

        return _Resp()

    def test_parse_grid_id(self):
        from connectors.zensus_grid_connector import _parse_grid_id

        result = _parse_grid_id("100mN26850E43350")
        self.assertEqual(result, (100, 4335000, 2685000))

    def test_fetch_filters_by_min_population(self):
        from connectors.zensus_grid_connector import ZensusGridConnector

        with mock.patch(
            "connectors.zensus_grid_connector.requests.get",
            return_value=self._fake_get(self.SAMPLE_CSV),
        ):
            result = ZensusGridConnector().fetch(
                {
                    "url": "https://example.com/zensus.csv",
                    "indicator_columns": ["Einwohner", "Alter_unter_18", "Alter_65_und_aelter"],
                    "min_population": 1,
                }
            )
        # Row with Einwohner=0 is skipped
        self.assertEqual(result.record_count, 3)
        for feat in result.feature_collection["features"]:
            self.assertEqual(feat["geometry"]["type"], "Polygon")
            self.assertGreater(feat["properties"]["Einwohner"], 0)

    def test_fetch_clips_to_workspace_bbox(self):
        from connectors.zensus_grid_connector import ZensusGridConnector

        @dataclass
        class _B:
            extent: tuple = (12.2, 51.2, 12.6, 51.5)

        @dataclass
        class _W:
            bounds: _B = None

        with mock.patch(
            "connectors.zensus_grid_connector.requests.get",
            return_value=self._fake_get(self.SAMPLE_CSV),
        ):
            result = ZensusGridConnector().fetch(
                {
                    "url": "https://example.com/zensus.csv",
                    "indicator_columns": ["Einwohner", "Alter_unter_18", "Alter_65_und_aelter"],
                    "min_population": 1,
                },
                workspace=_W(bounds=_B()),
            )
        # The far-north cell (N35000) should be outside Leipzig bbox
        self.assertLess(result.record_count, 3)

    def test_validate_config_requires_url_and_indicators(self):
        from connectors.zensus_grid_connector import ZensusGridConnector

        errors = ZensusGridConnector().validate_config({})
        self.assertTrue(any("url" in e for e in errors))
        self.assertTrue(any("indicator_columns" in e for e in errors))


class HTTPHelperTests(TestCase):
    """Shared client-cert helper used by every connector that talks HTTP."""

    def test_returns_tuple_when_both_cert_and_key_present(self):
        from connectors._http import cert_from_config, request_kwargs

        cfg = {"client_cert_path": "/c.pem", "client_key_path": "/k.pem"}
        self.assertEqual(cert_from_config(cfg), ("/c.pem", "/k.pem"))
        self.assertEqual(request_kwargs(cfg), {"cert": ("/c.pem", "/k.pem")})

    def test_returns_single_path_for_combined_pem(self):
        from connectors._http import cert_from_config

        self.assertEqual(
            cert_from_config({"client_cert_path": "/combined.pem"}),
            "/combined.pem",
        )

    def test_returns_none_when_no_cert_configured(self):
        from connectors._http import cert_from_config, request_kwargs

        self.assertIsNone(cert_from_config({}))
        self.assertEqual(request_kwargs({}), {})
        self.assertIsNone(cert_from_config(None))


class OSMTemplateExtensionsTests(TestCase):
    """The decision-support templates (kindergartens, hospitals, public
    buildings, pedestrian crossings, EV chargers) must be registered and
    must compile against a workspace bbox without hitting the network."""

    def test_new_templates_registered(self):
        from connectors.osm_connector import OVERPASS_TEMPLATES

        for tpl in (
            "kindergartens",
            "hospitals",
            "public_buildings",
            "pedestrian_crossings",
            "ev_chargers_osm",
        ):
            self.assertIn(tpl, OVERPASS_TEMPLATES)

    def test_templates_render_workspace_bbox(self):
        from connectors.osm_connector import OSMOverpassConnector

        # Re-use the same workspace stub pattern as the other tests in this file.
        @dataclass
        class _Bnds:
            extent: tuple = (12.295, 51.236, 12.549, 51.443)

        @dataclass
        class _Ws:
            bounds: _Bnds = None

        ws = _Ws(bounds=_Bnds())
        conn = OSMOverpassConnector()
        for tpl in (
            "kindergartens",
            "hospitals",
            "public_buildings",
            "pedestrian_crossings",
            "ev_chargers_osm",
        ):
            q = conn._build_query({"template": tpl}, ws)
            self.assertIn("51.236,12.295,51.443,12.549", q)
            self.assertNotIn("{bbox}", q)

    def test_overpass_call_routed_through_request_mock(self):
        """Sanity-check that fetch() round-trips the response through the
        shared element-to-feature converter for the new templates."""
        from connectors.osm_connector import OSMOverpassConnector

        sample = {
            "elements": [
                {
                    "type": "node",
                    "id": 1,
                    "lat": 51.34,
                    "lon": 12.37,
                    "tags": {"amenity": "kindergarten", "name": "Kita Süd"},
                }
            ]
        }

        @dataclass
        class _Bnds:
            extent: tuple = (12.295, 51.236, 12.549, 51.443)

        @dataclass
        class _Ws:
            bounds: _Bnds = None

        ws = _Ws(bounds=_Bnds())

        with mock.patch(
            "connectors.osm_connector.requests.post",
            return_value=_OSMFakeResponse(json_data=sample),
        ):
            result = OSMOverpassConnector().fetch({"template": "kindergartens"}, ws)

        self.assertEqual(result.record_count, 1)
        feat = result.feature_collection["features"][0]
        self.assertEqual(feat["geometry"]["type"], "Point")
        self.assertEqual(feat["properties"]["amenity"], "kindergarten")


# ---------------------------------------------------------------------------
# Mobilithek catalog browser tests
# ---------------------------------------------------------------------------

# Minimal DCAT-AP RDF/XML fixture with two datasets:
#   1. A GTFS transit feed (Deutsche Bahn)
#   2. A GeoJSON / CSV bike-counter dataset (municipality)
_DCAT_AP_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF
  xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
  xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
  xmlns:dcat="http://www.w3.org/ns/dcat#"
  xmlns:dct="http://purl.org/dc/terms/"
  xmlns:foaf="http://xmlns.com/foaf/0.1/"
  xmlns:xml="http://www.w3.org/XML/1998/namespace">

  <!-- Dataset 1: nationwide GTFS feed -->
  <dcat:Dataset rdf:about="https://mobilithek.info/offers/11111">
    <dct:title xml:lang="de">Deutschlandweites GTFS-Paket</dct:title>
    <dct:title xml:lang="en">Nationwide GTFS package</dct:title>
    <dct:description xml:lang="de">Haltestellen und Fahrtplandaten fuer ganz Deutschland.</dct:description>
    <dcat:keyword xml:lang="de">GTFS</dcat:keyword>
    <dcat:keyword xml:lang="de">Fahrplandaten</dcat:keyword>
    <dct:publisher>
      <foaf:Organization>
        <foaf:name xml:lang="de">Deutsche Bahn AG</foaf:name>
      </foaf:Organization>
    </dct:publisher>
    <dcat:distribution>
      <dcat:Distribution rdf:about="https://mobilithek.info/offers/11111/dist/1">
        <dcat:downloadURL rdf:resource="https://download.example.com/db-gtfs.zip"/>
        <dct:format>GTFS</dct:format>
        <dct:license rdf:resource="https://creativecommons.org/licenses/by/4.0/"/>
      </dcat:Distribution>
    </dcat:distribution>
  </dcat:Dataset>

  <!-- Dataset 2: bike counter GeoJSON (also has a CSV distribution) -->
  <dcat:Dataset rdf:about="https://mobilithek.info/offers/22222">
    <dct:title xml:lang="de">Radverkehrszaehlstellen Leipzig</dct:title>
    <dct:description xml:lang="de">Automatische Radverkehrszaehlung der Stadt Leipzig.</dct:description>
    <dcat:keyword xml:lang="de">Radverkehr</dcat:keyword>
    <dct:publisher>
      <foaf:Organization>
        <foaf:name xml:lang="de">Stadt Leipzig</foaf:name>
      </foaf:Organization>
    </dct:publisher>
    <dcat:distribution>
      <dcat:Distribution rdf:about="https://mobilithek.info/offers/22222/dist/1">
        <dcat:downloadURL rdf:resource="https://download.example.com/bike-counters.geojson"/>
        <dct:format>GeoJSON</dct:format>
        <dct:license rdf:resource="https://www.govdata.de/dl-de/by-2-0"/>
      </dcat:Distribution>
    </dcat:distribution>
    <dcat:distribution>
      <dcat:Distribution rdf:about="https://mobilithek.info/offers/22222/dist/2">
        <dcat:downloadURL rdf:resource="https://download.example.com/bike-counters.csv"/>
        <dct:format>CSV</dct:format>
        <dct:license rdf:resource="https://www.govdata.de/dl-de/by-2-0"/>
      </dcat:Distribution>
    </dcat:distribution>
  </dcat:Dataset>

  <!-- Dataset 3: DATEX II feed (no supported format_hint) -->
  <dcat:Dataset rdf:about="https://mobilithek.info/offers/33333">
    <dct:title xml:lang="de">Baustellen Autobahn GmbH DATEX II</dct:title>
    <dct:description xml:lang="de">Realtime-Baustellen auf Bundesautobahnen.</dct:description>
    <dcat:keyword xml:lang="de">DATEX II</dcat:keyword>
    <dcat:distribution>
      <dcat:Distribution rdf:about="https://mobilithek.info/offers/33333/dist/1">
        <dcat:accessURL rdf:resource="https://datex.example.com/roadworks"/>
        <dct:format>DATEX II</dct:format>
      </dcat:Distribution>
    </dcat:distribution>
  </dcat:Dataset>

</rdf:RDF>
"""


class MobilithekCatalogTests(TestCase):
    """Tests for mobilithek_catalog.parse_catalog and browse_catalog."""

    def _datasets(self):
        from connectors.mobilithek_catalog import parse_catalog

        return parse_catalog(_DCAT_AP_FIXTURE)

    # ------------------------------------------------------------------
    # parse_catalog
    # ------------------------------------------------------------------

    def test_parse_returns_three_datasets(self):
        datasets = self._datasets()
        self.assertEqual(len(datasets), 3)

    def test_parse_title_german_preferred(self):
        datasets = {d.uid: d for d in self._datasets()}
        # Dataset 1 has both de and en titles — German should win
        ds1 = datasets["https://mobilithek.info/offers/11111"]
        self.assertIn("GTFS", ds1.title)
        self.assertIn("Deutschland", ds1.title)

    def test_parse_publisher_extracted(self):
        datasets = {d.uid: d for d in self._datasets()}
        ds1 = datasets["https://mobilithek.info/offers/11111"]
        self.assertIn("Deutsche Bahn", ds1.publisher)

    def test_parse_keywords(self):
        datasets = {d.uid: d for d in self._datasets()}
        ds1 = datasets["https://mobilithek.info/offers/11111"]
        self.assertIn("GTFS", ds1.keywords)

    def test_parse_gtfs_distribution(self):
        datasets = {d.uid: d for d in self._datasets()}
        ds1 = datasets["https://mobilithek.info/offers/11111"]
        self.assertEqual(len(ds1.distributions), 1)
        dist = ds1.distributions[0]
        self.assertEqual(dist.url, "https://download.example.com/db-gtfs.zip")
        self.assertEqual(dist.format_hint, "gtfs")
        self.assertIn("creativecommons", dist.license_url)

    def test_parse_multiple_distributions(self):
        datasets = {d.uid: d for d in self._datasets()}
        ds2 = datasets["https://mobilithek.info/offers/22222"]
        self.assertEqual(len(ds2.distributions), 2)
        hints = {d.format_hint for d in ds2.distributions}
        self.assertIn("geojson", hints)
        self.assertIn("csv", hints)

    def test_parse_datexii_format_hint(self):
        """DATEX II gets its own format_hint value even though it's not directly parseable."""
        datasets = {d.uid: d for d in self._datasets()}
        ds3 = datasets["https://mobilithek.info/offers/33333"]
        dist = ds3.distributions[0]
        self.assertEqual(dist.format_hint, "datexii")
        self.assertEqual(dist.url, "https://datex.example.com/roadworks")

    # ------------------------------------------------------------------
    # CatalogDataset.best_distribution
    # ------------------------------------------------------------------

    def test_best_distribution_prefers_requested_format(self):
        datasets = {d.uid: d for d in self._datasets()}
        ds2 = datasets["https://mobilithek.info/offers/22222"]
        best_csv = ds2.best_distribution("csv")
        self.assertEqual(best_csv.format_hint, "csv")
        best_geojson = ds2.best_distribution("geojson")
        self.assertEqual(best_geojson.format_hint, "geojson")

    def test_best_distribution_falls_back_to_geojson(self):
        """Without an explicit preference the default priority picks geojson over csv."""
        datasets = {d.uid: d for d in self._datasets()}
        ds2 = datasets["https://mobilithek.info/offers/22222"]
        best = ds2.best_distribution()
        self.assertEqual(best.format_hint, "geojson")

    def test_has_supported_format_true(self):
        datasets = {d.uid: d for d in self._datasets()}
        self.assertTrue(datasets["https://mobilithek.info/offers/11111"].has_supported_format())
        self.assertTrue(datasets["https://mobilithek.info/offers/22222"].has_supported_format())

    def test_has_supported_format_false_for_datexii(self):
        datasets = {d.uid: d for d in self._datasets()}
        self.assertFalse(datasets["https://mobilithek.info/offers/33333"].has_supported_format())

    # ------------------------------------------------------------------
    # browse_catalog
    # ------------------------------------------------------------------

    def test_browse_no_keyword_returns_all(self):
        from connectors.mobilithek_catalog import browse_catalog

        results = browse_catalog(_xml_bytes=_DCAT_AP_FIXTURE)
        self.assertEqual(len(results), 3)

    def test_browse_keyword_filter(self):
        from connectors.mobilithek_catalog import browse_catalog

        results = browse_catalog(keyword="GTFS", _xml_bytes=_DCAT_AP_FIXTURE)
        self.assertEqual(len(results), 1)
        self.assertIn("GTFS", results[0].title)

    def test_browse_keyword_matches_description(self):
        from connectors.mobilithek_catalog import browse_catalog

        results = browse_catalog(keyword="Bundesautobahn", _xml_bytes=_DCAT_AP_FIXTURE)
        self.assertEqual(len(results), 1)
        self.assertIn("DATEX", results[0].title)

    def test_browse_keyword_matches_keywords_field(self):
        from connectors.mobilithek_catalog import browse_catalog

        results = browse_catalog(keyword="Fahrplandaten", _xml_bytes=_DCAT_AP_FIXTURE)
        self.assertEqual(len(results), 1)
        self.assertIn("GTFS", results[0].title)

    def test_browse_returns_sorted_by_title(self):
        from connectors.mobilithek_catalog import browse_catalog

        results = browse_catalog(_xml_bytes=_DCAT_AP_FIXTURE)
        titles = [r.title for r in results]
        self.assertEqual(titles, sorted(titles, key=str.lower))

    def test_browse_empty_keyword_no_match(self):
        from connectors.mobilithek_catalog import browse_catalog

        results = browse_catalog(keyword="ThisKeywordDoesNotExist", _xml_bytes=_DCAT_AP_FIXTURE)
        self.assertEqual(len(results), 0)

    # ------------------------------------------------------------------
    # get_distribution_url
    # ------------------------------------------------------------------

    def test_get_distribution_url_found(self):
        from connectors.mobilithek_catalog import get_distribution_url

        url = get_distribution_url(
            "https://mobilithek.info/offers/11111",
            _xml_bytes=_DCAT_AP_FIXTURE,
        )
        self.assertEqual(url, "https://download.example.com/db-gtfs.zip")

    def test_get_distribution_url_with_format_preference(self):
        from connectors.mobilithek_catalog import get_distribution_url

        url = get_distribution_url(
            "https://mobilithek.info/offers/22222",
            format_preference="csv",
            _xml_bytes=_DCAT_AP_FIXTURE,
        )
        self.assertEqual(url, "https://download.example.com/bike-counters.csv")

    def test_get_distribution_url_not_found(self):
        from connectors.mobilithek_catalog import get_distribution_url

        url = get_distribution_url(
            "https://mobilithek.info/offers/99999",
            _xml_bytes=_DCAT_AP_FIXTURE,
        )
        self.assertIsNone(url)

    # ------------------------------------------------------------------
    # Format normalization edge cases
    # ------------------------------------------------------------------

    def test_norm_format_media_type_uris(self):
        from connectors.mobilithek_catalog import _norm_format

        self.assertEqual(_norm_format("application/json"), "json")
        self.assertEqual(_norm_format("application/geo+json"), "geojson")
        self.assertEqual(_norm_format("https://www.iana.org/assignments/media-types/text/csv"), "csv")
        self.assertEqual(_norm_format("application/x-gtfs+zip"), "gtfs")
        self.assertIsNone(_norm_format("application/xml"))
        self.assertIsNone(_norm_format("application/octet-stream"))

    # ------------------------------------------------------------------
    # Malformed XML
    # ------------------------------------------------------------------

    def test_parse_malformed_xml_raises_value_error(self):
        from connectors.mobilithek_catalog import parse_catalog

        with self.assertRaises(ValueError):
            parse_catalog(b"<this is not valid xml >>>")

    def test_parse_empty_catalog(self):
        from connectors.mobilithek_catalog import parse_catalog

        result = parse_catalog(b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>')
        self.assertEqual(result, [])


class _OSMFakeResponse:
    """Minimal stand-in for ``requests.Response`` used by the OSM tests above.

    Other test classes in this file define their own fake responses tailored
    to the request/response shape of their connector (CSV needs ``.content``,
    Unfallatlas needs ``.content``+ encoding, etc.) — keep this one local to
    the OSM tests so it can't collide with them.
    """

    def __init__(self, json_data=None):
        self._json = json_data or {}
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._json
