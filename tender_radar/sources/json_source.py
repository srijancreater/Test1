from __future__ import annotations

import json

from ..models import Tender
from .csv_source import row_to_tender


def load_json(path: str) -> list[Tender]:
    """Accept a list of objects, or {"tenders": [...]} / {"items": [...]} / {"data": [...]}."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        for key in ("tenders", "items", "data", "results"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON list of tenders")
    return [row_to_tender(r, path) for r in data if isinstance(r, dict)]
