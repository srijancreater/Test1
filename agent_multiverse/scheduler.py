"""Recurring jobs: `every_minutes = 30`, or `at = "08:30"` with optional `days = ["mon","tue",...]`."""
from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from typing import Any, Callable

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class Job:
    name: str
    goal: str
    every_minutes: int | None = None
    at: str | None = None
    days: list[str] | None = None
    last_run: dt.datetime | None = None

    def due(self, now: dt.datetime) -> bool:
        if self.days and DAYS[now.weekday()] not in [d.lower()[:3] for d in self.days]:
            return False
        if self.every_minutes:
            return self.last_run is None or (now - self.last_run) >= dt.timedelta(minutes=self.every_minutes)
        if self.at:
            hh, mm = map(int, self.at.split(":"))
            slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            return now >= slot and (self.last_run is None or self.last_run < slot)
        return False


def jobs_from_config(cfg: dict[str, Any]) -> list[Job]:
    return [Job(j["name"], j["goal"], j.get("every_minutes"), j.get("at"), j.get("days")) for j in cfg.get("schedule", [])]


async def serve(fleet: Any, jobs: list[Job], tick_s: float = 30.0, on_report: Callable[[Job, Any], None] | None = None,
                stop_after: int | None = None) -> None:
    runs = 0
    while True:
        now = dt.datetime.now()
        due = [j for j in jobs if j.due(now)]
        for j in due:
            j.last_run = now
        if due:
            reports = await asyncio.gather(*(fleet.run(j.goal) for j in due))
            for j, r in zip(due, reports):
                fleet.store.audit("scheduler", "job_ran", {"job": j.name, "ok": r.ok})
                if on_report:
                    on_report(j, r)
            runs += len(due)
        if stop_after is not None and runs >= stop_after:
            return
        await asyncio.sleep(tick_s)
