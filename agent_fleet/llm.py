"""LLM backends.

ClaudeBackend  - uses the Anthropic SDK (Messages API, manual tool loop) when credentials exist.
OfflineBackend - deterministic, no network: keyword planning + direct skill calls. Lets the whole
                 fleet run (and be tested) without an API key; swap in Claude by setting ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Awaitable, Callable, Protocol

from .skills import Skill


class ApprovalRequired(Exception):
    def __init__(self, skill: str, args: dict[str, Any]) -> None:
        super().__init__(f"approval required for side-effect skill '{skill}'")
        self.skill, self.skill_args = skill, args

ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[Any]]

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "goal": {"type": "string"},
                    "department": {"type": "string"},
                    "skill": {"type": "string"},
                    "args_json": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "goal", "department", "skill", "args_json", "depends_on"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["steps"],
    "additionalProperties": False,
}


class LLMBackend(Protocol):
    is_live: bool

    async def complete(self, prompt: str, system: str = "") -> str: ...

    async def plan(self, goal: str, departments: dict[str, list[Skill]]) -> list[dict[str, Any]]: ...

    async def run_agent(self, system: str, goal: str, skills: list[Skill], execute: ToolExecutor,
                        max_turns: int = 12) -> tuple[str, list[dict[str, Any]]]: ...


def tool_name(skill_name: str) -> str:
    """API tool names allow [a-zA-Z0-9_-]; connector skills use dots (files.read -> files__read)."""
    return skill_name.replace(".", "__")


# ---------------------------------------------------------------- offline

_KEYWORDS: list[tuple[str, str, str]] = [
    # (regex, department, skill)
    (r"\b(send|reply)\b.*\b(e-?mail|mail)\b|\b(e-?mail|mail)\b.*\b(send|reply)\b", "comms", "email.send"),
    (r"\b(draft|write)\b.*\b(e-?mail|letter|message)\b", "comms", "draft_email"),
    (r"\b(notify|announce|post to|slack|teams)\b", "comms", "webhook.notify"),
    (r"\b(summar|tl;?dr|digest)", "research", "summarize"),
    (r"\b(keyword|topics?)\b", "research", "extract_keywords"),
    (r"\b(fetch|download|scrape|visit|https?://)", "research", "http.get"),
    (r"\b(todo|action items?|follow[- ]ups?|tasks from)\b", "ops", "extract_action_items"),
    (r"\b(meeting|calendar|schedule|remind|appointment)\b", "ops", "calendar.add_event"),
    (r"\b(budget|expenses?|spend|invoice)\b", "finance", "budget_summary"),
    (r"\b(calculate|compute|how much|percent|\d+\s*[-+*/^]\s*\d+)", "finance", "calculate"),
    (r"\b(csv|stats|statistics|average|mean)\b", "data", "csv_stats"),
    (r"\b(save|store|remember|note)\b", "ops", "notes.put"),
]


class OfflineBackend:
    is_live = False

    async def complete(self, prompt: str, system: str = "") -> str:
        return f"[offline] {prompt[:200]}"

    async def plan(self, goal: str, departments: dict[str, list[Skill]]) -> list[dict[str, Any]]:
        available = {s.name for skills in departments.values() for s in skills}
        parts = [p.strip() for p in re.split(r"\s*(?:;|\bthen\b|\band then\b|\n)\s*", goal) if p.strip()]
        steps: list[dict[str, Any]] = []
        for i, part in enumerate(parts or [goal]):
            dept, sk = "research", "answer"
            for pat, d, s in _KEYWORDS:
                if re.search(pat, part, re.I) and s in available:
                    dept, sk = d, s
                    break
            steps.append({"id": f"s{i + 1}", "goal": part, "department": dept, "skill": sk, "args": {},
                          "depends_on": [f"s{i}"] if i else []})
        return steps

    async def run_agent(self, system, goal, skills, execute, max_turns=12):
        # Without a model we cannot choose arguments; call the single best-matching skill with the goal as input.
        names = {s.name: s for s in skills}
        chosen = next((s for pat, _, s in _KEYWORDS if re.search(pat, goal, re.I) and s in names), None)
        chosen = chosen or ("answer" if "answer" in names else next(iter(names), None))
        if chosen is None:
            return "no skills available", []
        task_text, _, upstream = goal.partition("\n\nUpstream results: ")
        source = upstream
        m = re.search(r"\bfiles/([\w./-]+\w)", task_text)
        if m and "files.read" in names and chosen != "files.read":
            try:
                source = await execute("files.read", {"path": m.group(1)})
            except Exception:
                pass
        if upstream and source == upstream:
            try:  # unwrap {"s1": "..."} into plain text
                vals = list(json.loads(upstream).values())
                source = "\n".join(v if isinstance(v, str) else json.dumps(v) for v in vals)
            except ValueError:
                pass
        args = guess_args(names[chosen], task_text, source)
        out = await execute(chosen, args)
        return out, [{"tool": chosen, "args": args}]


def guess_args(s: Skill, goal: str, source: str = "") -> dict[str, Any]:
    """Best-effort argument filling for offline mode. `source` = file content or upstream output."""
    props = s.input_schema.get("properties", {})
    req = s.input_schema.get("required", list(props))
    args: dict[str, Any] = {}
    url = re.search(r"https?://\S+", goal)
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", goal)
    for k in req:
        t = props.get(k, {}).get("type", "string")
        if k == "url" and url:
            args[k] = url.group(0)
        elif k == "to" and email:
            args[k] = email.group(0)
        elif k == "key":
            args[k] = re.sub(r"[^a-z0-9]+", "-", goal.lower()).strip("-")[:48] or "note"
        elif k in ("text", "value", "content", "csv_text", "message", "body") and source:
            args[k] = source
        elif k == "purpose":
            args[k] = goal + (f": {source}" if source else "")
        elif k == "subject":
            args[k] = goal[:70]
        elif k == "expression":
            m = re.search(r"[\d().\s+\-*/^%]{3,}", goal)
            args[k] = (m.group(0).strip() if m else "0")
        elif k == "start":
            import datetime as dt
            args[k] = (dt.datetime.now().replace(minute=0, second=0, microsecond=0) + dt.timedelta(days=1, hours=1)).isoformat()
        elif t == "string":
            args[k] = goal
        elif t == "integer":
            args[k] = 1
    return args


# ---------------------------------------------------------------- Claude

class ClaudeBackend:
    """Anthropic Messages API backend. One shared async client; a semaphore caps concurrent requests so
    thousands of agents can share a rate limit."""

    is_live = True

    def __init__(self, model: str = "claude-opus-5-5", planner_model: str | None = None, effort: str = "medium",
                 max_concurrency: int = 16) -> None:
        import anthropic  # optional dependency

        self._anthropic = anthropic
        self.client = anthropic.AsyncAnthropic(max_retries=4)
        self.model = model
        self.planner_model = planner_model or model
        self.effort = effort
        self.sem = asyncio.Semaphore(max_concurrency)

    async def _create(self, *, model: str, effort: str | None = None, **kw: Any):
        async with self.sem:
            resp = await self.client.beta.messages.create(
                model=model,
                max_tokens=kw.pop("max_tokens", 16000),
                output_config={"effort": effort or self.effort, **kw.pop("output_config", {})},
                # Server-side fallback: if a request is declined by a safety classifier, the API re-runs it
                # on a fallback model chosen by refusal category, inside the same call.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                **kw,
            )
        if resp.stop_reason == "refusal":
            cat = getattr(resp.stop_details, "category", None) if resp.stop_details else None
            raise RuntimeError(f"model declined the request (category={cat})")
        return resp

    @staticmethod
    def _text(resp: Any) -> str:
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    async def complete(self, prompt: str, system: str = "") -> str:
        kw: dict[str, Any] = {"messages": [{"role": "user", "content": prompt}]}
        if system:
            kw["system"] = system
        return self._text(await self._create(model=self.model, **kw))

    async def plan(self, goal: str, departments: dict[str, list[Skill]]) -> list[dict[str, Any]]:
        catalog = "\n".join(
            f"## department: {d}\n" + "\n".join(f"- {s.name}: {s.description} | args: {json.dumps(s.input_schema.get('properties', {}))}"
                                               for s in skills)
            for d, skills in departments.items())
        system = (
            "You are the planner of a multi-agent fleet. Break the user's goal into the smallest set of steps that "
            "fully achieves it. Each step is done by one worker in one department using one skill from the catalog "
            "(use 'answer' for pure reasoning or writing). Put concrete argument values in args_json (a JSON object "
            "string; use \"{{s1}}\" to insert the output of step s1). Steps that do not depend on each other must have "
            "no depends_on so they run in parallel. Do not invent skills.\n\n# Skill catalog\n" + catalog)
        resp = await self._create(
            model=self.planner_model, effort="high", system=system,
            messages=[{"role": "user", "content": goal}],
            output_config={"format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
        )
        data = json.loads(self._text(resp))
        steps = []
        for st in data["steps"]:
            try:
                args = json.loads(st.pop("args_json") or "{}")
            except json.JSONDecodeError:
                args = {}
            steps.append({**st, "args": args if isinstance(args, dict) else {}})
        return steps

    async def run_agent(self, system, goal, skills, execute, max_turns=12):
        by_tool = {tool_name(s.name): s for s in skills}
        tools = [{**s.as_tool(), "name": tool_name(s.name)} for s in skills]
        messages: list[dict[str, Any]] = [{"role": "user", "content": goal}]
        steps: list[dict[str, Any]] = []
        for _ in range(max_turns):
            resp = await self._create(model=self.model, system=system, tools=tools, messages=messages)
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason == "pause_turn":
                continue
            calls = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason != "tool_use" or not calls:
                return self._text(resp), steps

            async def one(call):
                s = by_tool.get(call.name)
                try:
                    if s is None:
                        raise KeyError(f"unknown tool {call.name}")
                    out = await execute(s.name, dict(call.input))
                    steps.append({"tool": s.name, "args": call.input})
                    return {"type": "tool_result", "tool_use_id": call.id,
                            "content": out if isinstance(out, str) else json.dumps(out, default=str)}
                except ApprovalRequired as e:
                    return {"type": "tool_result", "tool_use_id": call.id, "is_error": True,
                            "content": f"{e}. The call has been queued for a human to approve; do not retry it."}
                except Exception as e:  # report tool errors back to the model
                    return {"type": "tool_result", "tool_use_id": call.id, "content": f"error: {e}", "is_error": True}

            # parallel tool calls -> all results in ONE user message
            messages.append({"role": "user", "content": list(await asyncio.gather(*(one(c) for c in calls)))})
        return "stopped: turn limit reached", steps


def make_backend(kind: str = "auto", **kw: Any) -> LLMBackend:
    if kind == "offline":
        return OfflineBackend()
    has_creds = any(os.environ.get(v) for v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"))
    if kind == "claude" or (kind == "auto" and has_creds):
        try:
            return ClaudeBackend(**kw)
        except ImportError:
            if kind == "claude":
                raise
    return OfflineBackend()
