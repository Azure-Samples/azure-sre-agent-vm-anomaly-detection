"""Thread-safe status store: sources apply changes (commands), the API reads snapshots (query)."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

from dashboard.config import Config
from dashboard.events import diff
from dashboard.links import LinkBuilder
from dashboard.model import Environment, Event, LiveState, Snapshot, SourceStatus
from dashboard.stage import derive_stage, latch

MAX_EVENTS = 50


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class StatusStore:
    def __init__(
        self,
        config: Config,
        mode: Literal["live", "demo"],
        clock: Callable[[], datetime] = utcnow,
        refresh_ms: int = 5000,
    ) -> None:
        self._config = config
        self._mode = mode
        self._clock = clock
        self._refresh_ms = refresh_ms
        self._links = LinkBuilder(config)
        self._lock = threading.Lock()
        self._state = LiveState()
        self._stage = derive_stage(self._state, False)
        self._mitigation_seen = False
        self._events: list[Event] = []
        self._ok_at: dict[str, datetime] = {}
        self._errors: dict[str, str] = {}

    def apply(self, source: str, changes: Mapping[str, object]) -> None:
        with self._lock:
            now = self._clock()
            new_state = replace(self._state, **changes)
            if new_state.agent.approvals:
                self._mitigation_seen = True
            new_stage = latch(derive_stage(new_state, self._mitigation_seen), self._stage)
            if new_stage.current == "healthy":
                self._mitigation_seen = False
            self._events.extend(diff(self._state, new_state, self._stage, new_stage, iso(now)))
            del self._events[:-MAX_EVENTS]
            self._state, self._stage = new_state, new_stage
            self._ok_at[source] = now
            self._errors.pop(source, None)

    def fail(self, source: str, error: str) -> None:
        with self._lock:
            self._errors[source] = error

    def snapshot(self) -> Snapshot:
        with self._lock:
            now = self._clock()
            state, stage = self._state, self._stage
            events = tuple(self._events)
            sources = tuple(
                SourceStatus(
                    name,
                    name not in self._errors,
                    (now - self._ok_at[name]).total_seconds() if name in self._ok_at else None,
                    self._errors.get(name),
                )
                for name in sorted({*self._ok_at, *self._errors})
            )
        c = self._config
        return Snapshot(
            generated_at=iso(now),
            mode=self._mode,
            refresh_ms=self._refresh_ms,
            environment=Environment(c.resource_group, c.vm_name, c.repo),
            stage=stage,
            state=state,
            events=events,
            sources=sources,
            links=self._links.build(state, stage),
        )
