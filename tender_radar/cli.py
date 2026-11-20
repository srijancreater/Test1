"""Command-line interface.

    tender-radar scan data/sample_tenders.csv
    tender-radar scan feeds.txt --html out/report.html --csv out/report.csv
    tender-radar explain data/sample_tenders.csv --id GEM/2026/B/1001
    tender-radar categories
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from . import __version__
from .classifier import classify
from .config import load_config
from .pipeline import Filters, run
from .report import to_table, write_csv, write_html, write_json
from .sources import load_any


def _expand_sources(items: list[str]) -> list[str]:
    """A .txt argument is a list of sources (one path/URL per line, # for comments)."""
    out: list[str] = []
    for item in items:
        if item.lower().endswith(".txt") and Path(item).is_file():
            for line in Path(item).read_text(encoding="utf-8").splitlines():
                line = line.split("#", 1)[0].strip()
                if line:
                    out.append(line)
        else:
            out.append(item)
    return out


def cmd_scan(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    unknown = set(args.category or []) - set(config.categories)
    if unknown:
        print(f"Unknown category: {', '.join(sorted(unknown))}. Run `tender-radar categories`.", file=sys.stderr)
        return 2
    today = date.fromisoformat(args.today) if args.today else date.today()
    filters = Filters(
        categories=args.category or [], min_score=args.min_score, min_value=args.min_value,
        include_expired=args.include_expired, location=args.location,
    )
    tenders = run(_expand_sources(args.sources), config, filters, today=today)

    print(to_table(tenders, config, today, limit=args.limit))
    print(f"\n{len(tenders)} matching tenders")
    for flag, writer in ((args.html, write_html), (args.csv, write_csv)):
        if flag:
            Path(flag).parent.mkdir(parents=True, exist_ok=True)
            writer(tenders, config, flag, today)
            print(f"wrote {flag}")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        write_json(tenders, args.json)
        print(f"wrote {args.json}")
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    for src in _expand_sources(args.sources):
        for t in load_any(src):
            if t.id == args.id:
                classify(t, config)
                print(f"{t.title}\nscore: {t.score}   flags: {', '.join(t.flags) or '-'}\n")
                for k, v in sorted(t.categories.items(), key=lambda kv: -kv[1]):
                    print(f"  {config.categories[k].name:<48} {v:>6}   {', '.join(t.matched_terms[k])}")
                if not t.categories:
                    print("  (no category matched)")
                return 0
    print(f"Tender {args.id!r} not found", file=sys.stderr)
    return 1


def cmd_categories(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    for k, c in config.categories.items():
        print(f"{k:<14} x{c.weight:<4} {c.name}  ({len(c.keywords)} keywords, {len(c.strong)} strong)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tender-radar", description=__doc__.split("\n")[0])
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config", help="path to categories.toml (default: config/categories.toml)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scan", help="load, classify, filter and rank tenders")
    s.add_argument("sources", nargs="+", help=".csv / .json / .xml files, feed URLs, or a .txt list of them")
    s.add_argument("-c", "--category", action="append", help="only these category keys (repeatable)")
    s.add_argument("--min-score", type=float)
    s.add_argument("--min-value", type=float, help="minimum estimated value")
    s.add_argument("--location", help="substring match on location")
    s.add_argument("--include-expired", action="store_true")
    s.add_argument("--limit", type=int, default=50, help="rows in the terminal table")
    s.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    s.add_argument("--html", help="write an interactive HTML dashboard")
    s.add_argument("--csv", help="write a CSV for the bid tracker")
    s.add_argument("--json", help="write JSON")
    s.set_defaults(func=cmd_scan)

    e = sub.add_parser("explain", help="show why one tender scored the way it did")
    e.add_argument("sources", nargs="+")
    e.add_argument("--id", required=True)
    e.set_defaults(func=cmd_explain)

    c = sub.add_parser("categories", help="list configured target categories")
    c.set_defaults(func=cmd_categories)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
