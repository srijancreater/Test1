"""Tender sources. Each loader returns a list[Tender]."""
from __future__ import annotations

from pathlib import Path

from ..models import Tender
from .csv_source import load_csv
from .json_source import load_json
from .rss_source import load_rss


def load_any(path_or_url: str) -> list[Tender]:
    """Pick a loader from the file extension (or treat http(s) URLs as RSS feeds)."""
    lower = path_or_url.lower()
    if lower.startswith(("http://", "https://")):
        return load_rss(path_or_url)
    suffix = Path(lower).suffix
    if suffix == ".csv":
        return load_csv(path_or_url)
    if suffix == ".json":
        return load_json(path_or_url)
    if suffix in (".xml", ".rss", ".atom"):
        return load_rss(path_or_url)
    raise ValueError(f"Don't know how to load {path_or_url!r} (use .csv, .json, .xml or a feed URL)")


__all__ = ["load_any", "load_csv", "load_json", "load_rss"]
