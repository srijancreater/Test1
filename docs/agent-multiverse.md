# Agent Multiverse: design and operating guide

One orchestrator, a manager per department, and hundreds to thousands of worker agents that do
everyday tasks. Workers can only use the skills assigned to them. They handle one-off jobs, repeated
jobs and multi-step jobs.

```
                         ┌──────────────────────────────────────────┐
  you / scheduler ──────▶│ ORCHESTRATOR (Multiverse)                     │
  CLI / bulk file        │  1. recall a learned playbook, or plan   │  Claude planner (effort=high,
                         │  2. split into a DAG of steps            │  JSON-schema output)
                         │  3. route each step to a department      │
                         │  4. run independent steps in parallel    │
                         │  5. hold side effects for approval       │
                         │  6. combine results, learn the playbook  │
                         └───────┬───────────┬───────────┬──────────┘
                ┌────────────────┘           │           └────────────────┐
        ┌───────▼───────┐            ┌───────▼───────┐            ┌───────▼───────┐
        │ Research Mgr  │            │ Comms Mgr     │   ...      │ Finance Mgr   │  MANAGERS
        │ pool, retries │            │ pool, retries │            │ pool, retries │  (one per department)
        │ escalation    │            │ escalation    │            │ escalation    │
        └───────┬───────┘            └───────┬───────┘            └───────┬───────┘
          250 workers                  200 workers                  100 workers        WORKERS
     (each: allowed skills,       (Claude tool loop, or a        (stats, audit trail)
      system prompt, id)           direct skill call)
                         │
      ┌──────────────────▼──────────────────────────────────────────────┐
      │ SKILLS  built-ins · skills_contrib/*.py plugins · connector actions│
      │ CONNECTORS files · http · email(SMTP) · webhook(Slack/Teams/Zapier)│
      │            calendar(.ics) · notes(shared memory) · your own        │
      └────────────────────────────────────────────────────────────────────┘
        MEMORY  SQLite: tasks, results, playbooks (learned plans), audit log
```

## Who does what

| Role | Count (default config) | Responsibility |
|---|---|---|
| Orchestrator | 1 | Takes a goal and plans it, or reuses a learned playbook. Routes steps, resolves dependencies, gates approvals, writes the final answer, learns from the run. |
| Research Manager | 1 → 250 workers | Look things up, fetch pages, read files, summarize, extract keywords. |
| Communications Manager | 1 → 200 workers | Draft and send email, post chat notifications, suggest replies. |
| Operations Manager | 1 → 300 workers | Calendar, reminders, todos, notes, files, day plans: everyday admin. |
| Finance Manager | 1 → 100 workers | Budgets, expenses, bill splitting, calculations. |
| Data Manager | 1 → 150 workers | CSV/JSON stats and conversions. |

You change counts, departments and managers in `config/multiverse.toml`, with no code changes. Use
`--scale 0.01` for a tiny multiverse or `--scale 10` for 10,000 workers. A worker is a small Python
object, so the pool size is cheap. The real limit is `max_concurrency`, the number of concurrent
Claude requests shared by the whole multiverse.

## What kind of work

* **One-off tasks:** `run "Calculate 1200*12*0.18; then draft an email to sam@x.com about the tax estimate"`.
* **Repeated tasks:** `bulk tasks.jsonl` sends thousands of independent tasks out in parallel, and
  managers throttle by pool size. `serve` runs `[[schedule]]` jobs (`every_minutes`, or `at` + `days`).
* **Complex tasks:** the planner breaks the goal into steps. Steps with no dependencies run at the
  same time in different departments. Later steps get earlier outputs (`{{s1}}`).
* **Learning:** a goal that succeeds is saved as a *playbook* under a normalized key. Numbers,
  dates, emails and URLs are masked, so "daily report for 2026-11-25" matches tomorrow's run. Next
  time the plan is reused and the planner call is skipped. Failures are counted. A playbook with
  more failures than successes is re-planned. `playbooks` lists them and `forget KEY` drops one.

## Safety

* Skills tagged `side_effect` (`email.send`, `http.post_json`, `webhook.notify`) stop and wait for a
  human when `approval_policy = "ask"`. The task is parked as a concrete call with real arguments,
  and `approve ID` runs exactly that call. Set `auto_approve` to trust specific skills; `deny`
  disables side effects entirely.
* Workers can only call skills assigned to their department.
* The files connector is sandboxed to the workspace. `MULTIVERSE_HTTP_ALLOW` restricts HTTP hosts.
* Every skill call, error, escalation, plan and approval goes to the `audit` log.
* Email and webhook run in **dry-run mode** (writing to `.multiverse/outbox/`) until credentials are set.

## Adding skills

Drop a file in `skills_contrib/`:

```python
from agent_multiverse import skill

@skill(tags={"department:ops"})
def plan_my_day(tasks: str, start_hour: int = 9) -> list[str]:
    """Turn a list of tasks into an hour-by-hour plan."""
    ...
```

The type hints become the tool's JSON schema, and the docstring becomes its description. Add
`"side_effect"` to the tags if the skill changes the outside world. Async functions and a `ctx`
parameter (access to `ctx.llm()`, `ctx.connector()`, `ctx.workspace`) are supported.

## Adding connectors

Subclass `Connector`, set `env_vars` (the connector switches to live mode when they are present),
return `Skill`s from `actions()`, then call `fleet.connectors.register(...)` and register its actions.
Each action becomes the skill `<connector>.<action>`.

| Connector | Live when set | Otherwise |
|---|---|---|
| email | `MULTIVERSE_SMTP_HOST`, `MULTIVERSE_SMTP_USER`, `MULTIVERSE_SMTP_PASSWORD` (+ `MULTIVERSE_SMTP_PORT`, `MULTIVERSE_SMTP_FROM`) | `.eml` files in `.multiverse/outbox/` |
| webhook | `MULTIVERSE_WEBHOOK_URL` (Slack/Teams/Discord/Zapier incoming webhook) | `.multiverse/outbox/webhook.log` |
| http | always (optional `MULTIVERSE_HTTP_ALLOW` allowlist) | |
| files, calendar, notes | always (local workspace) | |

Through a Zapier or Make webhook, `webhook.notify` / `http.post_json` can reach thousands of SaaS
apps without writing a connector for each.

## The model

* `llm = "auto"` uses Claude when credentials exist (`ANTHROPIC_API_KEY` or `ant auth login`).
  Otherwise it falls back to the deterministic **offline** backend: keyword planning plus direct
  skill calls. That keeps the multiverse, the tests and CI runnable without a key.
* Workers run a Messages-API tool loop on `claude-opus-5-5` at `effort = "medium"`. Parallel tool
  calls are executed at the same time and returned in one message. Tool errors go back to the
  model as `is_error` results.
* The planner uses JSON-schema structured output at `effort = "high"`.
* Requests send `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`). If a safety
  classifier declines a request, the API retries it on a fallback model. A refusal that still
  ends as a refusal is raised as an error, and the manager retries the task, then escalates.
* To cut cost on high-volume chores, lower `effort` to `low`, or set `model` to a cheaper model
  for workers and keep the planner on Opus.

Alternative: Anthropic's hosted **Managed Agents** (multi-agent workflows, scheduled deployments,
vault credentials) runs the agent loop and sandbox for you. This framework is the self-hosted
version: you own the loop, the data and the connectors.
