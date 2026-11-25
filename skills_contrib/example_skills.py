"""Example skill plugin. Any *.py file in skills_contrib/ is loaded at startup.

A skill is just a function with type hints and a docstring. Tag it with the department(s)
that should get it; tag `side_effect` if it changes the outside world (then it needs approval).
"""
from agent_fleet import skill


@skill(tags={"department:ops"})
def plan_my_day(tasks: str, start_hour: int = 9) -> list[str]:
    """Turn a comma/newline separated list of tasks into a simple hour-by-hour day plan."""
    items = [t.strip() for t in tasks.replace("\n", ",").split(",") if t.strip()]
    return [f"{start_hour + i:02d}:00  {t}" for i, t in enumerate(items)]


@skill(tags={"department:finance"})
def split_bill(total: float, people: int, tip_percent: float = 0) -> float:
    """Split a bill evenly between people, optionally adding a tip."""
    return round(total * (1 + tip_percent / 100) / max(people, 1), 2)


@skill(tags={"department:comms"})
async def reply_suggestions(message: str, ctx=None) -> list[str]:
    """Suggest three short replies to a message."""
    if ctx is not None and ctx.fleet.llm.is_live:
        text = await ctx.llm(f"Give three short, different replies (one per line, no numbering) to:\n{message}")
        return [l.strip() for l in text.splitlines() if l.strip()][:3]
    return ["Thanks, got it!", "Let me check and get back to you.", "Sounds good - see you then."]
