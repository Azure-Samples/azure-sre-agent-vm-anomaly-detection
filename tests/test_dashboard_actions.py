import threading
from datetime import UTC, datetime

import pytest

from dashboard.actions import Action, ActionRunner
from dashboard.demo import DemoClock

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def _runner(run):
    return ActionRunner([Action("inject", "Inject", "Deploy the leak", run)], clock=lambda: NOW)


def _wait(runner):
    for _ in range(200):
        current = runner.describe()["current"]
        if current and current["state"] != "running":
            return current
        threading.Event().wait(0.01)
    raise AssertionError("action did not finish")


def test_given_successful_action_when_started_then_status_is_succeeded_with_message():
    # Arrange
    runner = _runner(lambda: "deployed incident/example")

    # Act
    runner.start("inject")
    status = _wait(runner)

    # Assert
    assert (status["state"], status["message"]) == ("succeeded", "deployed incident/example")


def test_given_failing_action_when_started_then_status_is_failed_with_reason():
    # Arrange
    def fail():
        raise RuntimeError("VM is deallocated")

    runner = _runner(fail)

    # Act
    runner.start("inject")
    status = _wait(runner)

    # Assert
    assert (status["state"], status["message"]) == ("failed", "VM is deallocated")


def test_given_running_action_when_started_again_then_start_is_refused():
    # Arrange
    release = threading.Event()
    runner = _runner(lambda: release.wait(5) and "done")
    runner.start("inject")

    # Act
    second = runner.start("inject")
    release.set()

    # Assert
    assert second is False


def test_given_unknown_action_when_started_then_raises_key_error():
    # Arrange
    runner = _runner(lambda: "ok")

    # Act / Assert
    with pytest.raises(KeyError):
        runner.start("rm -rf")


def test_given_runner_when_describe_then_lists_available_actions_without_callables():
    # Act
    described = _runner(lambda: "ok").describe()

    # Assert
    assert described == {
        "available": [{"name": "inject", "label": "Inject", "description": "Deploy the leak"}],
        "current": None,
    }


def test_given_demo_clock_when_jump_then_scenario_restarts_at_that_minute():
    # Arrange
    clock = DemoClock(speed=1.0)

    # Act
    clock.jump(24.0)

    # Assert
    assert 24.0 <= clock.advance() < 24.1
