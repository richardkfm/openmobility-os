"""Unfallatlas catalog loader — year→URL mapping used by both the
`seed_unfallatlas` management command and the data hub catalog browser.

The Destatis Unfallatlas portal rotates download URLs every release cycle,
so the catalog of available years lives in ``config/unfallatlas.yaml``
(with an optional per-workspace override at
``config/unfallatlas/<slug>.yaml``) rather than hard-coded in Python.

This module exposes the loader as a plain function so connectors and
admin UIs can list and pick years without going through the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from django.conf import settings

CONFIG_FILENAME = "unfallatlas.yaml"
PER_WORKSPACE_DIR = "unfallatlas"


@dataclass
class YearSpec:
    year: int
    url: str
    encoding: str


@dataclass
class CuratedSource:
    """A ready-to-add Unfallatlas release shown in the catalog browser.

    Unlike the per-year ``sources`` map (official Destatis URLs that rotate
    yearly), curated entries point at stable mirrors that can be added with
    one click — e.g. the MobilityData Foundation combined mirror.
    """

    id: str
    name: str
    url: str
    description: str
    encoding: str
    years: str  # human label, e.g. "2016–2023"


def load_year_sources(workspace_slug: str | None = None) -> list[YearSpec]:
    """Return the list of configured Unfallatlas years for a workspace.

    Per-workspace YAML overrides the repo-wide default when present.
    Years without a usable ``url`` are skipped. Returns an empty list if
    no config file exists.
    """
    data, _ = _load_data(workspace_slug)
    default_encoding = data.get("default_encoding") or "utf-8"
    raw_sources = data.get("sources") or {}
    out: list[YearSpec] = []
    for year, spec in raw_sources.items():
        try:
            year_int = int(year)
        except (TypeError, ValueError):
            continue
        if isinstance(spec, str):
            spec = {"url": spec}
        if not spec or not spec.get("url"):
            continue
        out.append(
            YearSpec(
                year=year_int,
                url=spec["url"],
                encoding=spec.get("encoding") or default_encoding,
            )
        )
    out.sort(key=lambda y: y.year)
    return out


def load_curated_catalog(workspace_slug: str | None = None) -> list[CuratedSource]:
    """Return curated, ready-to-add Unfallatlas releases from the YAML
    ``catalog:`` list. Empty list when none are configured."""
    data, _ = _load_data(workspace_slug)
    default_encoding = data.get("default_encoding") or "utf-8"
    out: list[CuratedSource] = []
    for item in data.get("catalog") or []:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        out.append(
            CuratedSource(
                id=str(item.get("id") or item["url"]),
                name=item.get("name") or item["url"],
                url=item["url"],
                description=item.get("description", ""),
                encoding=item.get("encoding") or default_encoding,
                years=str(item.get("years", "")),
            )
        )
    return out


def _load_data(workspace_slug: str | None) -> tuple[dict, Path | None]:
    """Read the most specific YAML file, return (parsed_dict, path)."""
    config_dir: Path = settings.REPO_ROOT / "config"
    paths: list[Path] = []
    if workspace_slug:
        per_ws = config_dir / PER_WORKSPACE_DIR / f"{workspace_slug}.yaml"
        if per_ws.exists():
            paths.append(per_ws)
    fallback = config_dir / CONFIG_FILENAME
    if fallback.exists():
        paths.append(fallback)

    if not paths:
        return {}, None

    data = yaml.safe_load(paths[0].read_text()) or {}
    return data, paths[0]


def _load_raw(workspace_slug: str | None) -> tuple[dict, str]:
    """Read the YAML file, return (sources_dict, default_encoding)."""
    data, _ = _load_data(workspace_slug)
    default_encoding = data.get("default_encoding") or "utf-8"
    raw_sources = data.get("sources") or {}
    return raw_sources, default_encoding


# ----------------------------------------------------------------------- #
# Backwards-compatible helpers kept for the `seed_unfallatlas` command.
# ----------------------------------------------------------------------- #


def load_year_sources_dict(
    workspace_slug: str,
    encoding_override: str = "",
) -> tuple[dict[int, dict], str]:
    """Legacy shape used by `seed_unfallatlas`: dict keyed by year."""
    raw_sources, default_encoding = _load_raw(workspace_slug)
    if encoding_override:
        default_encoding = encoding_override
    out: dict[int, dict] = {}
    for year, spec in raw_sources.items():
        try:
            year_int = int(year)
        except (TypeError, ValueError):
            continue
        if isinstance(spec, str):
            spec = {"url": spec}
        if not spec or not spec.get("url"):
            continue
        out[year_int] = {
            "url": spec["url"],
            "encoding": spec.get("encoding") or default_encoding,
        }
    return out, default_encoding
