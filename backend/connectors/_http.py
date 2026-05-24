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
