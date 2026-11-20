"""Minimal RSS 2.0 / Atom reader (stdlib only).

Many tender portals and aggregators publish feeds; point this at a feed URL
or a saved .xml file. Fetched content is treated purely as data.
"""
from __future__ import annotations

import hashlib
import html
import re
import urllib.request
import xml.etree.ElementTree as ET

from ..models import Tender
from ._parse import parse_date

_ATOM = "{http://www.w3.org/2005/Atom}"
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str:
    return html.unescape(_TAG_RE.sub(" ", text or "")).strip()


def _read(path_or_url: str) -> bytes:
    if path_or_url.lower().startswith(("http://", "https://")):
        req = urllib.request.Request(path_or_url, headers={"User-Agent": "tender-radar/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - user-supplied feed
            return resp.read()
    with open(path_or_url, "rb") as fh:
        return fh.read()


def load_rss(path_or_url: str) -> list[Tender]:
    root = ET.fromstring(_read(path_or_url))
    tenders: list[Tender] = []

    for item in root.iter("item"):                     # RSS 2.0
        title = _clean(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        tenders.append(Tender(
            id=(item.findtext("guid") or "").strip() or hashlib.sha1(f"{title}|{link}".encode()).hexdigest()[:12],
            title=title,
            description=_clean(item.findtext("description")),
            published=parse_date(item.findtext("pubDate")),
            url=link,
            source=path_or_url,
        ))

    for entry in root.iter(f"{_ATOM}entry"):           # Atom
        title = _clean(entry.findtext(f"{_ATOM}title"))
        link_el = entry.find(f"{_ATOM}link")
        link = link_el.get("href", "") if link_el is not None else ""
        tenders.append(Tender(
            id=(entry.findtext(f"{_ATOM}id") or "").strip() or hashlib.sha1(f"{title}|{link}".encode()).hexdigest()[:12],
            title=title,
            description=_clean(entry.findtext(f"{_ATOM}summary") or entry.findtext(f"{_ATOM}content")),
            published=parse_date(entry.findtext(f"{_ATOM}updated") or entry.findtext(f"{_ATOM}published")),
            url=link,
            source=path_or_url,
        ))
    return tenders
