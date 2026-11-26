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
        return p or "/"

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


CONSOLE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Agent Multiverse</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#16181d;--muted:#5f6673;--line:#e3e6eb;--accent:#3b5bdb;--ok:#2b8a3e;--bad:#c92a2a}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--ink:#e8eaee;--muted:#9aa1ad;--line:#2a2f39;--accent:#748ffc;--ok:#69db7c;--bad:#ff8787}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px}h1{margin:0 0 4px;font-size:24px}p.sub{color:var(--muted);margin:0 0 20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.k{font-size:26px;font-weight:650}.l{color:var(--muted);font-size:13px}
textarea,input{width:100%;font:inherit;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px}
button{font:inherit;border:0;border-radius:8px;padding:9px 16px;background:var(--accent);color:#fff;cursor:pointer;margin-top:8px}
button.alt{background:transparent;color:var(--accent);border:1px solid var(--line)}
pre{white-space:pre-wrap;word-break:break-word;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:12px;max-height:420px;overflow:auto;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:500}.pill{font-size:12px;padding:1px 7px;border-radius:99px;border:1px solid var(--line);color:var(--muted)}
.se{color:var(--bad);border-color:var(--bad)}section{margin-bottom:22px}.row{display:flex;gap:8px;flex-wrap:wrap}
.scroll{overflow-x:auto}
</style></head><body><main>
<h1>Agent Multiverse</h1><p class="sub" id="mode">Orchestrator → department managers → worker agents</p>
<div class="grid" id="kpis"></div>
<section class="card"><b>Give the multiverse a goal</b>
<p class="l">Separate steps with “;” or “then”. Independent steps run in parallel across departments.</p>
<textarea id="goal" rows="3">Calculate 1200*12*0.18; then summarize the result</textarea>
<input id="token" type="password" placeholder="Access token (optional, enables Claude)" style="margin-top:8px">
<div class="row"><button id="run">Run goal</button><button class="alt" id="demo">Stress test: 3,000 tasks</button></div>
<pre id="out">Results appear here.</pre></section>
<section class="card"><b>Managers</b><div class="scroll"><table id="mgrs"></table></div></section>
<section class="card"><b>Skills</b><div class="scroll"><table id="skills"></table></div></section>
</main><script>
const $=id=>document.getElementById(id);
const hdr=()=>{const t=$('token').value.trim();return Object.assign({'Content-Type':'application/json'},t?{Authorization:'Bearer '+t}:{})};
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function load(){
 const st=await (await fetch('/multiverse/api/status',{headers:hdr()})).json();
 $('mode').textContent='Mode: '+st.mode+' · backend '+st.llm+' · approvals '+st.approval_policy;
 $('kpis').innerHTML=[[st.workers.toLocaleString(),'worker agents'],[st.managers.length,'managers'],[st.skills,'skills'],[1,'orchestrator']]
  .map(([k,l])=>`<div class="card"><div class="k">${k}</div><div class="l">${l}</div></div>`).join('');
 $('mgrs').innerHTML='<tr><th>Manager</th><th>Department</th><th>Workers</th><th>Skills</th></tr>'+st.managers.map(m=>
  `<tr><td>${esc(m.manager)}</td><td>${esc(m.department)}</td><td>${m.workers}</td><td>${m.skills.map(esc).join(', ')}</td></tr>`).join('');
 const sk=await (await fetch('/multiverse/api/skills',{headers:hdr()})).json();
 $('skills').innerHTML='<tr><th>Skill</th><th>Departments</th><th>What it does</th></tr>'+sk.map(s=>
  `<tr><td><code>${esc(s.name)}</code> ${s.side_effect?'<span class="pill se">needs approval</span>':''}</td><td>${s.departments.map(esc).join(', ')}</td><td>${esc(s.description)}</td></tr>`).join('');
}
$('run').onclick=async()=>{$('out').textContent='Running…';
 const r=await fetch('/multiverse/api/run',{method:'POST',headers:hdr(),body:JSON.stringify({goal:$('goal').value})});
 const d=await r.json(); if(d.error){$('out').textContent=d.error;return}
 $('out').textContent=(d.ok?'OK':'INCOMPLETE')+(d.from_playbook?' (learned playbook)':'')+'\\n\\n'+
  d.steps.map(s=>`${s.id} ${s.department}/${s.skill||'agent'} by ${s.worker||'-'}: ${s.ok?JSON.stringify(s.output):'✗ '+s.error}`).join('\\n')+'\\n\\n'+d.summary;};
$('demo').onclick=async()=>{$('out').textContent='Dispatching 3,000 tasks…';
 const r=await fetch('/multiverse/api/demo',{method:'POST',headers:hdr(),body:JSON.stringify({tasks:3000})});
 $('out').textContent=JSON.stringify(await r.json(),null,2);};
$('token').onchange=load; load();
</script></body></html>"""
