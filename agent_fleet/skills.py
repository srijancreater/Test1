"""Skill registry. A skill = name + description + JSON schema + handler + tags.

Tags drive routing and safety:
  department:<name>   which manager owns it (a skill may belong to several)
  side_effect         changes the outside world (send, post, pay, delete) -> needs approval
"""
from __future__ import annotations

import asyncio
import importlib.util
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

Handler = Callable[..., Any]


@dataclass
class Skill:
    name: str
    description: str
    handler: Handler
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    tags: set[str] = field(default_factory=set)

    @property
    def side_effect(self) -> bool:
        return "side_effect" in self.tags

    @property
    def departments(self) -> set[str]:
        return {t.split(":", 1)[1] for t in self.tags if t.startswith("department:")}

    async def run(self, ctx: "SkillContext", **kwargs: Any) -> Any:
        params = inspect.signature(self.handler).parameters
        if "ctx" in params:
            kwargs["ctx"] = ctx
        result = self.handler(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    def as_tool(self) -> dict[str, Any]:
        """Claude Messages API tool definition."""
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


@dataclass
class SkillContext:
    """Passed to handlers that accept `ctx`: access to the fleet's connectors, memory and workspace."""

    fleet: Any
    task: Any
    worker: str

    @property
    def workspace(self) -> Path:
        return self.fleet.workspace

    def connector(self, name: str) -> Any:
        return self.fleet.connectors.get(name)

    async def llm(self, prompt: str, system: str = "") -> str:
        return await self.fleet.llm.complete(prompt, system=system)


_PENDING: list[Skill] = []


def _schema_from_signature(fn: Handler) -> dict[str, Any]:
    pytypes = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}
    props: dict[str, Any] = {}
    required: list[str] = []
    hints = getattr(fn, "__annotations__", {})
    for name, p in inspect.signature(fn).parameters.items():
        if name == "ctx" or p.kind in (p.VAR_KEYWORD, p.VAR_POSITIONAL):
            continue
        t = hints.get(name, str)
        if isinstance(t, str):
            t = {"str": str, "int": int, "float": float, "bool": bool, "list": list, "dict": dict}.get(t.split(" ")[0], str)
        props[name] = {"type": pytypes.get(t, "string")}
        if p.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


def skill(name: str | None = None, description: str | None = None, tags: set[str] | list[str] | None = None,
          input_schema: dict[str, Any] | None = None) -> Callable[[Handler], Handler]:
    """Decorator: `@skill(tags={"department:comms", "side_effect"})`. Picked up by SkillRegistry.load_*."""

    def wrap(fn: Handler) -> Handler:
        s = Skill(
            name=name or fn.__name__,
            description=(description or (fn.__doc__ or fn.__name__)).strip(),
            handler=fn,
            input_schema=input_schema or _schema_from_signature(fn),
            tags=set(tags or ()),
        )
        fn.__skill__ = s  # type: ignore[attr-defined]
        _PENDING.append(s)
        return fn

    return wrap


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, s: Skill) -> Skill:
        self._skills[s.name] = s
        return s

    def unregister(self, name: str) -> None:
        self._skills.pop(name, None)

    def get(self, name: str) -> Skill:
        if name not in self._skills:
            raise KeyError(f"unknown skill: {name}")
        return self._skills[name]

    def __contains__(self, name: str) -> bool:
        return name in self._skills

    def __iter__(self):
        return iter(sorted(self._skills.values(), key=lambda s: s.name))

    def __len__(self) -> int:
        return len(self._skills)

    def for_department(self, dept: str) -> list[Skill]:
        return [s for s in self if dept in s.departments]

    def load_module_skills(self, module: Any) -> int:
        n = 0
        for obj in vars(module).values():
            s = getattr(obj, "__skill__", None)
            if isinstance(s, Skill):
                self.register(s)
                n += 1
        return n

    def load_directory(self, path: str | Path) -> int:
        """Load every *.py file in `path` as a skill plugin. Drop a file in, get new skills."""
        path = Path(path)
        n = 0
        if not path.is_dir():
            return 0
        for f in sorted(path.glob("*.py")):
            if f.name.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(f"fleet_plugin_{f.stem}", f)
            if not spec or not spec.loader:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            n += self.load_module_skills(mod)
        return n


def run_sync(coro):
    return asyncio.run(coro)
