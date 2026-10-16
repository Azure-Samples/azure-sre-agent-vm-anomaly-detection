from datetime import UTC, datetime

from dashboard.config import Config
from dashboard.model import AgentStatus, AlertStatus, Approval, ServiceStatus
from dashboard.store import StatusStore

FIRED = AlertStatus(key="ml", rule="alert-ml-anomaly-vm-app-01", condition="Fired", severity="Sev2")
APPROVAL = Approval(id="a1", action="systemctl restart demo-app.service")


def _store():
    return StatusStore(
        Config(), mode="live", clock=lambda: datetime(2026, 9, 23, 13, 0, tzinfo=UTC)
    )


def test_given_fired_alert_when_apply_then_snapshot_is_alerting_with_alert_event():
    # Arrange
    store = _store()

    # Act
    store.apply("arm", {"alerts": (FIRED,)})
    snapshot = store.snapshot()

    # Assert
    assert (snapshot.stage.current, snapshot.events[0].link_id) == ("alerting", "alert:ml")


def test_given_approval_was_pending_when_it_disappears_then_stage_is_rca():
    # Arrange
    store = _store()
    store.apply("sre", {"agent": AgentStatus(thread_id="t1", approvals=(APPROVAL,))})

    # Act
    store.apply("sre", {"agent": AgentStatus(thread_id="t1")})

    # Assert
    assert store.snapshot().stage.current == "rca"


def test_given_healthy_state_when_new_thread_appears_then_mitigation_memory_is_reset():
    # Arrange
    store = _store()
    store.apply("sre", {"agent": AgentStatus(thread_id="t1", approvals=(APPROVAL,))})
    store.apply("sre", {"agent": AgentStatus()})

    # Act
    store.apply("sre", {"agent": AgentStatus(thread_id="t2")})

    # Assert
    assert store.snapshot().stage.current == "interim"


def test_given_source_failure_when_snapshot_then_source_reports_error():
    # Arrange
    store = _store()

    # Act
    store.fail("github", "401 Unauthorized")
    source = store.snapshot().sources[0]

    # Assert
    assert (source.name, source.ok, source.error) == ("github", False, "401 Unauthorized")


def test_given_replay_start_when_apply_then_event_names_the_traffic_onset():
    # Arrange
    store = _store()

    # Act
    store.apply("law", {"service": ServiceStatus(replay_started_at="2026-09-23T12:20:00Z")})

    # Assert
    assert [e.message for e in store.snapshot().events] == [
        "history replay started (batch /report?at= traffic)"
    ]
