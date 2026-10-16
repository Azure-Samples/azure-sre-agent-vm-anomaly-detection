"""Log Analytics source: guest metrics, demo-app health and deploy lines, anomaly scores."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from dashboard import queries
from dashboard.config import Config
from dashboard.model import DetectorStatus, ScorePoint, ServiceStatus, VmMetrics

Rows = list[dict[str, object]]
RunQuery = Callable[[str, timedelta], Rows]

HEALTH = re.compile(r"health rss_mb=(\d+) cache_entries=(\d+)\b.*\bversion=(\S+)")
ARCHIVE = re.compile(r"\barchive_entries=(\d+)")
DEPLOY = re.compile(r"^deploy (\S+) by \S+")


def parse_health_line(message: str) -> tuple[float, int, int | None, str] | None:
    match = HEALTH.search(message)
    if not match:
        return None
    archive = ARCHIVE.search(message)
    return float(match[1]), int(match[2]), int(archive[1]) if archive else None, match[3]


def _text(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return None if value is None else str(value)


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _groups(details: object) -> dict[str, float]:
    if isinstance(details, str):
        details = json.loads(details or "{}")
    groups = details.get("groups", {}) if isinstance(details, dict) else {}
    return {str(k): float(v) for k, v in groups.items() if isinstance(v, int | float)}


class LawSource:
    name = "law"

    def __init__(self, config: Config, run_query: RunQuery, interval_s: float = 30.0) -> None:
        self.interval_s = interval_s
        self._vm = config.vm_name
        self._run = run_query

    def poll(self) -> dict[str, object]:
        return {
            "metrics": self._metrics(),
            "service": self._service(),
            "detector": self._detector(),
        }

    def _metrics(self) -> VmMetrics:
        rows = {
            r["CounterName"]: r for r in self._run(queries.metrics(self._vm), timedelta(minutes=10))
        }

        def value(counter: str, column: str) -> float | None:
            row = rows.get(counter)
            return _number(row[column]) if row else None

        return VmMetrics(
            value("% Used Memory", "Avg"),
            value("% Processor Time", "Avg"),
            value("% Used Space", "Max"),
        )

    def _service(self) -> ServiceStatus:
        health: tuple[float, int, int | None, str] | None = None
        deploy: tuple[str, str | None] | None = None
        replay_at: str | None = None
        for row in self._run(queries.service(self._vm), timedelta(hours=2)):
            message = str(row["SyslogMessage"])
            health = health or parse_health_line(message)
            if replay_at is None and message.startswith("history replay started"):
                replay_at = _text(row["TimeGenerated"])
            match = DEPLOY.search(message)
            if deploy is None and match:
                deploy = (match[1], _text(row["TimeGenerated"]))
        rss, cache, archive, version = health or (None, None, None, None)
        ref, deployed_at = deploy or (None, None)
        return ServiceStatus(rss, cache, version, ref, deployed_at, archive, replay_at)

    def _detector(self) -> DetectorStatus:
        rows = self._run(queries.scores(self._vm), timedelta(minutes=60))
        series = tuple(
            ScorePoint(_text(r["TimeGenerated"]) or "", score)
            for r in rows
            if (score := _number(r["Score"])) is not None
        )
        if not rows:
            return DetectorStatus()
        last = rows[-1]
        return DetectorStatus(
            score=_number(last["Score"]),
            groups=_groups(last.get("Details")),
            top_feature=_text(last.get("TopFeature")),
            latest_bin=_text(last["TimeGenerated"]),
            series=series,
        )


class LogsClient(Protocol):
    def query_resource(self, resource_id: str, query: str, *, timespan: timedelta) -> object: ...


def logs_runner(client: LogsClient, workspace_resource_id: str) -> RunQuery:
    """Adapt azure.monitor.query.LogsQueryClient to RunQuery."""

    def run(query: str, timespan: timedelta) -> Rows:
        result = client.query_resource(workspace_resource_id, query, timespan=timespan)
        tables = getattr(result, "tables", None) or getattr(result, "partial_data", None) or []
        if not tables:
            return []
        columns = list(tables[0].columns)
        return [dict(zip(columns, row, strict=True)) for row in tables[0].rows]

    return run
