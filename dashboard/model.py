"""Immutable status model shared by sources, the store and the snapshot API."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

StageName = Literal["healthy", "alerting", "interim", "rca", "permanent", "resolved"]
WaitingFor = Literal["none", "human", "system"]


@dataclass(frozen=True)
class VmMetrics:
    mem_used_pct: float | None = None
    cpu_pct: float | None = None
    disk_used_pct: float | None = None


@dataclass(frozen=True)
class ServiceStatus:
    rss_mb: float | None = None
    cache_entries: int | None = None
    version: str | None = None
    deployed_ref: str | None = None
    deployed_at: str | None = None
    archive_entries: int | None = None
    replay_started_at: str | None = None


@dataclass(frozen=True)
class ScorePoint:
    time: str
    score: float


@dataclass(frozen=True)
class DetectorStatus:
    score: float | None = None
    groups: dict[str, float] = field(default_factory=dict)
    top_feature: str | None = None
    latest_bin: str | None = None
    series: tuple[ScorePoint, ...] = ()


@dataclass(frozen=True)
class AlertStatus:
    key: Literal["ml", "memlow"]
    rule: str
    condition: Literal["Fired", "Resolved", "None"]
    severity: str | None = None
    fired_at: str | None = None
    alert_id: str | None = None


@dataclass(frozen=True)
class AgentStep:
    time: str | None
    text: str


@dataclass(frozen=True)
class Approval:
    id: str
    action: str
    requested_at: str | None = None


@dataclass(frozen=True)
class AgentStatus:
    thread_id: str | None = None
    title: str | None = None
    steps: tuple[AgentStep, ...] = ()
    approvals: tuple[Approval, ...] = ()


@dataclass(frozen=True)
class IssueStatus:
    number: int
    title: str
    state: str
    labels: tuple[str, ...]
    url: str


@dataclass(frozen=True)
class PullStatus:
    number: int
    title: str
    state: str
    merged: bool
    url: str
    merge_sha: str | None = None


@dataclass(frozen=True)
class RunStatus:
    workflow: Literal["deploy-app", "incident-approved"]
    status: str
    conclusion: str | None
    head_sha: str
    url: str
    created_at: str | None = None


@dataclass(frozen=True)
class TicketStatus:
    issue: IssueStatus | None = None
    pull: PullStatus | None = None
    runs: tuple[RunStatus, ...] = ()

    def run(self, workflow: str) -> RunStatus | None:
        return next((r for r in self.runs if r.workflow == workflow), None)


@dataclass(frozen=True)
class LiveState:
    power_state: str | None = None
    metrics: VmMetrics = field(default_factory=VmMetrics)
    service: ServiceStatus = field(default_factory=ServiceStatus)
    detector: DetectorStatus = field(default_factory=DetectorStatus)
    alerts: tuple[AlertStatus, ...] = ()
    agent: AgentStatus = field(default_factory=AgentStatus)
    ticket: TicketStatus = field(default_factory=TicketStatus)

    def alert(self, key: str) -> AlertStatus | None:
        return next((a for a in self.alerts if a.key == key), None)


@dataclass(frozen=True)
class StageStatus:
    current: StageName
    waiting_for: WaitingFor
    detail: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Event:
    time: str
    source: str
    message: str
    link_id: str | None = None


@dataclass(frozen=True)
class SourceStatus:
    name: str
    ok: bool
    age_sec: float | None
    error: str | None = None


@dataclass(frozen=True)
class Link:
    url: str
    label: str
    exact: bool = True


@dataclass(frozen=True)
class Environment:
    resource_group: str
    vm_name: str
    repo: str


@dataclass(frozen=True)
class Snapshot:
    generated_at: str
    mode: Literal["live", "demo"]
    refresh_ms: int
    environment: Environment
    stage: StageStatus
    state: LiveState
    events: tuple[Event, ...]
    sources: tuple[SourceStatus, ...]
    links: dict[str, Link]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
