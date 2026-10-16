"""Pollers that read one external system each and return LiveState field changes."""

from __future__ import annotations

import logging
import threading
from typing import Protocol

from dashboard.store import StatusStore

log = logging.getLogger(__name__)


class Source(Protocol):
    name: str
    interval_s: float

    def poll(self) -> dict[str, object]: ...


class Poller(threading.Thread):
    def __init__(self, source: Source, store: StatusStore, stop: threading.Event) -> None:
        super().__init__(name=f"poll-{source.name}", daemon=True)
        self._source, self._store, self._stop = source, store, stop

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self._store.apply(self._source.name, self._source.poll())
            except Exception as error:  # noqa: BLE001 - a failing source must not stop the dashboard
                log.warning("%s poll failed: %s", self._source.name, error)
                self._store.fail(self._source.name, f"{type(error).__name__}: {error}"[:200])
            self._stop.wait(self._source.interval_s)
