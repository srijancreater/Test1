from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .classifier import classify_all
from .config import Config
from .models import Tender
from .sources import load_any


@dataclass
class Filters:
    categories: list[str] = field(default_factory=list)   # empty = all
    min_score: float | None = None                         # None = use config
    min_value: float | None = None
    include_expired: bool = False
    include_excluded: bool = False
    location: str | None = None


def _dedupe_key(t: Tender) -> str:
    return re.sub(r"[^a-z0-9]", "", f"{t.organization}{t.title}".lower())


def dedupe(tenders: list[Tender]) -> list[Tender]:
    seen: dict[str, Tender] = {}
    for t in tenders:
        key = _dedupe_key(t)
        # Keep the record with the most information.
        if key not in seen or len(t.description) > len(seen[key].description):
            seen[key] = t
    return list(seen.values())


def add_flags(t: Tender, config: Config, today: date) -> None:
    days = t.days_left(today)
    if days is not None:
        if days < 0:
            t.flags.append("expired")
        elif days <= config.settings.urgent_days:
            t.flags.append("urgent")
    if len(t.categories) >= 3:
        t.flags.append("multi-fit")
    if "poc" in t.categories:
        t.flags.append("pilot")


def run(sources: list[str], config: Config, filters: Filters | None = None,
        today: date | None = None) -> list[Tender]:
    filters = filters or Filters()
    today = today or date.today()

    tenders: list[Tender] = []
    for src in sources:
        tenders.extend(load_any(src))

    tenders = classify_all(dedupe(tenders), config)
    for t in tenders:
        add_flags(t, config, today)

    min_score = config.settings.min_score if filters.min_score is None else filters.min_score
    out = []
    for t in tenders:
        if t.score < min_score:
            continue
        if "excluded" in t.flags and not filters.include_excluded:
            continue
        if "expired" in t.flags and not filters.include_expired:
            continue
        if filters.categories and not set(filters.categories) & set(t.categories):
            continue
        if filters.min_value is not None and (t.value or 0) < filters.min_value:
            continue
        if filters.location and filters.location.lower() not in t.location.lower():
            continue
        out.append(t)

    # Highest score first; among equals, nearest deadline first.
    out.sort(key=lambda t: (-t.score, t.deadline or date.max))
    return out
