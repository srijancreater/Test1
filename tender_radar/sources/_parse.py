from __future__ import annotations

import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime

_DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y",
    "%d-%B-%Y", "%d %B %Y", "%Y/%m/%d", "%b %d, %Y", "%B %d, %Y",
)


def parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    # Drop a trailing time component like "10:00 AM" or "T17:00:00Z"
    candidate = re.split(r"[ T]\d{1,2}:\d{2}", text)[0].strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(text).date()   # RFC 822 (RSS pubDate)
    except (TypeError, ValueError, IndexError):
        return None


_MULTIPLIERS = {"cr": 1e7, "crore": 1e7, "crores": 1e7, "lakh": 1e5, "lakhs": 1e5,
                "lac": 1e5, "k": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9}


def parse_value(value: object) -> float | None:
    """Parse '₹ 2.5 Cr', '45,00,000', '1.2 million', 350000 → float."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*([a-z]+)?", text)
    if not m:
        return None
    number = float(m.group(1))
    unit = (m.group(2) or "").strip(".")
    return number * _MULTIPLIERS.get(unit, 1.0)


def pick(row: dict, *names: str, default: str = "") -> str:
    """Return the first non-empty value among several possible column names."""
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for name in names:
        v = lowered.get(name)
        if v not in (None, ""):
            return str(v).strip()
    return default
