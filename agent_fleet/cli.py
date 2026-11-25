"""agent-fleet command line.

  run "goal"                 plan + execute a (complex) goal across departments
  do SKILL --args JSON       run one skill directly
  bulk FILE.jsonl            fan out many tasks ({"goal": ..} or {"skill": .., "args": {..}} per line)
  approvals | approve ID | reject ID
  status | history | skills | connectors | playbooks | forget KEY | audit
  serve                      run scheduled jobs from config
  demo --tasks N             stress test: N everyday tasks across the whole fleet (offline)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time

from .fleet import build_fleet, load_config
from .models import Task
from .scheduler import jobs_from_config, serve


def _p(obj) -> None:
    print(json.dumps(obj, indent=2, default=str) if not isinstance(obj, str) else obj)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agent-fleet", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="path to fleet.toml (default config/fleet.toml)")
    ap.add_argument("--llm", choices=["auto", "claude", "offline"])
    ap.add_argument("--scale", type=float, default=1.0, help="multiply worker counts (0.01 for a tiny fleet)")
    ap.add_argument("--approve-all", action="store_true", help="auto-approve side-effect skills for this command")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("goal"); r.add_argument("--no-memory", action="store_true"); r.add_argument("--json", action="store_true")
    d = sub.add_parser("do"); d.add_argument("skill"); d.add_argument("--args", default="{}")
    b = sub.add_parser("bulk"); b.add_argument("file")
    for name in ("approvals", "status", "history", "skills", "connectors", "playbooks", "audit"):
        sub.add_parser(name)
    for name in ("approve", "reject", "forget"):
        sub.add_parser(name).add_argument("id")
    s = sub.add_parser("serve"); s.add_argument("--tick", type=float, default=30.0)
    dm = sub.add_parser("demo"); dm.add_argument("--tasks", type=int, default=1000)
    a = ap.parse_args(argv)

    cfg = load_config(a.config)
    llm = "offline" if a.cmd == "demo" else a.llm
    fleet = build_fleet(cfg, llm=llm, scale=a.scale, approval_policy="auto" if a.approve_all else None)

    if a.cmd == "run":
        rep = asyncio.run(fleet.run(a.goal, use_memory=not a.no_memory))
        if a.json:
            _p(rep.to_dict())
        else:
            src = "learned playbook" if rep.from_playbook else "fresh plan"
            print(f"[{'OK' if rep.ok else 'INCOMPLETE'}] {len(rep.steps)} step(s) via {src}\n")
            for st in rep.steps:
                print(f"  {st['id']} {st['department']}/{st['skill'] or 'agent'} by {st['worker'] or '-'}: "
                      f"{'ok' if st['ok'] else st['error']}")
            print("\n" + rep.summary)
            for tid in rep.waiting_approval:
                print(f"\n  waiting for approval: {tid}   ->  python -m agent_fleet approve {tid}")
        return 0 if rep.ok or rep.waiting_approval else 1
    if a.cmd == "do":
        res = asyncio.run(fleet.submit(Task(goal=f"run {a.skill}", skill=a.skill, args=json.loads(a.args))))
        _p(res.to_dict())
        return 0 if res.ok else 1
    if a.cmd == "bulk":
        with open(a.file, encoding="utf-8") as f:
            specs = [json.loads(l) for l in f if l.strip()]
        tasks = [Task(goal=x.get("goal", f"run {x.get('skill')}"), skill=x.get("skill"), args=x.get("args", {}),
                      department=x.get("department")) for x in specs]
        t0 = time.perf_counter()
        res = asyncio.run(fleet.submit_many(tasks))
        _p({"tasks": len(res), "ok": sum(r.ok for r in res), "failed": sum(not r.ok for r in res),
            "seconds": round(time.perf_counter() - t0, 2)})
        return 0
    if a.cmd == "approvals":
        _p([{k: r[k] for k in ("id", "skill", "args", "goal")} for r in fleet.pending_approvals()]); return 0
    if a.cmd == "approve":
        _p(asyncio.run(fleet.approve(a.id)).to_dict()); return 0
    if a.cmd == "reject":
        fleet.reject(a.id); print(f"rejected {a.id}"); return 0
    if a.cmd == "status":
        st = fleet.status()
        st["managers"] = [{k: m[k] for k in ("manager", "department", "workers", "completed", "failed")} for m in st["managers"]]
        _p(st); return 0
    if a.cmd == "history":
        _p([{k: r[k] for k in ("id", "status", "skill", "worker", "goal")} for r in fleet.store.tasks(limit=30)]); return 0
    if a.cmd == "skills":
        for sk in fleet.skills:
            flag = " [side-effect]" if sk.side_effect else ""
            print(f"{sk.name:28s} {','.join(sorted(sk.departments)):38s} {sk.description.splitlines()[0][:70]}{flag}")
        return 0
    if a.cmd == "connectors":
        _p([c.status() for c in fleet.connectors]); return 0
    if a.cmd == "playbooks":
        _p(fleet.store.playbooks()); return 0
    if a.cmd == "forget":
        fleet.store.forget(a.id); print("forgotten"); return 0
    if a.cmd == "audit":
        _p(fleet.store.audit_log()); return 0
    if a.cmd == "serve":
        jobs = jobs_from_config(cfg)
        print(f"serving {len(jobs)} job(s) with {fleet.worker_count} workers; Ctrl+C to stop")
        try:
            asyncio.run(serve(fleet, jobs, a.tick, on_report=lambda j, r: print(f"[{j.name}] {'ok' if r.ok else 'incomplete'}: {r.summary[:300]}")))
        except KeyboardInterrupt:
            pass
        return 0
    if a.cmd == "demo":
        return _demo(fleet, a.tasks)
    return 2


def _demo(fleet, n: int) -> int:
    rnd = random.Random(7)
    makers = [
        lambda i: Task(goal="calc", skill="calculate", args={"expression": f"{rnd.randint(1, 999)}*{rnd.randint(1, 99)}+{i}"}),
        lambda i: Task(goal="keywords", skill="extract_keywords", args={"text": "invoice payment overdue reminder client invoice"}),
        lambda i: Task(goal="todos", skill="extract_action_items", args={"text": f"- call plumber\nTODO: renew passport {i}\n- buy milk"}),
        lambda i: Task(goal="note", skill="notes.put", args={"key": f"demo-{i % 50}", "value": f"run {i}"}),
        lambda i: Task(goal="split", skill="split_bill", args={"total": 100 + i, "people": 3, "tip_percent": 10})
        if "split_bill" in fleet.skills else Task(goal="calc", skill="calculate", args={"expression": "1+1"}),
        lambda i: Task(goal=f"Summarize: The team shipped release {i}. Customers liked the faster search. Next: billing fixes."),
    ]
    tasks = [makers[i % len(makers)](i) for i in range(n)]
    print(f"fleet: {fleet.worker_count} workers in {len(fleet.managers)} departments, {len(fleet.skills)} skills")
    t0 = time.perf_counter()
    res = asyncio.run(fleet.submit_many(tasks))
    dt_s = time.perf_counter() - t0
    used = {r.worker for r in res if r.worker}
    print(f"{n} tasks: {sum(r.ok for r in res)} ok, {sum(not r.ok for r in res)} failed in {dt_s:.2f}s "
          f"({n / dt_s:.0f} tasks/s), {len(used)} distinct workers used")
    for m in fleet.managers.values():
        print(f"  {m.name:28s} workers={len(m.workers):4d} completed={m.completed}")
    return 0 if all(r.ok for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
