"""Connectors: adapters to the outside world. Each one works out of the box in a safe local mode
(writes to the workspace) and switches to the real service when its environment variables are set.

Add your own: subclass Connector, implement `actions()`, register with fleet.connectors.register(...).
Every action becomes a skill named `<connector>.<action>` automatically.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import smtplib
import ssl
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable

from .skills import Skill


class Connector:
    name = "base"
    description = ""
    env_vars: tuple[str, ...] = ()

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    @property
    def live(self) -> bool:
        """True when every required env var is present (real service); False = local/dry-run mode."""
        return bool(self.env_vars) and all(os.environ.get(v) for v in self.env_vars)

    def actions(self) -> list[Skill]:
        return []

    def status(self) -> dict[str, Any]:
        return {"name": self.name, "mode": "live" if self.live else "local", "needs": list(self.env_vars),
                "actions": [a.name for a in self.actions()]}

    def _skill(self, action: str, fn: Callable[..., Any], description: str, props: dict[str, Any],
               required: list[str], tags: set[str]) -> Skill:
        return Skill(name=f"{self.name}.{action}", description=description, handler=fn,
                     input_schema={"type": "object", "properties": props, "required": required}, tags=tags)


def _safe_path(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    if root.resolve() not in p.parents and p != root.resolve():
        raise PermissionError(f"path escapes workspace: {rel}")
    return p


class FilesConnector(Connector):
    name = "files"
    description = "Read/write files inside the multiverse workspace (sandboxed)."

    @property
    def live(self) -> bool:
        return True

    def actions(self) -> list[Skill]:
        root = self.workspace / "files"
        root.mkdir(parents=True, exist_ok=True)

        def read(path: str) -> str:
            return _safe_path(root, path).read_text(encoding="utf-8")

        def write(path: str, content: str) -> str:
            p = _safe_path(root, path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"wrote {len(content)} chars to {path}"

        def listdir(path: str = ".") -> list[str]:
            return sorted(str(x.relative_to(root)) for x in _safe_path(root, path).rglob("*") if x.is_file())

        tags = {"department:ops", "department:research", "department:data"}
        s = {"type": "string"}
        return [
            self._skill("read", read, "Read a text file from the workspace.", {"path": s}, ["path"], tags),
            self._skill("write", write, "Write a text file in the workspace.", {"path": s, "content": s}, ["path", "content"], tags),
            self._skill("list", listdir, "List files in the workspace.", {"path": s}, [], tags),
        ]


class HttpConnector(Connector):
    name = "http"
    description = "Fetch web pages / call JSON APIs. Optional allowlist: MULTIVERSE_HTTP_ALLOW=host1,host2"

    @property
    def live(self) -> bool:
        return True

    def _check(self, url: str) -> None:
        allow = [h.strip() for h in os.environ.get("MULTIVERSE_HTTP_ALLOW", "").split(",") if h.strip()]
        host = urllib.parse.urlparse(url).hostname or ""
        if urllib.parse.urlparse(url).scheme not in ("http", "https"):
            raise ValueError("only http(s) URLs are allowed")
        if allow and not any(host == a or host.endswith("." + a) for a in allow):
            raise PermissionError(f"host {host} not in MULTIVERSE_HTTP_ALLOW")

    def actions(self) -> list[Skill]:
        def get(url: str, max_chars: int = 20000) -> str:
            self._check(url)
            req = urllib.request.Request(url, headers={"User-Agent": "agent-multiverse/0.1"})
            with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 - scheme checked
                return r.read(max_chars * 4).decode("utf-8", "replace")[:max_chars]

        def post_json(url: str, payload: dict) -> str:
            self._check(url)
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "User-Agent": "agent-multiverse/0.1"})
            with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
                return r.read(20000).decode("utf-8", "replace")

        s = {"type": "string"}
        return [
            self._skill("get", get, "HTTP GET a URL and return the body text.", {"url": s, "max_chars": {"type": "integer"}},
                        ["url"], {"department:research", "department:data"}),
            self._skill("post_json", post_json, "HTTP POST a JSON payload to a URL.", {"url": s, "payload": {"type": "object"}},
                        ["url", "payload"], {"department:ops", "side_effect"}),
        ]


class EmailConnector(Connector):
    name = "email"
    description = "Send email via SMTP. Without credentials, messages are written to workspace/outbox/."
    env_vars = ("MULTIVERSE_SMTP_HOST", "MULTIVERSE_SMTP_USER", "MULTIVERSE_SMTP_PASSWORD")

    def actions(self) -> list[Skill]:
        def send(to: str, subject: str, body: str) -> str:
            if not self.live:
                out = self.workspace / "outbox"
                out.mkdir(parents=True, exist_ok=True)
                f = out / f"{dt.datetime.now():%Y%m%d-%H%M%S-%f}.eml"
                f.write_text(f"To: {to}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
                return f"[dry-run] saved to {f.name}"
            msg = EmailMessage()
            msg["From"] = os.environ.get("MULTIVERSE_SMTP_FROM", os.environ["MULTIVERSE_SMTP_USER"])
            msg["To"], msg["Subject"] = to, subject
            msg.set_content(body)
            port = int(os.environ.get("MULTIVERSE_SMTP_PORT", "587"))
            with smtplib.SMTP(os.environ["MULTIVERSE_SMTP_HOST"], port, timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(os.environ["MULTIVERSE_SMTP_USER"], os.environ["MULTIVERSE_SMTP_PASSWORD"])
                s.send_message(msg)
            return f"sent to {to}"

        s = {"type": "string"}
        return [self._skill("send", send, "Send an email.", {"to": s, "subject": s, "body": s},
                            ["to", "subject", "body"], {"department:comms", "side_effect"})]


class WebhookConnector(Connector):
    name = "webhook"
    description = "Post a message to Slack/Teams/Discord/Zapier incoming webhook (MULTIVERSE_WEBHOOK_URL)."
    env_vars = ("MULTIVERSE_WEBHOOK_URL",)

    def actions(self) -> list[Skill]:
        def notify(text: str) -> str:
            if not self.live:
                out = self.workspace / "outbox"
                out.mkdir(parents=True, exist_ok=True)
                with (out / "webhook.log").open("a", encoding="utf-8") as f:
                    f.write(f"{dt.datetime.now().isoformat()} {text}\n")
                return "[dry-run] appended to outbox/webhook.log"
            req = urllib.request.Request(os.environ["MULTIVERSE_WEBHOOK_URL"], data=json.dumps({"text": text}).encode(),
                                         method="POST", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
                return f"posted ({r.status})"

        return [self._skill("notify", notify, "Post a chat notification.", {"text": {"type": "string"}}, ["text"],
                            {"department:comms", "side_effect"})]


class CalendarConnector(Connector):
    name = "calendar"
    description = "Create calendar events in workspace/calendar.ics (import into Google/Outlook/Apple)."

    @property
    def live(self) -> bool:
        return True

    def actions(self) -> list[Skill]:
        ics = self.workspace / "calendar.ics"

        def add_event(title: str, start: str, minutes: int = 30, notes: str = "") -> str:
            t0 = dt.datetime.fromisoformat(start)
            t1 = t0 + dt.timedelta(minutes=minutes)
            fmt = "%Y%m%dT%H%M%S"
            body = ics.read_text(encoding="utf-8") if ics.exists() else "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//agent-multiverse//EN\nEND:VCALENDAR\n"
            uid = f"{t0:%Y%m%d%H%M%S}-{abs(hash(title)) % 10**8}@agent-multiverse"
            ev = (f"BEGIN:VEVENT\nUID:{uid}\nDTSTART:{t0:{fmt}}\nDTEND:{t1:{fmt}}\n"
                  f"SUMMARY:{title}\nDESCRIPTION:{notes}\nEND:VEVENT\n")
            ics.write_text(body.replace("END:VCALENDAR", ev + "END:VCALENDAR"), encoding="utf-8")
            return f"event '{title}' at {t0:%Y-%m-%d %H:%M}"

        def list_events() -> list[str]:
            if not ics.exists():
                return []
            return [l[8:] for l in ics.read_text(encoding="utf-8").splitlines() if l.startswith("SUMMARY:")]

        s = {"type": "string"}
        return [
            self._skill("add_event", add_event, "Add a calendar event. start is ISO datetime e.g. 2026-12-01T09:00.",
                        {"title": s, "start": s, "minutes": {"type": "integer"}, "notes": s}, ["title", "start"],
                        {"department:ops"}),
            self._skill("list_events", list_events, "List calendar event titles.", {}, [], {"department:ops"}),
        ]


class NotesConnector(Connector):
    name = "notes"
    description = "Shared key/value notebook every agent can read and write (workspace/notes.json)."

    @property
    def live(self) -> bool:
        return True

    def actions(self) -> list[Skill]:
        path = self.workspace / "notes.json"

        def _load() -> dict[str, Any]:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

        def put(key: str, value: str) -> str:
            d = _load()
            d[key] = value
            path.write_text(json.dumps(d, indent=2), encoding="utf-8")
            return f"saved {key}"

        def get(key: str) -> str:
            return _load().get(key, "")

        def append_todo(item: str) -> list[str]:
            d = _load()
            todos = json.loads(d.get("todos", "[]"))
            todos.append(item)
            d["todos"] = json.dumps(todos)
            path.write_text(json.dumps(d, indent=2), encoding="utf-8")
            return todos

        s = {"type": "string"}
        tags = {"department:ops", "department:research", "department:comms", "department:finance", "department:data"}
        return [
            self._skill("put", put, "Save a note under a key.", {"key": s, "value": s}, ["key", "value"], tags),
            self._skill("get", get, "Read a note by key.", {"key": s}, ["key"], tags),
            self._skill("append_todo", append_todo, "Add an item to the shared todo list.", {"item": s}, ["item"], tags),
        ]


BUILTIN_CONNECTORS = [FilesConnector, HttpConnector, EmailConnector, WebhookConnector, CalendarConnector, NotesConnector]


class ConnectorRegistry:
    def __init__(self) -> None:
        self._c: dict[str, Connector] = {}

    def register(self, c: Connector) -> Connector:
        self._c[c.name] = c
        return c

    def get(self, name: str) -> Connector:
        return self._c[name]

    def __iter__(self):
        return iter(self._c.values())

    def skills(self) -> list[Skill]:
        return [s for c in self for s in c.actions()]
