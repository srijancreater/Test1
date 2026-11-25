"""SQLite persistence: tasks, results, learned playbooks and an audit log."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, parent_id TEXT, goal TEXT, skill TEXT, args TEXT,
  department TEXT, status TEXT, approved INTEGER, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS results (task_id TEXT PRIMARY KEY, ok INTEGER, output TEXT, error TEXT, worker TEXT,
  manager TEXT, steps TEXT, duration_s REAL);
CREATE TABLE IF NOT EXISTS playbooks (key TEXT PRIMARY KEY, goal TEXT, steps TEXT, uses INTEGER DEFAULT 0,
  successes INTEGER DEFAULT 0, failures INTEGER DEFAULT 0, updated_at REAL);
CREATE TABLE IF NOT EXISTS audit (ts REAL, actor TEXT, event TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)

    def save_task(self, t: Any) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)",
            (t.id, t.parent_id, t.goal, t.skill, json.dumps(t.args, default=str), t.department, t.status.value,
             int(t.approved), t.created_at, time.time()))
        self.db.commit()

    def save_result(self, r: Any) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?)",
            (r.task_id, int(r.ok), json.dumps(r.output, default=str), r.error, r.worker, r.manager,
             json.dumps(r.steps, default=str), r.duration_s))
        self.db.commit()

    def task(self, task_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def tasks(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        q = "SELECT t.*, r.output, r.error, r.worker FROM tasks t LEFT JOIN results r ON r.task_id=t.id"
        args: tuple = ()
        if status:
            q += " WHERE t.status=?"
            args = (status,)
        q += " ORDER BY t.updated_at DESC LIMIT ?"
        return [dict(r) for r in self.db.execute(q, args + (limit,))]

    def counts(self) -> dict[str, int]:
        return {r[0]: r[1] for r in self.db.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status")}

    # -- learning
    def playbook(self, key: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM playbooks WHERE key=?", (key,)).fetchone()
        return dict(row) | {"steps": json.loads(row["steps"])} if row else None

    def learn(self, key: str, goal: str, steps: list[dict[str, Any]], ok: bool) -> None:
        cur = self.playbook(key)
        if cur is None:
            self.db.execute("INSERT INTO playbooks VALUES (?,?,?,?,?,?,?)",
                            (key, goal, json.dumps(steps, default=str), 1, int(ok), int(not ok), time.time()))
        else:
            # keep the steps of the last successful run; count outcomes
            new_steps = json.dumps(steps, default=str) if ok else json.dumps(cur["steps"], default=str)
            self.db.execute("UPDATE playbooks SET steps=?, uses=uses+1, successes=successes+?, failures=failures+?, "
                            "updated_at=? WHERE key=?", (new_steps, int(ok), int(not ok), time.time(), key))
        self.db.commit()

    def playbooks(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT key, goal, uses, successes, failures FROM playbooks "
                                                 "ORDER BY uses DESC")]

    def forget(self, key: str) -> None:
        self.db.execute("DELETE FROM playbooks WHERE key=?", (key,))
        self.db.commit()

    def audit(self, actor: str, event: str, detail: Any = "") -> None:
        self.db.execute("INSERT INTO audit VALUES (?,?,?,?)", (time.time(), actor, event, json.dumps(detail, default=str)))
        self.db.commit()

    def audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT * FROM audit ORDER BY ts DESC LIMIT ?", (limit,))]
