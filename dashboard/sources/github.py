"""GitHub source: incident issue, the PR that references it, and workflow runs."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal

from dashboard.config import Config
from dashboard.model import IssueStatus, PullStatus, RunStatus, TicketStatus

Get = Callable[[str], object]
WORKFLOWS: tuple[Literal["incident-approved", "deploy-app"], ...] = (
    "incident-approved",
    "deploy-app",
)


def _dicts(payload: object) -> list[dict[str, object]]:
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _str(item: dict[str, object], key: str) -> str:
    value = item.get(key)
    return value if isinstance(value, str) else ""


class GitHubSource:
    name = "github"

    def __init__(
        self, config: Config, get: Get, now: Callable[[], datetime], interval_s: float = 15.0
    ) -> None:
        self.interval_s = interval_s
        self._c = config
        self._get = get
        self._now = now

    def poll(self) -> dict[str, object]:
        issue = self._issue()
        pull = self._pull(issue.number) if issue else None
        return {"ticket": TicketStatus(issue, pull, self._runs())}

    def _issue(self) -> IssueStatus | None:
        since = (self._now() - timedelta(hours=self._c.window_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        path = f"/repos/{self._c.repo}/issues?labels=incident&state=all&sort=created&direction=desc&per_page=10&since={since}"
        for item in _dicts(self._get(path)):
            number = item.get("number")
            if "pull_request" in item or not isinstance(number, int):
                continue
            labels = tuple(_str(label, "name") for label in _dicts(item.get("labels")))
            return IssueStatus(
                number, _str(item, "title"), _str(item, "state"), labels, _str(item, "html_url")
            )
        return None

    def _pull(self, issue_number: int) -> PullStatus | None:
        reference = re.compile(rf"#{issue_number}\b")
        path = f"/repos/{self._c.repo}/pulls?state=all&sort=created&direction=desc&per_page=20"
        for item in _dicts(self._get(path)):
            number = item.get("number")
            if isinstance(number, int) and reference.search(
                f"{_str(item, 'title')} {_str(item, 'body')}"
            ):
                merged = bool(item.get("merged_at"))
                sha = _str(item, "merge_commit_sha") or None
                return PullStatus(
                    number,
                    _str(item, "title"),
                    _str(item, "state"),
                    merged,
                    _str(item, "html_url"),
                    sha if merged else None,
                )
        return None

    def _runs(self) -> tuple[RunStatus, ...]:
        runs = []
        for workflow in WORKFLOWS:
            payload = self._get(
                f"/repos/{self._c.repo}/actions/workflows/{workflow}.yml/runs?per_page=1"
            )
            items = _dicts(payload.get("workflow_runs") if isinstance(payload, dict) else None)
            if items:
                run = items[0]
                runs.append(
                    RunStatus(
                        workflow,
                        _str(run, "status"),
                        _str(run, "conclusion") or None,
                        _str(run, "head_sha"),
                        _str(run, "html_url"),
                        _str(run, "created_at") or None,
                    )
                )
        return tuple(runs)
