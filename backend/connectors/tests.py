"""Unit tests for the GTFS static connector.

Builds a tiny in-memory GTFS archive, monkey-patches ``requests.get`` to
return its bytes, and exercises each of the three output layers.
"""

import io
import zipfile
from dataclasses import dataclass
from unittest import TestCase, mock

from connectors.gtfs_connector import GTFSConnector, _circle_ring, _is_night_time


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
