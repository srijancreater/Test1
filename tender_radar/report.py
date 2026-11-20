from __future__ import annotations

import csv
import html
import json
from collections import Counter
from datetime import date
from pathlib import Path

from .config import Config
from .models import Tender


def format_value(value: float | None, currency: str = "INR") -> str:
    if value is None:
        return "—"
    if currency.upper() == "INR":
        if value >= 1e7:
            return f"₹{value / 1e7:.2f} Cr"
        if value >= 1e5:
            return f"₹{value / 1e5:.1f} L"
        return f"₹{value:,.0f}"
    return f"{currency} {value:,.0f}"


# ---------------------------------------------------------------- terminal
def to_table(tenders: list[Tender], config: Config, today: date | None = None, limit: int = 50) -> str:
    today = today or date.today()
    rows = [("Score", "Category", "Days", "Value", "Organization", "Title")]
    for t in tenders[:limit]:
        cat = config.categories[t.primary_category].name if t.primary_category else "-"
        days = t.days_left(today)
        rows.append((
            f"{t.score:.1f}", cat[:28], "-" if days is None else str(days),
            format_value(t.value, t.currency), t.organization[:24], t.title[:60],
        ))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


# ---------------------------------------------------------------- csv / json
def write_csv(tenders: list[Tender], config: Config, path: str | Path, today: date | None = None) -> None:
    today = today or date.today()
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "score", "primary_category", "all_categories", "matched_terms", "flags",
                    "title", "organization", "location", "value", "currency", "deadline",
                    "days_left", "url"])
        for t in tenders:
            w.writerow([
                t.id, t.score,
                config.categories[t.primary_category].name if t.primary_category else "",
                "; ".join(config.categories[k].name for k in t.categories),
                "; ".join(sorted({m for ms in t.matched_terms.values() for m in ms})),
                ", ".join(t.flags), t.title, t.organization, t.location,
                "" if t.value is None else t.value, t.currency,
                t.deadline.isoformat() if t.deadline else "",
                "" if t.days_left(today) is None else t.days_left(today), t.url,
            ])


def write_json(tenders: list[Tender], path: str | Path) -> None:
    def enc(t: Tender) -> dict:
        return {
            "id": t.id, "title": t.title, "description": t.description,
            "organization": t.organization, "location": t.location, "value": t.value,
            "currency": t.currency, "deadline": t.deadline.isoformat() if t.deadline else None,
            "url": t.url, "score": t.score, "categories": t.categories,
            "matched_terms": t.matched_terms, "flags": t.flags,
        }
    Path(path).write_text(json.dumps([enc(t) for t in tenders], indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- html
_CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1f23;--muted:#62666d;--line:#e4e4e0;--accent:#2f5bd3;
--urgent:#c2410c;--good:#15803d;--chip:#eef1fb}
@media (prefers-color-scheme:dark){:root{--bg:#141518;--card:#1c1e22;--ink:#e8e9eb;--muted:#9a9ea6;
--line:#2c2f35;--accent:#7c9cff;--urgent:#fb923c;--good:#4ade80;--chip:#252a3a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 20px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.stat b{display:block;font-size:22px;font-variant-numeric:tabular-nums}.stat span{color:var(--muted);font-size:12px}
.bars{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin-bottom:20px}
.bar{display:grid;grid-template-columns:minmax(120px,280px) 1fr 32px;gap:10px;align-items:center;margin:4px 0;
font-size:13px;cursor:pointer}.bar i{display:block;height:10px;border-radius:5px;background:var(--accent)}
.bar.off{opacity:.35}.bar em{font-style:normal;text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}
.controls{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.controls input,.controls select{padding:8px 10px;border:1px solid var(--line);border-radius:8px;
background:var(--card);color:var(--ink);font:inherit;flex:1 1 200px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:10px}
.top{display:flex;gap:12px;align-items:flex-start;justify-content:space-between}
.card h3{margin:0;font-size:15px}.card h3 a{color:inherit}
.score{font-weight:700;font-size:18px;color:var(--accent);font-variant-numeric:tabular-nums;white-space:nowrap}
.meta{color:var(--muted);font-size:12.5px;margin:4px 0 8px}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{background:var(--chip);border-radius:999px;padding:2px 9px;font-size:12px}
.chip.flag-urgent{background:var(--urgent);color:#fff}.chip.flag-pilot,.chip.flag-multi-fit{background:var(--good);color:#fff}
.terms{color:var(--muted);font-size:12px;margin-top:8px}
details summary{cursor:pointer;color:var(--muted);font-size:12.5px;margin-top:6px}
.empty{color:var(--muted);padding:40px;text-align:center}
"""

_JS = """
const cards=[...document.querySelectorAll('.card')];const q=document.getElementById('q');
const sel=document.getElementById('cat');const fl=document.getElementById('flag');
function apply(){const s=q.value.toLowerCase(),c=sel.value,f=fl.value;let n=0;
cards.forEach(el=>{const ok=(!s||el.dataset.text.includes(s))&&(!c||el.dataset.cats.split(' ').includes(c))
&&(!f||el.dataset.flags.split(' ').includes(f));el.style.display=ok?'':'none';if(ok)n++});
document.getElementById('count').textContent=n;
document.querySelectorAll('.bar').forEach(b=>b.classList.toggle('off',!!c&&b.dataset.cat!==c));}
[q,sel,fl].forEach(e=>e.addEventListener('input',apply));
document.querySelectorAll('.bar').forEach(b=>b.addEventListener('click',()=>{
sel.value=sel.value===b.dataset.cat?'':b.dataset.cat;apply()}));
"""


def write_html(tenders: list[Tender], config: Config, path: str | Path, today: date | None = None) -> None:
    Path(path).write_text(render_html(tenders, config, today), encoding="utf-8")


def render_html(tenders: list[Tender], config: Config, today: date | None = None,
                header_extra: str = "", subtitle: str = "") -> str:
    today = today or date.today()
    e = html.escape
    counts = Counter(k for t in tenders for k in t.categories)
    top = max(counts.values(), default=1)
    total_value = sum(t.value or 0 for t in tenders if t.currency.upper() == "INR")
    urgent = sum("urgent" in t.flags for t in tenders)
    pilots = sum("poc" in t.categories for t in tenders)

    bars = "".join(
        f'<div class="bar" data-cat="{k}"><span>{e(c.name)}</span>'
        f'<i style="width:{max(counts[k] / top * 100, 1.5):.0f}%"></i><em>{counts[k]}</em></div>'
        for k, c in config.categories.items()
    )
    options = "".join(f'<option value="{k}">{e(c.name)}</option>' for k, c in config.categories.items())

    cards = []
    for t in tenders:
        days = t.days_left(today)
        deadline = f"{t.deadline:%d %b %Y} ({days} days left)" if t.deadline else "No deadline listed"
        cat_chips = "".join(
            f'<span class="chip">{e(config.categories[k].name)} · {v:g}</span>'
            for k, v in sorted(t.categories.items(), key=lambda kv: -kv[1])
        )
        flag_chips = "".join(f'<span class="chip flag-{e(f)}">{e(f)}</span>' for f in t.flags)
        terms = ", ".join(sorted({m for ms in t.matched_terms.values() for m in ms}))
        title = f'<a href="{e(t.url)}" target="_blank" rel="noopener">{e(t.title)}</a>' if t.url else e(t.title)
        desc = f"<details><summary>Description</summary><p>{e(t.description)}</p></details>" if t.description else ""
        search = e(" ".join([t.title, t.description, t.organization, t.location]).lower())
        cards.append(
            f'<article class="card" data-cats="{" ".join(t.categories)}" data-flags="{" ".join(t.flags)}" '
            f'data-text="{search}"><div class="top"><div><h3>{title}</h3>'
            f'<div class="meta">{e(t.organization or "—")} · {e(t.location or "—")} · '
            f'{format_value(t.value, t.currency)} · {deadline} · ID {e(t.id)}</div></div>'
            f'<div class="score">{t.score:.1f}</div></div>'
            f'<div class="chips">{flag_chips}{cat_chips}</div>'
            f'<div class="terms">Matched: {e(terms)}</div>{desc}</article>'
        )

    body = "".join(cards) or '<div class="empty">No tenders matched. Lower min_score or add sources.</div>'
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Tender Radar</title>
<style>{_CSS}</style></head><body><main>
<h1>Tender Radar</h1><p class="sub">AI &amp; digital transformation opportunities · {e(subtitle) or "generated"} {today:%d %b %Y}</p>
{header_extra}
<section class="stats">
<div class="stat"><b>{len(tenders)}</b><span>Matching tenders</span></div>
<div class="stat"><b>{format_value(total_value) if total_value else "—"}</b><span>Combined est. value</span></div>
<div class="stat"><b>{urgent}</b><span>Closing within {config.settings.urgent_days} days</span></div>
<div class="stat"><b>{pilots}</b><span>PoC / pilot opportunities</span></div>
</section>
<section class="bars">{bars}</section>
<div class="controls"><input id="q" placeholder="Search title, buyer, location…">
<select id="cat"><option value="">All categories</option>{options}</select>
<select id="flag"><option value="">Any flag</option><option value="urgent">Urgent</option>
<option value="pilot">Pilot</option><option value="multi-fit">Multi-fit</option></select></div>
<p class="sub">Showing <span id="count">{len(tenders)}</span> tenders</p>
{body}</main><script>{_JS}</script></body></html>"""
    return page
