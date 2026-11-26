import asyncio
import datetime as dt
import json
from types import SimpleNamespace

import pytest

from agent_multiverse import Task, build_multiverse
from agent_multiverse.multiverse import playbook_key
from agent_multiverse.llm import ClaudeBackend
from agent_multiverse.models import TaskStatus
from agent_multiverse.scheduler import Job
from agent_multiverse.skills import Skill

DEPTS = [{"name": n, "workers": w} for n, w in
         [("research", 5), ("comms", 5), ("ops", 5), ("finance", 3), ("data", 3)]]


@pytest.fixture
def fleet(tmp_path):
    cfg = {"multiverse": {"llm": "offline", "store": ":memory:", "approval_policy": "ask"}, "department": DEPTS}
    return build_multiverse(cfg, workspace=tmp_path)


def run(coro):
    return asyncio.run(coro)


def test_builds_departments_and_skills(fleet):
    assert fleet.worker_count == 21
    assert {"research", "comms", "ops", "finance", "data"} == set(fleet.managers)
    assert "email.send" in fleet.skills and fleet.skills.get("email.send").side_effect
    assert "split_bill" in fleet.skills  # plugin from skills_contrib/


def test_direct_skill(fleet):
    r = run(fleet.submit(Task(goal="x", skill="calculate", args={"expression": "(2+3)*4"})))
    assert r.ok and r.output == 20 and r.manager == "finance-manager"


def test_thousand_agents_bulk(tmp_path):
    cfg = {"multiverse": {"llm": "offline", "store": ":memory:"},
           "department": [{"name": "finance", "workers": 600}, {"name": "data", "workers": 600}]}
    f = build_multiverse(cfg, workspace=tmp_path)
    assert f.worker_count == 1200
    res = run(f.submit_many([Task(goal="c", skill="calculate", args={"expression": f"{i}+1"}) for i in range(3000)]))
    assert all(r.ok for r in res)
    assert [r.output for r in res[:3]] == [1, 2, 3]
    assert {r.manager for r in res} == {"finance-manager", "data-manager"}  # load-balanced


def test_plan_dependencies_and_learning(fleet):
    rep = run(fleet.run("Calculate 6*7; then summarize the result"))
    assert rep.ok and not rep.from_playbook and len(rep.steps) == 2
    assert rep.steps[0]["output"] == 42
    rep2 = run(fleet.run("Calculate 8*9; then summarize the result"))
    assert rep2.from_playbook and rep2.ok


def test_file_to_note_pipeline(fleet):
    (fleet.workspace / "files").mkdir(exist_ok=True)
    (fleet.workspace / "files" / "inbox.txt").write_text("TODO: pay rent\n- call mom\nhello\n")
    rep = run(fleet.run("Read files/inbox.txt and extract action items; then save them as a note"))
    assert rep.ok
    assert rep.steps[0]["output"] == ["pay rent", "call mom"]
    assert "pay rent" in (fleet.workspace / "notes.json").read_text()


def test_side_effect_needs_approval(fleet):
    r = run(fleet.submit(Task(goal="mail", skill="email.send",
                              args={"to": "a@b.co", "subject": "hi", "body": "yo"})))
    assert not r.ok
    pending = fleet.pending_approvals()
    assert len(pending) == 1 and pending[0]["status"] == TaskStatus.WAITING_APPROVAL.value
    r2 = run(fleet.approve(pending[0]["id"]))
    assert r2.ok and "dry-run" in r2.output
    assert list((fleet.workspace / "outbox").glob("*.eml"))
    assert fleet.pending_approvals() == []


def test_agentic_side_effect_parks_concrete_call(fleet):
    rep = run(fleet.run("send email to pat@example.com about lunch"))
    assert rep.waiting_approval and not rep.learned
    row = fleet.store.task(rep.waiting_approval[0])
    assert row["skill"] == "email.send" and json.loads(row["args"])["to"] == "pat@example.com"


def test_deny_and_auto_policies(fleet):
    fleet.approval_policy = "deny"
    r = run(fleet.submit(Task(goal="n", skill="webhook.notify", args={"text": "x"}, max_retries=0)))
    assert not r.ok and "deny" in r.error
    fleet.approval_policy = "ask"  # webhook.notify is not in auto_approve here
    fleet.auto_approve.add("webhook.notify")
    assert run(fleet.submit(Task(goal="n", skill="webhook.notify", args={"text": "x"}))).ok


def test_retries_then_success(fleet):
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("temporary")
        return "fine"

    fleet.skills.register(Skill("flaky", "flaky", flaky, tags={"department:ops"}))
    fleet.add_department("ops", 2)
    r = run(fleet.submit(Task(goal="f", skill="flaky", max_retries=2)))
    assert r.ok and r.output == "fine" and calls["n"] == 3


def test_failure_escalates(fleet):
    def broken() -> str:
        raise ValueError("nope")

    fleet.skills.register(Skill("broken", "broken", broken, tags={"department:ops"}))
    fleet.add_department("ops", 2)
    r = run(fleet.submit(Task(goal="b", skill="broken", max_retries=1)))
    assert not r.ok and "nope" in r.error
    assert any(a["event"] == "escalated" for a in fleet.store.audit_log())


def test_worker_cannot_use_foreign_skill(fleet):
    w = fleet.managers["finance"].workers[0]
    with pytest.raises(PermissionError):
        run(w.call_skill(Task(goal="x"), "email.send", {}))


def test_workspace_sandbox(fleet):
    r = run(fleet.submit(Task(goal="r", skill="files.read", args={"path": "../../etc/passwd"}, max_retries=0)))
    assert not r.ok and "escapes" in r.error


def test_calendar_and_notes(fleet):
    assert run(fleet.submit(Task(goal="e", skill="calendar.add_event",
                                 args={"title": "Dentist", "start": "2026-12-01T09:00"}))).ok
    assert run(fleet.submit(Task(goal="l", skill="calendar.list_events"))).output == ["Dentist"]


def test_playbook_key_normalizes_variables():
    assert playbook_key("Email bob@x.com the report for 2026-11-25") == playbook_key("email ann@y.org the report for 2025-01-02")


def test_scheduler_due():
    j = Job("m", "g", at="08:30", days=["mon"])
    mon = dt.datetime(2026, 11, 23, 9, 0)
    assert j.due(mon)
    j.last_run = mon
    assert not j.due(mon + dt.timedelta(hours=1))
    assert not j.due(dt.datetime(2026, 11, 24, 9, 0))  # tuesday
    e = Job("e", "g", every_minutes=10)
    assert e.due(mon)
    e.last_run = mon
    assert not e.due(mon + dt.timedelta(minutes=5)) and e.due(mon + dt.timedelta(minutes=10))


# ---- Claude backend tool loop with a fake client (no network)

class FakeMessages:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    async def create(self, **kw):
        self.calls.append({**kw, "messages": list(kw.get("messages", []))})
        return self.responses.pop(0)


def _resp(stop, *blocks):
    return SimpleNamespace(stop_reason=stop, stop_details=None, content=list(blocks))


def test_claude_tool_loop_parallel_calls(fleet):
    b = ClaudeBackend.__new__(ClaudeBackend)
    b.model = b.planner_model = "claude-opus-5-5"
    b.effort = "low"
    b.sem = asyncio.Semaphore(4)
    fake = FakeMessages([
        _resp("tool_use",
              SimpleNamespace(type="tool_use", id="u1", name="calculate", input={"expression": "2*3"}),
              SimpleNamespace(type="tool_use", id="u2", name="notes__put", input={"key": "k", "value": "v"})),
        _resp("end_turn", SimpleNamespace(type="text", text="done: 6")),
    ])
    b.client = SimpleNamespace(beta=SimpleNamespace(messages=fake))
    fleet.llm = b
    w = fleet.managers["finance"].workers[0]
    r = run(w.execute(Task(goal="compute and save")))
    assert r.ok and r.output == "done: 6"
    assert {s["tool"] for s in r.steps} == {"calculate", "notes.put"}
    first, second = fake.calls
    assert all("." not in t["name"] for t in first["tools"])
    assert first["fallbacks"] == "default" and first["output_config"]["effort"] == "low"
    results = second["messages"][-1]["content"]
    assert [x["tool_use_id"] for x in results] == ["u1", "u2"]  # all results in one user message
    assert results[0]["content"] == "6"


def test_claude_refusal_raises():
    b = ClaudeBackend.__new__(ClaudeBackend)
    b.model, b.effort, b.sem = "claude-opus-5-5", "low", asyncio.Semaphore(1)
    b.client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages([
        SimpleNamespace(stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"), content=[])])))
    with pytest.raises(RuntimeError, match="declined"):
        run(b.complete("hi"))


# ---- deterministic facts: Wikipedia lookup (network replaced by recorded responses)

WIKI_FIXTURES = {
    "search": {"query": {"search": [{"title": "Mark Zuckerberg"}]}},
    "summary": {"title": "Mark Zuckerberg", "description": "American businessman (born 1984)",
                "extract": "Mark Elliot Zuckerberg is an American businessman who co-founded Facebook.",
                "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Mark_Zuckerberg"}}},
}


@pytest.fixture
def fake_wiki(monkeypatch):
    from agent_multiverse import builtin_skills
    calls = []

    def fake(url):
        calls.append(url)
        if "list=search" in url:
            return {"query": {"search": []}} if "Nonexistentxyz" in url else WIKI_FIXTURES["search"]
        return WIKI_FIXTURES["summary"]

    monkeypatch.setattr(builtin_skills, "_wiki_get", fake)
    return calls


@pytest.mark.parametrize("text,topic", [
    ("Get a summary of Mark Zuckerberg.", "Mark Zuckerberg"),
    ("Who is Ada Lovelace?", "Ada Lovelace"),
    ("Tell me about the Eiffel Tower", "Eiffel Tower"),
    ("summary of Infosys", "Infosys"),
    ("Please give me a short biography of Sachin Tendulkar", "Sachin Tendulkar"),
])
def test_clean_topic(text, topic):
    from agent_multiverse.builtin_skills import clean_topic
    assert clean_topic(text) == topic


def test_summary_of_person_returns_sourced_facts(fleet, fake_wiki):
    rep = run(fleet.run("Get a summary of Mark Zuckerberg."))
    assert rep.ok and rep.steps[0]["skill"] in (None, "lookup")
    out = rep.steps[0]["output"]
    assert out["found"] and out["title"] == "Mark Zuckerberg"
    assert "co-founded Facebook" in out["summary"]
    assert out["source"].startswith("https://en.wikipedia.org/wiki/")
    assert "srsearch=Mark%20Zuckerberg" in fake_wiki[0]
    assert rep.steps[0]["worker"].startswith("research-")


def test_lookup_is_deterministic_and_reports_misses(fleet, fake_wiki):
    a = run(fleet.submit(Task(goal="x", skill="lookup", args={"topic": "Mark Zuckerberg"}))).output
    b = run(fleet.submit(Task(goal="x", skill="lookup", args={"topic": "Mark Zuckerberg"}))).output
    assert a == b
    miss = run(fleet.submit(Task(goal="x", skill="lookup", args={"topic": "Nonexistentxyz"}))).output
    assert miss["found"] is False and "no article" in miss["summary"]


def test_summarize_with_text_still_summarizes(fleet, fake_wiki):
    rep = run(fleet.run("Summarize: Revenue grew 12%. Churn fell to 2.1%. Hiring is paused."))
    assert rep.ok and not fake_wiki
