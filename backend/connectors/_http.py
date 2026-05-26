"""Shared HTTP-request helpers for connectors.

Today: support for client-certificate (mutual-TLS) authentication. Used by
the Mobilithek connector's subscriber mode to plumb an X.509 client cert
through the inner GTFS / CSV / GeoJSON parsers, and available to any other
connector that needs to talk to a mutual-TLS endpoint (e.g. a state-level
DATEX II feed, a corporate-firewalled WFS).

Config keys (read by every connector that calls ``request_kwargs``):

- ``client_cert_path`` — filesystem path to the client certificate (PEM).
  Mount these as Docker secrets / env-injected file paths; never check the
  files themselves into the repo.
- ``client_key_path`` — filesystem path to the matching private key (PEM).
  Optional: if omitted, ``client_cert_path`` is expected to be a combined
  PEM containing both.
"""

from __future__ import annotations

import os


def cert_from_config(config: dict):
    """Return a value suitable for ``requests.get(..., cert=…)``.

    Returns ``None`` if no client certificate is configured.
    """
    cert = (config or {}).get("client_cert_path")
    key = (config or {}).get("client_key_path")
    if cert and key:
        return (cert, key)
    if cert:
        return cert
    return None


def request_kwargs(config: dict) -> dict:
    """Build keyword args for ``requests.get`` / ``requests.head`` from config.

    Currently emits ``cert=`` only. Designed so callers can simply splat
    the result: ``requests.get(url, timeout=60, **request_kwargs(config))``.
    """
    cert = cert_from_config(config)
    if cert is not None:
        return {"cert": cert}
    return {}


def is_local_path(url: str) -> bool:
    """Return True when *url* points to a local file rather than a remote URL."""
    if not url:
        return False
    # Absolute Unix path or file:// URI
    if url.startswith("/") or url.startswith("file://"):
        return True
    # Absolute Windows path (e.g. C:\...)
    if len(url) > 2 and url[1] == ":" and url[2] in ("/", "\\"):
        return True
    return False


def fetch_bytes(url: str, config: dict, timeout: int = 60) -> bytes:
    """Fetch raw bytes from either a local filesystem path or a remote URL.

    When *url* looks like a local path (starts with ``/``, ``file://``, or a
    Windows drive letter) the file is read directly from disk; no HTTP request
    is made.  For all other values an authenticated HTTP GET is performed using
    the shared ``request_kwargs`` helper so mutual-TLS and other config keys
    are honoured automatically.

    This function is used by the CSV and GeoJSON connectors to transparently
    support operator-uploaded source files stored in MEDIA_ROOT alongside
    regular remote-URL data sources.
    """
    if is_local_path(url):
        path = url.replace("file://", "")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Local source file not found: {path}")
        with open(path, "rb") as fh:
            return fh.read()

    import requests  # noqa: PLC0415 — lazy import to keep module light

    response = requests.get(url, timeout=timeout, **request_kwargs(config))
    response.raise_for_status()
    return response.content
