"""Vercel Python function: Agent Multiverse console + JSON API.

GET  /multiverse            web console   (/fleet/... still works as an alias)
GET  /multiverse/api/status      departments, managers, worker counts
GET  /multiverse/api/skills      skill catalog
POST /multiverse/api/run         {"goal": "..."}                 plan + execute a goal
POST /multiverse/api/task        {"skill": "...", "args": {...}} run one skill
POST /multiverse/api/demo        {"tasks": 2000}                 stress test across the whole multiverse

Public-safety rules (this URL is reachable by anyone):
* Without a valid `Authorization: Bearer $MULTIVERSE_ACCESS_TOKEN`, requests run on the OFFLINE backend
  (no Claude spend), outbound HTTP skills are removed, and side-effect skills are denied.
* With the token (and ANTHROPIC_API_KEY set in Vercel), requests use Claude; side effects are still
  only parked for approval - the serverless filesystem is ephemeral, so approve from the CLI instead.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import random
import sys
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_multiverse.multiverse import build_multiverse, load_config  # noqa: E402
from agent_multiverse.models import Task  # noqa: E402

MAX_BODY = 256 * 1024
MAX_DEMO = 5000
WORKSPACE = Path(os.environ.get("MULTIVERSE_WORKSPACE", "/tmp/agent-multiverse"))
PUBLIC_EXCLUDE = ["http.get", "http.post_json"]


def authorized(headers) -> bool:
    token = os.environ.get("MULTIVERSE_ACCESS_TOKEN", "")
    got = (headers.get("Authorization") or "").removeprefix("Bearer ").strip()
    return bool(token) and hmac.compare_digest(token, got)


def make_fleet(trusted: bool):
    cfg = load_config(ROOT / "config" / "multiverse.toml")
    cfg.setdefault("multiverse", {})["store"] = ":memory:"
    return build_multiverse(cfg, llm=("auto" if trusted else "offline"), workspace=WORKSPACE,
                       approval_policy="ask" if trusted else "deny",
                       exclude_skills=None if trusted else PUBLIC_EXCLUDE)


def demo(fleet, n: int) -> dict:
    rnd = random.Random(7)
    kinds = [
        lambda i: Task(goal="c", skill="calculate", args={"expression": f"{rnd.randint(1, 999)}*{rnd.randint(1, 99)}"}),
        lambda i: Task(goal="k", skill="extract_keywords", args={"text": "invoice payment overdue reminder client"}),
        lambda i: Task(goal="t", skill="extract_action_items", args={"text": f"TODO: renew passport {i}\n- buy milk"}),
        lambda i: Task(goal="n", skill="notes.put", args={"key": f"demo-{i % 20}", "value": str(i)}),
        lambda i: Task(goal="Summarize: Release shipped. Customers liked faster search. Next: billing fixes."),
    ]
    t0 = time.perf_counter()
    res = asyncio.run(fleet.submit_many([kinds[i % len(kinds)](i) for i in range(n)]))
    dt = time.perf_counter() - t0
    return {"tasks": n, "ok": sum(r.ok for r in res), "failed": sum(not r.ok for r in res),
            "seconds": round(dt, 3), "tasks_per_second": round(n / dt) if dt else None,
            "distinct_workers": len({r.worker for r in res if r.worker}),
            "by_manager": {m.name: m.completed for m in fleet.managers.values()}}


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body, ctype: str = "application/json") -> None:
        data = (json.dumps(body, default=str, indent=2) if not isinstance(body, str) else body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if "charset" not in ctype else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _route(self) -> str:
        p = urlparse(self.path).path.rstrip("/")
        for prefix in ("/api/multiverse", "/multiverse", "/fleet"):
            if p == prefix or p.startswith(prefix + "/"):
                p = p[len(prefix):]
                break
        return p or "/"  # "/" on the agent-multiverse-app domain is rewritten here too

    def do_GET(self) -> None:  # noqa: N802
        r = self._route()
        trusted = authorized(self.headers)
        if r == "/":
            return self._send(200, CONSOLE, "text/html")
        fleet = make_fleet(trusted)
        if r == "/api/status":
            st = fleet.status()
            st["mode"] = "trusted" if trusted else "public (offline, no side effects)"
            return self._send(200, st)
        if r == "/api/skills":
            return self._send(200, [{"name": s.name, "departments": sorted(s.departments), "side_effect": s.side_effect,
                                     "description": s.description, "input_schema": s.input_schema} for s in fleet.skills])
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        r = self._route()
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._send(413, {"error": "body too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, {"error": "invalid JSON"})
        trusted = authorized(self.headers)
        fleet = make_fleet(trusted)
        try:
            if r == "/api/run":
                goal = str(body.get("goal", "")).strip()[:4000]
                if not goal:
                    return self._send(400, {"error": "goal is required"})
                rep = asyncio.run(fleet.run(goal))
                out = rep.to_dict()
                out["mode"] = "trusted" if trusted else "public"
                return self._send(200, out)
            if r == "/api/task":
                name = body.get("skill")
                if name not in fleet.skills:
                    return self._send(400, {"error": f"unknown or unavailable skill: {name}"})
                args = body.get("args") or {}
                if not isinstance(args, dict):
                    return self._send(400, {"error": "args must be an object"})
                res = asyncio.run(fleet.submit(Task(goal=f"run {name}", skill=name, args=args, max_retries=0)))
                return self._send(200 if res.ok else 422, res.to_dict())
            if r == "/api/demo":
                n = max(1, min(int(body.get("tasks", 1000)), MAX_DEMO))
                return self._send(200, demo(make_fleet(False), n))
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})
        self._send(404, {"error": "not found"})


CONSOLE = (ROOT / "agent_multiverse" / "web" / "console.html").read_text(encoding="utf-8")
