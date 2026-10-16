"""Azure SRE Agent data plane source (preview API): latest incident thread and approvals.

Response schemas are not published in detail, so parsing accepts the common field
spellings and ignores anything else.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timedelta
from urllib.parse import quote

from dashboard.config import Config
from dashboard.model import AgentStatus, AgentStep, Approval
from dashboard.sources.http import MANAGEMENT_SCOPE, SRE_SCOPE

ARM = "https://management.azure.com"
Get = Callable[[str, str], object]
MAX_STEPS = 6
PENDING = {"pending", "waiting", "awaitingapproval", "requested"}
AGENT_ROLES = {"assistant", "agent", "sreagent"}
HIDDEN_TYPES = {"Reasoning", "TrajectoryInsight"}
INCIDENT_TITLE = re.compile(r"^\[Sev\d\]")
SCRIPT = re.compile(r"--scripts\s+'([^']*)'")


def _items(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, dict):
        payload = next(
            (payload[k] for k in ("value", "items", "threads", "data") if k in payload), []
        )
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _first(item: dict[str, object], *keys: str) -> str | None:
    return next((str(item[k]) for k in keys if item.get(k) not in (None, "")), None)


def _parse_time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


class SreAgentSource:
    name = "sre-agent"

    def __init__(
        self, config: Config, get: Get, now: Callable[[], datetime], interval_s: float = 10.0
    ) -> None:
        self.interval_s = interval_s
        self._c = config
        self._get = get
        self._now = now
        self._endpoint: str | None = None

    def _endpoint_url(self) -> str:
        if self._endpoint is None:
            agent = self._get(
                f"{ARM}{self._c.agent_id}?api-version=2025-05-01-preview", MANAGEMENT_SCOPE
            )
            properties = agent.get("properties", {}) if isinstance(agent, dict) else {}
            endpoint = properties.get("agentEndpoint") if isinstance(properties, dict) else None
            if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
                raise ValueError("agentEndpoint missing from agent resource")
            self._endpoint = endpoint.rstrip("/")
        return self._endpoint

    def poll(self) -> dict[str, object]:
        base = self._endpoint_url()
        since = self._now() - timedelta(hours=self._c.window_hours)
        threads = []
        for item in _items(self._get(f"{base}/api/v1/threads", SRE_SCOPE)):
            start = item.get("startMessage")
            created = _parse_time(
                _first(item, "createdAt", "createdDateTime", "created", "createdTime")
                or (_first(start, "timeStamp", "timestamp") if isinstance(start, dict) else None)
            )
            thread_id = _first(item, "id", "threadId", "name")
            if thread_id and created and created >= since and _is_incident(item):
                threads.append((created, thread_id, _first(item, "title", "displayName", "name")))
        if not threads:
            return {"agent": AgentStatus()}
        _, thread_id, title = max(threads)
        path = quote(thread_id, safe="")
        messages = _items(self._get(f"{base}/api/v1/threads/{path}/messages", SRE_SCOPE))
        approvals = self._approvals(base, path) + _pending_cli(messages)
        return {"agent": AgentStatus(thread_id, title, _steps(messages), approvals)}

    def _approvals(self, base: str, path: str) -> tuple[Approval, ...]:
        approvals = []
        for item in _items(self._get(f"{base}/api/v1/approvals/{path}", SRE_SCOPE)):
            status = (_first(item, "status", "state") or "pending").lower()
            approval_id = _first(item, "id", "approvalId")
            if approval_id and status in PENDING:
                action = _first(item, "description", "title", "command", "toolName") or "action"
                approvals.append(
                    Approval(approval_id, action[:100], _first(item, "createdAt", "requestedAt"))
                )
        return tuple(approvals)


def _is_incident(thread: dict[str, object]) -> bool:
    """Incident threads start from an alert; portal chats and onboarding threads do not."""
    title = _first(thread, "title", "displayName", "name") or ""
    start = thread.get("startMessage")
    text = (_first(start, "text") or "") if isinstance(start, dict) else ""
    return bool(INCIDENT_TITLE.match(title)) or text.startswith("```incident-alert")


def _role(message: dict[str, object]) -> str:
    author = message.get("author")
    if isinstance(author, dict):
        return str(author.get("role", "")).lower()
    return (_first(message, "role", "author", "sender") or "").lower()


def _steps(messages: list[dict[str, object]]) -> tuple[AgentStep, ...]:
    steps = []
    for message in messages:
        text = (_first(message, "content", "text", "message") or "").strip()
        if _role(message) not in AGENT_ROLES or not text or text.startswith("```"):
            continue
        if message.get("messageType") in HIDDEN_TYPES:
            continue
        time = _first(message, "createdAt", "timeStamp", "timestamp", "created")
        steps.append(AgentStep(time, text.splitlines()[0][:100]))
    return tuple(steps[-MAX_STEPS:])


def _pending_cli(messages: list[dict[str, object]]) -> tuple[Approval, ...]:
    """Review mode holds Azure CLI writes in the thread as executions with status Pending."""
    pending = []
    for message in messages:
        execution = message.get("azCliExecution")
        if not isinstance(execution, dict) or str(execution.get("status", "")).lower() != "pending":
            continue
        command = str(execution.get("command", ""))
        script = SCRIPT.search(command)
        action = script[1] if script else command
        execution_id = _first(execution, "id") or _first(message, "id") or "cli"
        pending.append(Approval(execution_id, action[:100], _first(execution, "createdTimestamp")))
    return tuple(pending)
