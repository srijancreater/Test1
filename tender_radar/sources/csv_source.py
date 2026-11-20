from __future__ import annotations

import csv
import hashlib

from ..models import Tender
from ._parse import parse_date, parse_value, pick


def row_to_tender(row: dict, source: str) -> Tender:
    title = pick(row, "title", "tender title", "work description", "name", "subject")
    desc = pick(row, "description", "details", "scope", "summary", "work description")
    tid = pick(row, "id", "tender id", "tender no", "reference", "ref no", "bid number")
    if not tid:
        tid = hashlib.sha1(f"{title}|{source}".encode()).hexdigest()[:12]
    return Tender(
        id=tid,
        title=title,
        description=desc if desc != title else "",
        organization=pick(row, "organization", "organisation", "department", "buyer", "authority"),
        location=pick(row, "location", "state", "city", "region"),
        value=parse_value(pick(row, "value", "estimated value", "tender value", "budget", "emd")),
        currency=pick(row, "currency", default="INR"),
        deadline=parse_date(pick(row, "deadline", "closing date", "bid end date", "due date", "submission date")),
        published=parse_date(pick(row, "published", "published date", "start date", "date")),
        url=pick(row, "url", "link"),
        source=pick(row, "source", default=source),
    )


def load_csv(path: str) -> list[Tender]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return [row_to_tender(r, path) for r in csv.DictReader(fh) if any(r.values())]
