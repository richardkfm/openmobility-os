"""Restrict normalized GeoJSON features to a focus area.

Normalized feature sets are stored as JSON blobs rather than per-feature rows
(see ``datasets.NormalizedFeatureSet``), so there is no PostGIS query to filter
them with. This module does the spatial restriction in Python using GEOS, which
GeoDjango already provides — no new dependency, and no assumption about the
database backend.

The rule is intersection, not containment: a street that runs through the area
counts, even though most of it lies outside. Requiring containment would drop
exactly the corridors an area target is usually about.
"""

import json

from django.contrib.gis.gdal.error import GDALException
from django.contrib.gis.geos import GEOSGeometry
from django.contrib.gis.geos.error import GEOSException

# One malformed feature in a real-world dataset must never sink a whole plan,
# so every geometry conversion funnels through here and fails soft.
GEOMETRY_ERRORS = (ValueError, TypeError, KeyError, GDALException, GEOSException)


def to_geos(geojson_geometry):
    """Build a GEOS geometry from a GeoJSON geometry dict, or None if invalid."""
    if not geojson_geometry:
        return None
    try:
        return GEOSGeometry(json.dumps(geojson_geometry), srid=4326)
    except GEOMETRY_ERRORS:
        return None


def clip_features(features, area_geom, *, prepared=None):
    """Return the features that intersect ``area_geom``.

    Geometry is left untouched — a street is kept whole rather than cut at the
    boundary, because the connectors' properties (length, lane count, parking
    spaces) describe the whole way and would become wrong if the geometry were
    trimmed without recomputing them. Callers that need the inside-length say so
    explicitly via :func:`inside_fraction`.
    """
    if area_geom is None:
        return list(features or [])
    test = prepared if prepared is not None else area_geom.prepared
    kept = []
    for feature in features or []:
        geom = to_geos(feature.get("geometry"))
        if geom is None:
            continue
        try:
            if test.intersects(geom):
                kept.append(feature)
        except GEOMETRY_ERRORS:
            continue
    return kept


def clip_by_layer(features_by_layer: dict, area_geom) -> dict:
    """Clip several layers at once, reusing one prepared geometry."""
    if area_geom is None:
        return dict(features_by_layer)
    prepared = area_geom.prepared
    return {
        kind: clip_features(features, area_geom, prepared=prepared)
        for kind, features in features_by_layer.items()
    }


def inside_fraction(feature, area_geom) -> float:
    """How much of a feature lies inside the area, from 0.0 to 1.0.

    Used where a proportional reading matters (e.g. how many of a street's
    parking spaces are actually in the area). Returns 1.0 when the measure
    cannot be taken, which is the conservative reading for harm-reduction
    accounting: it never inflates the share of a segment credited to the area.
    """
    geom = to_geos(feature.get("geometry"))
    if geom is None or area_geom is None:
        return 1.0
    try:
        inside = geom.intersection(area_geom)
    except GEOMETRY_ERRORS:
        return 1.0
    total = geom.length or 0.0
    if not total:
        return 1.0 if area_geom.intersects(geom) else 0.0
    return round(min(inside.length / total, 1.0), 4)
