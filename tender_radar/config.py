from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "categories.toml"


@dataclass
class Category:
    key: str
    name: str
    weight: float = 1.0
    keywords: list[str] = field(default_factory=list)
    strong: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


@dataclass
class Settings:
    min_score: float = 3.0
    keyword_points: float = 1.0
    strong_points: float = 3.0
    exclude_penalty: float = 4.0
    title_multiplier: float = 2.0
    urgent_days: int = 7
    global_exclude: list[str] = field(default_factory=list)


@dataclass
class Config:
    settings: Settings
    categories: dict[str, Category]


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path) if path else DEFAULT_CONFIG
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)

    settings = Settings(**raw.get("settings", {}))
    categories = {
        key: Category(key=key, **body) for key, body in raw.get("categories", {}).items()
    }
    if not categories:
        raise ValueError(f"No [categories.*] tables found in {path}")
    return Config(settings=settings, categories=categories)
