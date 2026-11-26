"""Workers and managers."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from .llm import ApprovalRequired
from .models import Task, TaskResult, TaskStatus
from .skills import Skill, SkillContext




@dataclass
class Worker:
    """One agent. Cheap to create (a few hundred bytes) so a multiverse can hold thousands."""

    id: str
    department: str
    skills: list[Skill]
    fleet: Any
    done: int = 0
    failed: int = 0
    _names: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self._names = {s.name for s in self.skills}

    def system_prompt(self) -> str:
        return (f"You are worker {self.id} in the {self.department} department of an agent fleet. "
                "Complete the task using your tools; call several tools in parallel when they are independent. "
                "Never invent facts or tool results. If the task cannot be done with your tools, say exactly what is "
                "missing. Finish with a short, concrete result.")

    async def call_skill(self, task: Task, name: str, args: dict[str, Any]) -> Any:
        if name not in self._names:
            raise PermissionError(f"worker {self.id} is not allowed to use skill '{name}'")
        s = self.fleet.skills.get(name)
        if s.side_effect and self.fleet.approval_policy == "deny":
            raise PermissionError(f"side-effect skill '{name}' is disabled by approval_policy=deny")
        if s.side_effect and not (task.approved or self.fleet.auto_approves(name)):
            raise ApprovalRequired(name, args)
        self.fleet.store.audit(self.id, "skill", {"task": task.id, "skill": name, "args": args})
        return await s.run(SkillContext(self.fleet, task, self.id), **args)

    async def execute(self, task: Task) -> TaskResult:
        t0 = time.perf_counter()
        if task.skill:
            out = await self.call_skill(task, task.skill, task.args)
            steps = [{"tool": task.skill, "args": task.args}]
        else:
            pending: list[ApprovalRequired] = []

            async def run(name: str, args: dict[str, Any]) -> Any:
                try:
                    return await self.call_skill(task, name, args)
                except ApprovalRequired as e:
                    pending.append(e)
                    raise

            goal = task.goal + (f"\n\nInputs:\n{task.args}" if task.args else "")
            try:
                out, steps = await self.fleet.llm.run_agent(self.system_prompt(), goal, self.skills, run)
            except ApprovalRequired:
                pass  # recorded in `pending`
            if pending:  # the agent wanted a side effect: park the task as a concrete, approvable skill call
                task.skill, task.args = pending[0].skill, pending[0].skill_args
                raise pending[0]
        return TaskResult(task.id, True, out, worker=self.id, steps=steps, duration_s=time.perf_counter() - t0)


class Manager:
    """Owns a department: a pool of workers, a concurrency limit, retries and escalation."""

    def __init__(self, name: str, department: str, workers: list[Worker], description: str = "") -> None:
        self.name, self.department, self.description = name, department, description
        self.workers = workers
        self._idle: asyncio.Queue[Worker] | None = None
        self.completed = 0
        self.failed = 0
        self.assigned = 0  # tasks routed here (used for proportional load balancing)

    @property
    def skills(self) -> set[str]:
        return {s.name for w in self.workers[:1] for s in w.skills}

    def _pool(self) -> asyncio.Queue[Worker]:
        if self._idle is None:  # created lazily inside the running event loop
            self._idle = asyncio.Queue()
            for w in self.workers:
                self._idle.put_nowait(w)
        return self._idle

    async def handle(self, task: Task, fleet: Any) -> TaskResult:
        pool = self._pool()
        last_err = ""
        while task.attempts <= task.max_retries:
            task.attempts += 1
            worker = await pool.get()
            task.status = TaskStatus.RUNNING
            fleet.store.save_task(task)
            try:
                res = await worker.execute(task)
                res.manager = self.name
                worker.done += 1
                self.completed += 1
                task.status = TaskStatus.DONE
                fleet.store.save_task(task)
                fleet.store.save_result(res)
                return res
            except ApprovalRequired as e:
                task.status = TaskStatus.WAITING_APPROVAL
                fleet.store.save_task(task)
                fleet.store.audit(self.name, "approval_requested", {"task": task.id, "skill": e.skill, "args": e.skill_args})
                res = TaskResult(task.id, False, error=str(e), worker=worker.id, manager=self.name)
                fleet.store.save_result(res)
                return res
            except Exception as e:  # retry with backoff, then escalate
                worker.failed += 1
                last_err = f"{type(e).__name__}: {e}"
                fleet.store.audit(worker.id, "error", {"task": task.id, "error": last_err, "attempt": task.attempts})
                if task.attempts <= task.max_retries:
                    await asyncio.sleep(min(0.05 * 2 ** task.attempts, 2.0))
            finally:
                pool.put_nowait(worker)
        self.failed += 1
        task.status = TaskStatus.FAILED
        fleet.store.save_task(task)
        res = TaskResult(task.id, False, error=last_err, manager=self.name)
        fleet.store.save_result(res)
        fleet.store.audit(self.name, "escalated", {"task": task.id, "error": last_err})
        return res

    @property
    def idle(self) -> int:
        return self._idle.qsize() if self._idle else len(self.workers)

    def status(self) -> dict[str, Any]:
        busy = len(self.workers) - (self._idle.qsize() if self._idle else len(self.workers))
        return {"manager": self.name, "department": self.department, "workers": len(self.workers), "busy": busy,
                "completed": self.completed, "failed": self.failed, "skills": sorted(self.skills)}
