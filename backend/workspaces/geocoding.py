"""Place-name geocoding via OpenStreetMap Nominatim.

Used by the new-workspace wizard so an administrator can type a place name
(city, town, municipality, region, country) and have the bounding box, map
center, and country code filled in automatically — instead of looking up and
typing four coordinates by hand.

City-agnostic by construction: Nominatim covers the entire planet and nothing
here is wired to a specific place. Open and self-hostable: the endpoint is
configurable via ``OSM_NOMINATIM_API`` so a municipality can point at its own
Nominatim instance instead of the public one (same pattern as the Overpass
connector). No proprietary geocoder is involved.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests
from django.conf import settings


class GeocodingError(Exception):
    """Raised when a geocoding lookup cannot be completed."""


@dataclass(frozen=True)
class GeocodeResult:
    """A single resolved place."""

    name: str
    display_name: str
    # Bounding box in (west, south, east, north) order — i.e. (min lon, min lat,
    # max lon, max lat), matching the wizard's bbox fields and Polygon.from_bbox.
    bbox: tuple[float, float, float, float]
    # Center point as (lon, lat).
    center: tuple[float, float]
    country_code: str

    def as_dict(self) -> dict:
        minx, miny, maxx, maxy = self.bbox
        lon, lat = self.center
        return {
            "name": self.name,
            "display_name": self.display_name,
            "country_code": self.country_code,
            "bbox": {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy},
            "center": {"lon": lon, "lat": lat},
        }


def _user_agent() -> str:
    # Nominatim's usage policy requires a meaningful User-Agent identifying the
    # application so operators can get in touch. Mirrors the Overpass connector.
    version = getattr(settings, "PLATFORM_VERSION", "0.0.0")
    repo_url = getattr(
        settings, "PROJECT_REPO_URL", "https://github.com/richardkfm/openmobility-os"
    )
    return f"OpenMobilityOS/{version} (+{repo_url})"


def _parse_result(item: dict) -> GeocodeResult | None:
    """Turn one raw Nominatim record into a GeocodeResult, or None if unusable."""
    try:
        # Nominatim returns boundingbox as [south, north, west, east] strings.
        south, north, west, east = (float(v) for v in item["boundingbox"])
        lon = float(item["lon"])
        lat = float(item["lat"])
    except (KeyError, TypeError, ValueError):
        return None

    address = item.get("address") or {}
    country_code = (address.get("country_code") or "").upper()[:2]
    display_name = item.get("display_name", "")
    # The first comma-separated component is the most specific name (the city
    # itself), which is the sensible default for the workspace name.
    name = item.get("name") or display_name.split(",")[0].strip()

    return GeocodeResult(
        name=name,
        display_name=display_name,
        bbox=(west, south, east, north),
        center=(lon, lat),
        country_code=country_code,
    )


def geocode_place(
    query: str, *, limit: int = 5, country_code: str | None = None
) -> list[GeocodeResult]:
    """Look up a place by name and return matching results, best match first.

    Raises ``GeocodingError`` on a network/HTTP/parse failure so callers can
    surface a clean message. Returns an empty list when the place is simply not
    found.
    """
    query = (query or "").strip()
    if not query:
        return []

    endpoint = settings.OSM_NOMINATIM_API
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": max(1, min(limit, 10)),
        "addressdetails": 1,
    }
    if country_code:
        params["countrycodes"] = country_code.lower()[:2]

    try:
        response = requests.get(
            endpoint,
            params=params,
            headers={"User-Agent": _user_agent(), "Accept": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise GeocodingError(str(exc)) from exc
    except ValueError as exc:  # invalid JSON
        raise GeocodingError("Geocoder returned an invalid response.") from exc

    if not isinstance(payload, list):
        raise GeocodingError("Geocoder returned an unexpected response.")

    results = [r for r in (_parse_result(item) for item in payload) if r is not None]
    return results
