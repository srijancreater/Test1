"""The Orchestrator ("Multiverse"): intake -> plan (or recall a learned playbook) -> route to managers ->
run the DAG with maximum parallelism -> approvals -> aggregate -> learn."""
from __future__ import annotations

import asyncio
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import builtin_skills
from .agents import Manager, Worker
from .connectors import BUILTIN_CONNECTORS, ConnectorRegistry
from .llm import LLMBackend, make_backend
from .models import Task, TaskResult, TaskStatus, new_id
from .skills import SkillRegistry
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "multiverse.toml"


@dataclass
class RunReport:
    goal: str
    ok: bool
    summary: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    waiting_approval: list[str] = field(default_factory=list)
    learned: bool = False
    from_playbook: bool = False

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def playbook_key(goal: str) -> str:
    """Normalize a goal so repeated tasks ("daily digest for 2026-11-25") map to the same playbook."""
    g = goal.lower()
    g = re.sub(r"https?://\S+|[\w.+-]+@[\w-]+\.[\w.]+", "<x>", g)
    g = re.sub(r"\d+", "#", g)
    return re.sub(r"\s+", " ", re.sub(r"[^\w#<> ]", " ", g)).strip()


class Multiverse:
    def __init__(self, llm: LLMBackend, workspace: Path, store: Store, approval_policy: str = "ask",
                 auto_approve: list[str] | None = None) -> None:
        self.llm = llm
        self.workspace = workspace
        self.store = store
        self.skills = SkillRegistry()
        self.connectors = ConnectorRegistry()
        self.managers: dict[str, Manager] = {}
        self.approval_policy = approval_policy  # ask | auto | deny
        self.auto_approve = set(auto_approve or [])

    # ---------------------------------------------------------------- setup
    def auto_approves(self, skill_name: str) -> bool:
        return self.approval_policy == "auto" or skill_name in self.auto_approve

    def add_department(self, name: str, workers: int, description: str = "", extra_skills: list[str] | None = None,
                       manager_name: str | None = None) -> Manager:
        skills = self.skills.for_department(name)
        for n in extra_skills or []:
            if n == "*":
                skills = list(self.skills)
                break
            if n in self.skills and all(s.name != n for s in skills):
                skills.append(self.skills.get(n))
        pool = [Worker(f"{name}-{i:04d}", name, skills, self) for i in range(workers)]
        m = Manager(manager_name or f"{name}-manager", name, pool, description)
        self.managers[name] = m
        return m

    @property
    def worker_count(self) -> int:
        return sum(len(m.workers) for m in self.managers.values())

    def manager_for(self, task: Task) -> Manager:
        m = self._route(task)
        m.assigned += 1
        return m

    def _route(self, task: Task) -> Manager:
        if task.department in self.managers:
            m = self.managers[task.department]
            if not task.skill or task.skill in m.skills:
                return m
        if task.skill:  # load-balance across every department that has the skill
            owners = [m for m in self.managers.values() if task.skill in m.skills]
            if owners:
                return min(owners, key=lambda m: m.assigned / len(m.workers))  # proportional to pool size
        return self.managers.get("research") or next(iter(self.managers.values()))

    # ---------------------------------------------------------------- execution
    async def submit(self, task: Task) -> TaskResult:
        """Run one task (direct skill call or agentic) through the right manager."""
        self.store.save_task(task)
        return await self.manager_for(task).handle(task, self)

    async def submit_many(self, tasks: list[Task]) -> list[TaskResult]:
        """Fan out many independent tasks (e.g. 10,000 daily chores); managers throttle by pool size."""
        return list(await asyncio.gather(*(self.submit(t) for t in tasks)))

    async def run(self, goal: str, use_memory: bool = True) -> RunReport:
        """Complex goal -> plan -> parallel DAG execution -> aggregated answer."""
        key = playbook_key(goal)
        pb = self.store.playbook(key) if use_memory else None
        from_pb = bool(pb and pb["successes"] > 0 and pb["successes"] >= pb["failures"])
        if from_pb:
            steps = pb["steps"]
        else:
            catalog = {d: [s for s in self.skills if s.name in m.skills] for d, m in self.managers.items()}
            steps = await self.llm.plan(goal, catalog)
        self.store.audit("orchestrator", "plan", {"goal": goal, "from_playbook": from_pb, "steps": steps})

        parent = new_id("run")
        results: dict[str, TaskResult] = {}
        tasks: dict[str, Task] = {}
        done_events = {s["id"]: asyncio.Event() for s in steps}

        async def run_step(st: dict[str, Any]) -> None:
            for dep in st.get("depends_on", []):
                if dep in done_events:
                    await done_events[dep].wait()
            outputs = {d: results[d].output for d in st.get("depends_on", []) if d in results}
            failed_dep = [d for d in st.get("depends_on", []) if d in results and not results[d].ok]
            args = _fill(st.get("args", {}), {k: r.output for k, r in results.items()})
            skill = st.get("skill") or None
            if skill and skill not in self.skills:
                skill = None
            if skill and not args:  # planner gave no args: let the worker reason with the skill + upstream output
                skill = None
            goal_text = st["goal"] + (f"\n\nUpstream results: {json.dumps(outputs, default=str)[:8000]}" if outputs else "")
            t = Task(goal=goal_text, skill=skill, args=args, department=st.get("department"), parent_id=parent)
            tasks[st["id"]] = t
            if failed_dep:
                t.status = TaskStatus.FAILED
                self.store.save_task(t)
                results[st["id"]] = TaskResult(t.id, False, error=f"dependency failed: {failed_dep}")
            else:
                results[st["id"]] = await self.submit(t)
            done_events[st["id"]].set()

        await asyncio.gather(*(run_step(s) for s in steps))

        waiting = [tasks[s["id"]].id for s in steps if tasks[s["id"]].status == TaskStatus.WAITING_APPROVAL]
        ok = all(r.ok for r in results.values())
        step_view = [{"id": s["id"], "goal": s["goal"], "department": s.get("department"), "skill": s.get("skill"),
                      "task_id": tasks[s["id"]].id, "ok": results[s["id"]].ok, "worker": results[s["id"]].worker,
                      "output": results[s["id"]].output, "error": results[s["id"]].error} for s in steps]
        summary = await self._summarize(goal, step_view)
        learned = False
        if not waiting:
            self.store.learn(key, goal, steps, ok)
            learned = True
        return RunReport(goal, ok, summary, step_view, waiting, learned, from_pb)

    async def _summarize(self, goal: str, steps: list[dict[str, Any]]) -> str:
        if len(steps) == 1:
            s = steps[0]
            out = s["output"]
            if not s["ok"]:
                return f"failed: {s['error']}"
            if isinstance(out, dict) and "summary" in out:  # lookup result
                src = f"\n\nSource: {out['source']}" if out.get("source") else ""
                return f"{out.get('title', '')}: {out['summary']}{src}".lstrip(": ")
            return out if isinstance(out, str) else json.dumps(out, default=str)
        if self.llm.is_live:
            return await self.llm.complete(
                f"Goal: {goal}\n\nStep results:\n{json.dumps(steps, default=str)[:30000]}\n\n"
                "Write the final answer for the user: what was done, the results, and anything still pending.")
        return "\n".join(f"[{'ok' if s['ok'] else 'FAIL'}] {s['goal']}: {s['output'] if s['ok'] else s['error']}"
                         for s in steps)

    # ---------------------------------------------------------------- approvals
    def pending_approvals(self) -> list[dict[str, Any]]:
        return self.store.tasks(status=TaskStatus.WAITING_APPROVAL.value, limit=500)

    async def approve(self, task_id: str) -> TaskResult:
        row = self.store.task(task_id)
        if not row or row["status"] != TaskStatus.WAITING_APPROVAL.value:
            raise KeyError(f"no task waiting for approval: {task_id}")
        t = Task(goal=row["goal"], skill=row["skill"], args=json.loads(row["args"]), department=row["department"],
                 parent_id=row["parent_id"], id=row["id"], approved=True, created_at=row["created_at"])
        self.store.audit("human", "approved", {"task": task_id})
        return await self.submit(t)

    def reject(self, task_id: str) -> None:
        row = self.store.task(task_id)
        if not row:
            raise KeyError(task_id)
        self.store.db.execute("UPDATE tasks SET status=? WHERE id=?", (TaskStatus.REJECTED.value, task_id))
        self.store.db.commit()
        self.store.audit("human", "rejected", {"task": task_id})

    def status(self) -> dict[str, Any]:
        return {"llm": type(self.llm).__name__, "workers": self.worker_count, "skills": len(self.skills),
                "approval_policy": self.approval_policy, "tasks": self.store.counts(),
                "managers": [m.status() for m in self.managers.values()]}


def _fill(value: Any, outputs: dict[str, Any]) -> Any:
    """Replace "{{s1}}" placeholders with upstream outputs."""
    if isinstance(value, str):
        m = re.fullmatch(r"\{\{(\w+)\}\}", value.strip())
        if m and m.group(1) in outputs:
            return outputs[m.group(1)]
        return re.sub(r"\{\{(\w+)\}\}", lambda mm: str(outputs.get(mm.group(1), mm.group(0))), value)
    if isinstance(value, dict):
        return {k: _fill(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, outputs) for v in value]
    return value


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_CONFIG
    return tomllib.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def build_multiverse(config: str | Path | dict[str, Any] | None = None, *, llm: str | LLMBackend | None = None,
                workspace: str | Path | None = None, scale: float = 1.0, approval_policy: str | None = None,
                exclude_skills: list[str] | None = None) -> Multiverse:
    cfg = config if isinstance(config, dict) else load_config(config)
    fc = cfg.get("multiverse") or cfg.get("fleet", {})  # [fleet] accepted for old configs
    ws = Path(workspace or fc.get("workspace", ROOT / ".multiverse")).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    if isinstance(llm, str) or llm is None:
        kind = llm or fc.get("llm", "auto")
        backend = make_backend(kind, **({k: fc[k] for k in ("model", "planner_model", "effort", "max_concurrency") if k in fc}
                                        if kind != "offline" else {}))
    else:
        backend = llm
    fleet = Multiverse(backend, ws, Store(":memory:" if fc.get("store") == ":memory:" else ws / "multiverse.db"),
                  approval_policy=approval_policy or fc.get("approval_policy", "ask"),
                  auto_approve=fc.get("auto_approve", []))
    fleet.skills.load_module_skills(builtin_skills)
    for cls in BUILTIN_CONNECTORS:
        c = fleet.connectors.register(cls(ws))
        for s in c.actions():
            fleet.skills.register(s)
    for d in fc.get("skill_dirs", ["skills_contrib"]):
        fleet.skills.load_directory(d if Path(d).is_absolute() else ROOT / d)
    for name in exclude_skills or []:
        fleet.skills.unregister(name)
    depts = cfg.get("department") or [
        {"name": "research", "workers": 20}, {"name": "comms", "workers": 20}, {"name": "ops", "workers": 20},
        {"name": "finance", "workers": 10}, {"name": "data", "workers": 10}]
    for d in depts:
        fleet.add_department(d["name"], max(1, int(d.get("workers", 10) * scale)), d.get("description", ""),
                             d.get("skills"), d.get("manager"))
    return fleet
