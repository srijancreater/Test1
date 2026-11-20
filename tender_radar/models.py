from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Tender:
    """One tender / RFP / EoI listing, normalised from any source."""

    id: str
    title: str
    description: str = ""
    organization: str = ""
    location: str = ""
    value: float | None = None          # estimated value, in the source currency
    currency: str = "INR"
    deadline: date | None = None
    published: date | None = None
    url: str = ""
    source: str = ""

    # Filled in by the classifier
    categories: dict[str, float] = field(default_factory=dict)   # category key -> score
    matched_terms: dict[str, list[str]] = field(default_factory=dict)
    score: float = 0.0
    flags: list[str] = field(default_factory=list)

    @property
    def primary_category(self) -> str | None:
        if not self.categories:
            return None
        return max(self.categories, key=self.categories.get)

    def days_left(self, today: date | None = None) -> int | None:
        if self.deadline is None:
            return None
        return (self.deadline - (today or date.today())).days

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.description}"
