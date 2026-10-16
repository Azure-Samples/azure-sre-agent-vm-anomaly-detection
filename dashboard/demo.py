"""Scripted memory-leak incident used for rehearsal and offline demonstrations.

Times are synthetic scenario minutes after 12:00Z.
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime, timedelta

from dashboard.actions import Action
from dashboard.model import (
    AgentStatus,
    AgentStep,
    AlertStatus,
    Approval,
    DetectorStatus,
    IssueStatus,
    PullStatus,
    RunStatus,
    ScorePoint,
    ServiceStatus,
    TicketStatus,
    VmMetrics,
)

BASE = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
REPO_URL = "https://github.com/example/vm-anomaly-demo"
BASE_SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
FIX_SHA = "f00dfeed7a9b3c1d2e4f5a6b7c8d9e0f11223344"
BASE_REF = f"main@{BASE_SHA[:12]}"
FIX_REF = FIX_SHA[:12]

REPLAY_START, RESTART, DEPLOY_FIX = 48.5, 56.0, 78.0
LEAK_MB = 4900  # 60 % of the 8 GiB VM, archived by one bulk export
ALERT_FIRED, ALERT_RESOLVED = 50.85, 89.0
THREAD, APPROVAL_ASKED = 51.1, 53.1
ISSUE_OPENED, LABEL_APPROVED, PR_OPENED, PR_MERGED, ISSUE_CLOSED = 61.0, 64.0, 70.0, 76.0, 90.0

STEPS = (
    (51.1, "Alert acknowledged · first anomalous bin 12:50Z"),
    (51.7, "Triage: memory branch from Details.groups"),
    (52.5, "Perf: available memory dropped by 4.8 GB within a minute"),
    (53.1, "Proposed restart of demo-app.service (Review mode)"),
    (56.0, "Restart approved and executed · /health OK"),
    (57.5, "Syslog: demo-app rss_mb grows with archive_entries"),
    (59.0, "Onset matches history replay batch start (no deploy)"),
    (60.2, "Root cause: report archive never evicts (app/server.py)"),
    (61.0, "Opened incident issue #42"),
    (79.5, f"Deployed {FIX_REF} · memory flat"),
    (89.5, "Verified: Score < 0.8 for 10 min, alert resolved"),
    (89.6, "Commented verification evidence on issue #42 for human close"),
)


def _at(minutes: float) -> str:
    return (BASE + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


class DemoScenario:
    length_min = 100.0

    def rss_mb(self, t: float) -> float:
        if REPLAY_START <= t < RESTART:
            return 18 + LEAK_MB * min(1.0, (t - REPLAY_START) * 3)
        return 18.0

    def score(self, t: float) -> float:
        noise = 0.03 * math.sin(t * 1.7)
        if t < REPLAY_START + 1:
            return 0.06 + noise
        if t < REPLAY_START + 2:
            return 0.1 + (t - REPLAY_START - 1) * 0.73
        if t < DEPLOY_FIX:
            return 0.83 + noise
        return max(0.06, 0.83 - (t - DEPLOY_FIX) * 0.13) + noise / 3

    def changes_at(self, t: float) -> dict[str, object]:
        rss = self.rss_mb(t)
        archive = round((rss - 18) * 4) if REPLAY_START <= t < RESTART else 0
        replay_at = _at(REPLAY_START) if t >= REPLAY_START else None
        if t < DEPLOY_FIX:
            ref, deployed_at = BASE_REF, _at(-57.3)
        else:
            ref, deployed_at = FIX_REF, _at(DEPLOY_FIX)
        score = self.score(t)
        series = tuple(
            ScorePoint(_at(m), round(self.score(m), 3))
            for m in range(max(0, math.floor(t) - 59), math.floor(t) + 1)
        )
        return {
            "power_state": "running",
            "metrics": VmMetrics(round(6 + rss / 81.92, 1), round(4 + 2 * math.sin(t), 1), 33.0),
            "service": ServiceStatus(round(rss), 64, ref, ref, deployed_at, archive, replay_at),
            "detector": DetectorStatus(
                score=round(score, 3),
                groups={"memory": round(score, 3), "cpu": 0.02, "disk": 0.0},
                top_feature="mem_available_mb__slope" if score > 0.3 else None,
                latest_bin=_at(math.floor(t)),
                series=series,
            ),
            "alerts": (self._ml_alert(t), AlertStatus("memlow", "alert-mem-low-vm-app-01", "None")),
            "agent": self._agent(t),
            "ticket": self._ticket(t),
        }

    def _ml_alert(self, t: float) -> AlertStatus:
        rule = "alert-ml-anomaly-vm-app-01"
        if t < ALERT_FIRED:
            return AlertStatus("ml", rule, "None")
        condition = "Resolved" if t >= ALERT_RESOLVED else "Fired"
        return AlertStatus("ml", rule, condition, "Sev2", _at(ALERT_FIRED), "demo-alert-1")

    def _agent(self, t: float) -> AgentStatus:
        if t < THREAD:
            return AgentStatus()
        steps = tuple(AgentStep(_at(m), text) for m, text in STEPS if m <= t)
        approvals = (
            (Approval("approval-1", "systemctl restart demo-app.service", _at(APPROVAL_ASKED)),)
            if APPROVAL_ASKED <= t < RESTART
            else ()
        )
        return AgentStatus("thread-7f3a", "ML VM anomaly on vm-app-01", steps, approvals)

    def _ticket(self, t: float) -> TicketStatus:
        issue = None
        if t >= ISSUE_OPENED:
            labels = ("incident", "sre-agent") + (("approved",) if t >= LABEL_APPROVED else ())
            issue = IssueStatus(
                42,
                "VM memory anomaly: vm-app-01 report archive grows under history replay",
                "closed" if t >= ISSUE_CLOSED else "open",
                labels,
                f"{REPO_URL}/issues/42",
            )
        pull = None
        if t >= PR_OPENED:
            merged = t >= PR_MERGED
            pull = PullStatus(
                43,
                "Bound the historical report archive",
                "closed" if merged else "open",
                merged,
                f"{REPO_URL}/pull/43",
                FIX_SHA if merged else None,
            )
        runs: list[RunStatus] = []
        if t >= LABEL_APPROVED + 0.3:
            runs.append(
                RunStatus(
                    "incident-approved",
                    "completed",
                    "success",
                    BASE_SHA,
                    f"{REPO_URL}/actions/runs/1001",
                    _at(64.3),
                )
            )
        if t < PR_MERGED + 0.2:
            runs.append(
                RunStatus(
                    "deploy-app",
                    "completed",
                    "success",
                    BASE_SHA,
                    f"{REPO_URL}/actions/runs/1000",
                    _at(-58),
                )
            )
        else:
            done = t >= DEPLOY_FIX
            runs.append(
                RunStatus(
                    "deploy-app",
                    "completed" if done else "in_progress",
                    "success" if done else None,
                    FIX_SHA,
                    f"{REPO_URL}/actions/runs/1002",
                    _at(PR_MERGED + 0.2),
                )
            )
        return TicketStatus(issue, pull, tuple(runs))


class DemoClock:
    """Scenario clock; `minutes` advances with wall time times `speed` and loops."""

    def __init__(
        self, speed: float, start_min: float = 0.0, length_min: float = DemoScenario.length_min
    ) -> None:
        self.speed = speed
        self.start_min = start_min
        self.length_min = length_min
        self.minutes = start_min
        self._started = time.monotonic()

    def advance(self) -> float:
        elapsed = (time.monotonic() - self._started) * self.speed / 60
        self.minutes = (self.start_min + elapsed) % self.length_min
        return self.minutes

    def jump(self, minute: float) -> None:
        self.start_min = self.minutes = minute
        self._started = time.monotonic()

    def now(self) -> datetime:
        return BASE + timedelta(minutes=self.minutes)


class DemoSource:
    name = "demo"

    def __init__(
        self, clock: DemoClock, scenario: DemoScenario | None = None, interval_s: float = 1.0
    ) -> None:
        self.interval_s = interval_s
        self._clock = clock
        self._scenario = scenario or DemoScenario()

    def poll(self) -> dict[str, object]:
        return self._scenario.changes_at(self._clock.advance())


def demo_actions(clock: DemoClock) -> list[Action]:
    """Same buttons as live mode; they move the scenario clock instead of touching Azure."""

    def inject() -> str:
        clock.jump(REPLAY_START - 0.2)
        return "scenario jumped to the history replay start"

    def restore() -> str:
        clock.jump(0.0)
        return "scenario reset to healthy"

    return [
        Action(
            "inject-memory-leak",
            "Inject memory leak",
            "Scripted: start history-replay traffic",
            inject,
        ),
        Action("restore", "Stop incident", "Scripted: restart the scenario", restore),
    ]
