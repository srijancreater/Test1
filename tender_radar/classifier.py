"""Keyword-based tender classifier.

Deliberately transparent: every score can be explained by the matched terms,
which matters when a bid manager has to justify a go / no-go decision.
"""
from __future__ import annotations

import re
from functools import lru_cache

from .config import Config
from .models import Tender


@lru_cache(maxsize=4096)
def _pattern(term: str) -> re.Pattern[str]:
    # Whole-word / whole-phrase match; tolerate '-' or whitespace between words.
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", term.strip().lower()) if p]
    body = r"[\s\-]+".join(parts)
    return re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])")


def _hits(terms: list[str], text: str) -> list[str]:
    return [t for t in terms if _pattern(t).search(text)]


def classify(tender: Tender, config: Config) -> Tender:
    s = config.settings
    title = tender.title.lower()
    body = tender.description.lower()
    full = f"{title}\n{body}"

    tender.categories.clear()
    tender.matched_terms.clear()
    tender.flags = [f for f in tender.flags if f != "excluded"]

    global_excl = _hits(s.global_exclude, full)

    for key, cat in config.categories.items():
        score = 0.0
        matched: list[str] = []
        for terms, points in ((cat.keywords, s.keyword_points), (cat.strong, s.strong_points)):
            for term in terms:
                pat = _pattern(term)
                in_title = bool(pat.search(title))
                in_body = bool(pat.search(body))
                if in_title or in_body:
                    score += points * (s.title_multiplier if in_title else 1.0)
                    matched.append(term)
        if not matched:
            continue
        score -= s.exclude_penalty * len(_hits(cat.exclude, full))
        score *= cat.weight
        if score > 0:
            tender.categories[key] = round(score, 2)
            tender.matched_terms[key] = matched

    if tender.categories:
        ordered = sorted(tender.categories.values(), reverse=True)
        # Primary category counts fully, secondary ones add a breadth bonus.
        total = ordered[0] + 0.25 * sum(ordered[1:])
        total -= s.exclude_penalty * len(global_excl)
        tender.score = round(max(total, 0.0), 2)
    else:
        tender.score = 0.0

    if global_excl:
        tender.flags.append("excluded")
    return tender


def classify_all(tenders: list[Tender], config: Config) -> list[Tender]:
    return [classify(t, config) for t in tenders]
