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
