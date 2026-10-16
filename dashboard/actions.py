"""Presenter actions (commands): a fixed allow-list, one at a time, run in the background."""

from __future__ import annotations

import logging
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Literal

from dashboard.store import iso, utcnow

log = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parent.parent
SCRIPT_TIMEOUT_S = 900


@dataclass(frozen=True)
class Action:
    name: str
    label: str
    description: str
    run: Callable[[], str]


@dataclass(frozen=True)
class ActionStatus:
    name: str
    label: str
    state: Literal["running", "succeeded", "failed"]
    started_at: str
    finished_at: str | None = None
    message: str = ""


class ActionRunner:
    def __init__(self, actions: Sequence[Action], clock: Callable[[], datetime] = utcnow) -> None:
        self._actions = {action.name: action for action in actions}
        self._clock = clock
        self._lock = threading.Lock()
        self._status: ActionStatus | None = None

    def start(self, name: str) -> bool:
        """Raises KeyError for names outside the allow-list; False while another action runs."""
        action = self._actions[name]
        with self._lock:
            if self._status and self._status.state == "running":
                return False
            self._status = ActionStatus(name, action.label, "running", iso(self._clock()))
        threading.Thread(
            target=self._run, args=(action,), name=f"action-{name}", daemon=True
        ).start()
        return True

    def _run(self, action: Action) -> None:
        try:
            state, message = "succeeded", action.run()
        except Exception as error:  # noqa: BLE001 - any failure is reported to the presenter
            log.warning("action %s failed: %s", action.name, error)
            state, message = "failed", str(error)[:300]
        with self._lock:
            if self._status is not None:
                self._status = replace(
                    self._status, state=state, finished_at=iso(self._clock()), message=message
                )

    def describe(self) -> dict[str, object]:
        with self._lock:
            current = asdict(self._status) if self._status else None
        available = [
            {"name": a.name, "label": a.label, "description": a.description}
            for a in self._actions.values()
        ]
        return {"available": available, "current": current}


def script(relative: str) -> Callable[[], str]:
    """Run a repository script without a shell; return its last output line."""

    def run() -> str:
        result = subprocess.run(
            [str(REPO / relative)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=SCRIPT_TIMEOUT_S,
            check=False,
        )
        lines = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]
        if result.returncode != 0:
            raise RuntimeError(lines[-1] if lines else f"{relative} exited {result.returncode}")
        return lines[-1] if lines else "done"

    return run


def live_actions() -> list[Action]:
    return [
        Action(
            "inject-memory-leak",
            "Inject memory leak",
            "One bulk history export on vm-app-01, 60% of VM memory (scripts/inject_traffic.sh)",
            script("scripts/inject_traffic.sh"),
        ),
        Action(
            "restore",
            "Stop incident",
            "Restart demo-app to release the memory (scripts/stop_traffic.sh)",
            script("scripts/stop_traffic.sh"),
        ),
    ]
