from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    WAITING_APPROVAL = "waiting_approval"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    REJECTED = "rejected"


def new_id(prefix: str = "t") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@dataclass
class Task:
    """A unit of work. `skill` set => direct call; otherwise the worker reasons with its skills."""

    goal: str
    skill: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    department: str | None = None
    depends_on: list[str] = field(default_factory=list)
    priority: int = 5  # 1 = highest
    max_retries: int = 2
    parent_id: str | None = None
    approved: bool = False  # set by a human (or policy) to allow side-effect skills
    id: str = field(default_factory=new_id)
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["status"] = self.status.value
        return d


@dataclass
class TaskResult:
    task_id: str
    ok: bool
    output: Any = None
    error: str | None = None
    worker: str | None = None
    manager: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()
