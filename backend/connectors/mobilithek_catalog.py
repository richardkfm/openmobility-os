"""Mobilithek DCAT-AP catalog browser.

Fetches and parses the Mobilithek metadata feed so operators can search for
datasets by keyword and pick a distribution URL without manual URL hunting.

Usage — from a Django shell or management command::

    from connectors.mobilithek_catalog import browse_catalog

    # Search for transit feeds
    datasets = browse_catalog(keyword="GTFS")
    for ds in datasets:
        best = ds.best_distribution()
        if best:
            print(ds.title, "→", best.url)

    # Get a specific dataset's URL
    from connectors.mobilithek_catalog import get_distribution_url
    url = get_distribution_url("https://mobilithek.info/offers/123456", format_preference="gtfs")

Mobilithek publishes its catalog as a DCAT-AP RDF/XML document at
``CATALOG_URL``. The connector parses dataset titles, descriptions,
publishers, and distributions (with format + download URL), then lets
callers filter by keyword and pick the best format.

This module makes no network calls when ``_xml_bytes`` is injected (used in
tests). The live feed is fetched with a 60-second timeout and the standard
OpenMobility-OS ``User-Agent``.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Public catalog endpoint
# ---------------------------------------------------------------------------

CATALOG_URL = "https://mobilithek.info/mdp-api/files/catalogue/DCAT-AP.rdf"
_USER_AGENT = "OpenMobility-OS/1 (mobilithek-catalog-browser; +https://github.com/openMobilityOS)"

# ---------------------------------------------------------------------------
# XML namespace map — covers DCAT-AP EU standard + German extensions
# ---------------------------------------------------------------------------

_NS = {
    "rdf":    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs":   "http://www.w3.org/2000/01/rdf-schema#",
    "dcat":   "http://www.w3.org/ns/dcat#",
    "dct":    "http://purl.org/dc/terms/",
    "foaf":   "http://xmlns.com/foaf/0.1/",
    "vcard":  "http://www.w3.org/2006/vcard/ns#",
    "skos":   "http://www.w3.org/2004/02/skos/core#",
    "schema": "http://schema.org/",
    "adms":   "http://www.w3.org/ns/adms#",
    "locn":   "http://www.w3.org/ns/locn#",
    "owl":    "http://www.w3.org/2002/07/owl#",
    "spdx":   "http://spdx.org/rdf/terms#",
}

_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_RDF_ABOUT = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
_RDF_RESOURCE = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"

# Format preference order when no explicit preference is given
_FORMAT_PREFERENCE = ("gtfs", "geojson", "json", "csv", "netex", "datexii", "gbfs")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CatalogDistribution:
    """One distribution (= downloadable file) from a Mobilithek dataset."""

    url: str
    """Direct download or access URL."""

    format_label: str = ""
    """Raw format label from the feed, e.g. ``"GTFS"``, ``"application/json"``."""

    format_hint: Optional[str] = None
    """MobilithekConnector-compatible ``format_hint`` value, or ``None`` if
    the format cannot be mapped to a supported parser."""

    license_url: str = ""
    """License URI (SPDX, CC, DL-DE, …)."""

    media_type: str = ""
    """IANA media-type URI, if provided."""


@dataclass
class CatalogDataset:
    """One dataset entry from the Mobilithek DCAT-AP feed."""

    uid: str
    """``rdf:about`` URI — stable identifier for this dataset."""

    title: str = ""
    """Human-readable title (German preferred, English fallback)."""

    description: str = ""
    """Free-text description."""

    publisher: str = ""
    """Name of the publishing organisation."""

    keywords: list[str] = field(default_factory=list)
    """DCAT keyword tags."""

    distributions: list[CatalogDistribution] = field(default_factory=list)
    """All available distributions sorted by mapped format."""

    def best_distribution(
        self, format_preference: Optional[str] = None
    ) -> Optional[CatalogDistribution]:
        """Return the best distribution for a given format preference.

        Falls back through ``_FORMAT_PREFERENCE`` when no preference is given.
        Returns ``None`` if there are no distributions at all.
        """
        if not self.distributions:
            return None
        if format_preference:
            fp = format_preference.lower().strip()
            for d in self.distributions:
                if d.format_hint == fp:
                    return d
        for fmt in _FORMAT_PREFERENCE:
            for d in self.distributions:
                if d.format_hint == fmt:
                    return d
        return self.distributions[0]

    # Formats the MobilithekConnector (and its inner parsers) can directly handle
    _PARSEABLE: frozenset[str] = frozenset({"gtfs", "geojson", "json", "csv"})

    def has_supported_format(self) -> bool:
        """Return True if at least one distribution can be directly parsed
        by ``MobilithekConnector`` without additional tooling."""
        return any(d.format_hint in self._PARSEABLE for d in self.distributions)


# ---------------------------------------------------------------------------
# Format normalization
# ---------------------------------------------------------------------------

def _norm_format(raw: str) -> Optional[str]:
    """Map a raw format label or IANA media-type to a connector format_hint.

    Examples:
        "GTFS"                                   → "gtfs"
        "application/geo+json"                   → "geojson"
        "https://www.iana.org/.../application/json" → "json"
        "text/csv"                               → "csv"
        "application/xml"                        → None  (DATEX II, NeTEx, …)
    """
    s = raw.lower()
    if "gtfs" in s:
        return "gtfs"
    if "geo+json" in s or "geojson" in s:
        return "geojson"
    if "netex" in s or "transmodel" in s:
        return "netex"
    if "datex" in s:
        return "datexii"
    if "gbfs" in s:
        return "gbfs"
    if "json" in s:
        return "json"
    if "csv" in s or "comma" in s:
        return "csv"
    return None


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _lang_text(elem: ET.Element, tag: str, preferred_langs: tuple[str, ...] = ("de", "en")) -> str:
    """Return the text of the first child matching ``tag``, preferring
    ``preferred_langs`` in order.  Falls back to any language if none match."""
    children = elem.findall(tag, _NS)
    if not children:
        return ""
    # Try preferred languages in order
    for lang in preferred_langs:
        for c in children:
            if c.get(_XML_LANG, "").startswith(lang):
                return (c.text or "").strip()
    # No language match — return first non-empty text
    for c in children:
        text = (c.text or "").strip()
        if text:
            return text
    return ""


def _rdf_resource_or_text(elem: ET.Element) -> str:
    """Get ``rdf:resource`` attribute or text content (whichever is present)."""
    resource = elem.get(_RDF_RESOURCE)
    if resource:
        return resource.strip()
    return (elem.text or "").strip()


def _keywords(elem: ET.Element) -> list[str]:
    """Collect all ``dcat:keyword`` values from a dataset element."""
    result = []
    for kw_elem in elem.findall("dcat:keyword", _NS):
        text = (kw_elem.text or "").strip()
        if text:
            result.append(text)
    return result


# ---------------------------------------------------------------------------
# Distribution parser
# ---------------------------------------------------------------------------

def _parse_distribution(dist_elem: ET.Element) -> Optional[CatalogDistribution]:
    """Parse a ``dcat:Distribution`` XML element into a ``CatalogDistribution``.

    Returns ``None`` if no usable URL can be extracted.
    """
    # Prefer downloadURL over accessURL
    url = ""
    for url_tag in ("dcat:downloadURL", "dcat:accessURL"):
        url_elem = dist_elem.find(url_tag, _NS)
        if url_elem is not None:
            candidate = _rdf_resource_or_text(url_elem)
            if candidate:
                url = candidate
                break
    if not url:
        return None

    # Format: try dct:format first, then dcat:mediaType
    fmt_label = ""
    fmt_elem = dist_elem.find("dct:format", _NS)
    if fmt_elem is not None:
        # May be a plain literal or a rdf:resource URI
        fmt_label = _rdf_resource_or_text(fmt_elem)
        # Unwrap nested IMT value if present (common DCAT-AP pattern)
        imt_elem = fmt_elem.find("rdf:Description", _NS)
        if imt_elem is not None:
            label_elem = imt_elem.find("rdfs:label", _NS)
            if label_elem is not None and label_elem.text:
                fmt_label = label_elem.text.strip()

    media_type = ""
    mt_elem = dist_elem.find("dcat:mediaType", _NS)
    if mt_elem is not None:
        media_type = _rdf_resource_or_text(mt_elem)
        if not fmt_label:
            fmt_label = media_type

    # License
    license_url = ""
    lic_elem = dist_elem.find("dct:license", _NS)
    if lic_elem is not None:
        license_url = _rdf_resource_or_text(lic_elem)

    return CatalogDistribution(
        url=url,
        format_label=fmt_label,
        format_hint=_norm_format(fmt_label),
        license_url=license_url,
        media_type=media_type,
    )


# ---------------------------------------------------------------------------
# Dataset parser
# ---------------------------------------------------------------------------

def _parse_dataset(ds_elem: ET.Element) -> Optional[CatalogDataset]:
    """Parse a ``dcat:Dataset`` XML element into a ``CatalogDataset``.

    Returns ``None`` if neither a UID nor title can be found.
    """
    uid = ds_elem.get(_RDF_ABOUT, "").strip()
    title = _lang_text(ds_elem, "dct:title")
    if not uid and not title:
        return None

    description = _lang_text(ds_elem, "dct:description")

    # Publisher — may be foaf:Organization or foaf:Agent (inline or referenced)
    publisher = ""
    pub_wrapper = ds_elem.find("dct:publisher", _NS)
    if pub_wrapper is not None:
        for agent_tag in ("foaf:Organization", "foaf:Agent", "foaf:Person"):
            agent_elem = pub_wrapper.find(agent_tag, _NS)
            if agent_elem is not None:
                publisher = _lang_text(agent_elem, "foaf:name") or _lang_text(
                    agent_elem, "rdfs:label"
                )
                break
        if not publisher:
            # Referenced via rdf:resource
            resource = pub_wrapper.get(_RDF_RESOURCE, "")
            if resource:
                publisher = resource

    # Distributions (inline dcat:Distribution elements)
    distributions: list[CatalogDistribution] = []
    for dist_wrapper in ds_elem.findall("dcat:distribution", _NS):
        # Inline distribution
        dist_inner = dist_wrapper.find("dcat:Distribution", _NS)
        if dist_inner is not None:
            dist = _parse_distribution(dist_inner)
            if dist:
                distributions.append(dist)
        else:
            # Bare reference — treat the rdf:resource as the access URL with unknown format
            ref_url = dist_wrapper.get(_RDF_RESOURCE, "")
            if ref_url:
                distributions.append(
                    CatalogDistribution(url=ref_url, format_hint=_norm_format(ref_url))
                )

    return CatalogDataset(
        uid=uid,
        title=title,
        description=description,
        publisher=publisher,
        keywords=_keywords(ds_elem),
        distributions=distributions,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_catalog(xml_bytes: bytes) -> list[CatalogDataset]:
    """Parse a DCAT-AP RDF/XML document into a list of ``CatalogDataset`` objects.

    All parsing errors within individual dataset elements are silently skipped
    so that a single malformed entry does not abort the full catalog parse.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"Could not parse DCAT-AP XML: {exc}") from exc

    datasets: list[CatalogDataset] = []

    # Top-level dcat:Dataset elements (typical DCAT-AP RDF/XML layout)
    for ds_elem in root.findall("dcat:Dataset", _NS):
        ds = _parse_dataset(ds_elem)
        if ds:
            datasets.append(ds)

    # Some feeds wrap datasets inside a dcat:Catalog element
    for catalog_elem in root.findall("dcat:Catalog", _NS):
        for member_tag in ("dcat:dataset", "dcat:record"):
            for wrapper in catalog_elem.findall(member_tag, _NS):
                inner_ds = wrapper.find("dcat:Dataset", _NS)
                if inner_ds is not None:
                    ds = _parse_dataset(inner_ds)
                    if ds:
                        datasets.append(ds)

    return datasets


def browse_catalog(
    keyword: Optional[str] = None,
    *,
    catalog_url: str = CATALOG_URL,
    timeout: int = 60,
    _xml_bytes: Optional[bytes] = None,
) -> list[CatalogDataset]:
    """Fetch the Mobilithek DCAT-AP feed and return matching datasets.

    Args:
        keyword:     Optional search term matched case-insensitively against
                     dataset title, description, and keywords. Returns all
                     datasets when ``None``.
        catalog_url: Override the default Mobilithek DCAT-AP endpoint.
        timeout:     HTTP timeout in seconds (default: 60).
        _xml_bytes:  Inject raw XML bytes — use in tests to avoid network calls.

    Returns:
        List of ``CatalogDataset`` objects, sorted by title (ascending,
        case-insensitive).
    """
    if _xml_bytes is None:
        response = requests.get(
            catalog_url,
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
        )
        response.raise_for_status()
        xml_bytes: bytes = response.content
    else:
        xml_bytes = _xml_bytes

    datasets = parse_catalog(xml_bytes)

    if keyword:
        kw = keyword.lower()
        datasets = [
            d
            for d in datasets
            if kw in d.title.lower()
            or kw in d.description.lower()
            or any(kw in k.lower() for k in d.keywords)
        ]

    return sorted(datasets, key=lambda d: d.title.lower())


def get_distribution_url(
    dataset_uid: str,
    format_preference: Optional[str] = None,
    *,
    catalog_url: str = CATALOG_URL,
    timeout: int = 60,
    _xml_bytes: Optional[bytes] = None,
) -> Optional[str]:
    """Look up a dataset by its UID and return its best distribution URL.

    Useful from a Django shell or management command to resolve a Mobilithek
    dataset ID into the ``distribution_url`` that ``MobilithekConnector`` expects::

        url = get_distribution_url("https://mobilithek.info/offers/12345", "gtfs")

    Returns ``None`` if the dataset is not found or has no usable distribution.
    """
    all_datasets = browse_catalog(
        catalog_url=catalog_url,
        timeout=timeout,
        _xml_bytes=_xml_bytes,
    )
    for ds in all_datasets:
        if ds.uid == dataset_uid:
            dist = ds.best_distribution(format_preference)
            return dist.url if dist else None
    return None
