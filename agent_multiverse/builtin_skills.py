"""Built-in everyday skills. Add more by dropping a file into skills_contrib/ (see README)."""
from __future__ import annotations

import ast
import csv
import io
import operator
import re
import statistics
from collections import Counter

from .skills import skill

_STOP = set("a an the and or but if of to in on for with at by from is are was were be been it this that as not "
            "we you they he she i our your their will would can could should has have had do does did so than then".split())


@skill(tags={"department:research", "department:comms", "department:data"})
async def summarize(text: str, max_sentences: int = 3, ctx=None) -> str:
    """Summarize text into a few sentences."""
    if ctx is not None and ctx.fleet.llm.is_live:
        return await ctx.llm(f"Summarize in at most {max_sentences} sentences:\n\n{text}")
    sents = re.split(r"(?<=[.!?])\s+", text.strip())
    words = Counter(w for w in re.findall(r"[a-z']+", text.lower()) if w not in _STOP)
    ranked = sorted(sents, key=lambda s: -sum(words[w] for w in re.findall(r"[a-z']+", s.lower())))
    keep = set(ranked[:max_sentences])
    return " ".join(s for s in sents if s in keep)


@skill(tags={"department:research", "department:data"})
def extract_keywords(text: str, top: int = 8) -> list[str]:
    """Return the most important keywords in a text."""
    words = Counter(w for w in re.findall(r"[a-z][a-z'-]{2,}", text.lower()) if w not in _STOP)
    return [w for w, _ in words.most_common(top)]


@skill(tags={"department:ops", "department:comms"})
def extract_action_items(text: str) -> list[str]:
    """Pull action items / todos out of notes, emails or meeting transcripts."""
    pat = re.compile(r"(?i)^\s*(?:[-*]\s*)?(?:todo|action|ai|follow[- ]up|need to|please|must|should)\b[:\s-]*(.+)$")
    items = []
    for line in text.splitlines():
        if m := pat.match(line):
            items.append(m.group(1).strip())
        elif line.strip().startswith(("-", "*", "[ ]")):
            items.append(line.strip().lstrip("-*[] ").strip())
    return [i for i in items if i]


@skill(tags={"department:comms"})
async def draft_email(to: str, purpose: str, tone: str = "friendly, concise", ctx=None) -> dict:
    """Draft (not send) an email for a given purpose. Returns subject and body."""
    if ctx is not None and ctx.fleet.llm.is_live:
        body = await ctx.llm(f"Write a {tone} email to {to}. Purpose: {purpose}. Return only the body text.")
    else:
        body = f"Hi {to.split('@')[0].title()},\n\n{purpose.strip().rstrip('.')}.\n\nThanks,\n"
    subject = purpose.strip().split(".")[0][:70]
    return {"to": to, "subject": subject[:1].upper() + subject[1:], "body": body}


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv, ast.USub: operator.neg,
        ast.UAdd: operator.pos}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


@skill(tags={"department:finance", "department:data"})
def calculate(expression: str) -> float:
    """Safely evaluate an arithmetic expression, e.g. '(1200*12)*0.18'."""
    return _eval(ast.parse(expression.replace("^", "**"), mode="eval"))


@skill(tags={"department:finance"})
def budget_summary(csv_text: str, amount_column: str = "amount", category_column: str = "category") -> dict:
    """Summarize expenses from CSV text: total, per-category totals, largest items."""
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    by_cat: dict[str, float] = {}
    for r in rows:
        amt = float(str(r.get(amount_column, 0)).replace(",", "") or 0)
        by_cat[r.get(category_column, "other") or "other"] = by_cat.get(r.get(category_column, "other") or "other", 0) + amt
    total = sum(by_cat.values())
    return {"total": round(total, 2), "by_category": {k: round(v, 2) for k, v in sorted(by_cat.items(), key=lambda x: -x[1])},
            "rows": len(rows)}


@skill(tags={"department:data"})
def csv_stats(csv_text: str) -> dict:
    """Per-column stats (count, mean, min, max) for numeric columns of CSV text."""
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    out: dict[str, dict] = {}
    for col in (rows[0].keys() if rows else []):
        vals = []
        for r in rows:
            try:
                vals.append(float(r[col]))
            except (TypeError, ValueError):
                pass
        if vals:
            out[col] = {"count": len(vals), "mean": round(statistics.fmean(vals), 4), "min": min(vals), "max": max(vals)}
    return {"rows": len(rows), "numeric_columns": out}


@skill(tags={"department:research", "department:ops", "department:comms", "department:finance", "department:data"})
async def answer(question: str, context: str = "", ctx=None) -> str:
    """General reasoning: answer a question or produce text, optionally using provided context."""
    if ctx is not None and ctx.fleet.llm.is_live:
        return await ctx.llm(f"{context}\n\nQuestion: {question}" if context else question)
    return f"[offline] {question}" + (f" (context: {len(context)} chars)" if context else "")
