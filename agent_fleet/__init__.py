"""Agent Fleet: orchestrator -> managers -> hundreds/thousands of worker agents.

Layers
------
Orchestrator  intake, planning (decompose complex work into a DAG), routing, approvals, memory
Manager       owns one department, a pool of workers, concurrency, retries, escalation
Worker        executes one task with its assigned skills (tool loop via Claude, or direct skill call)
Skills        python callables with a JSON schema; connectors expose their actions as skills
Memory        remembers successful plans ("playbooks") so repeated tasks skip re-planning
Scheduler     recurring jobs (every N minutes / daily at HH:MM / weekdays)
"""
from .models import Task, TaskStatus, TaskResult
from .skills import Skill, SkillRegistry, skill
from .fleet import Fleet, build_fleet

__all__ = ["Task", "TaskStatus", "TaskResult", "Skill", "SkillRegistry", "skill", "Fleet", "build_fleet"]
__version__ = "0.1.0"
