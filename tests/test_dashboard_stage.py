import pytest

from dashboard.model import (
    AgentStatus,
    AlertStatus,
    Approval,
    DetectorStatus,
    IssueStatus,
    LiveState,
    PullStatus,
    RunStatus,
    StageStatus,
    TicketStatus,
)
from dashboard.stage import derive_stage, latch

FIRED = AlertStatus(key="ml", rule="alert-ml-anomaly-vm-app-01", condition="Fired")
THREAD = AgentStatus(thread_id="t1", title="ML VM anomaly on vm-app-01")
APPROVAL = Approval(id="a1", action="systemctl restart demo-app.service")
ISSUE = IssueStatus(
    number=42, title="VM memory anomaly", state="open", labels=("incident",), url="https://x"
)
APPROVED = IssueStatus(
    number=42, title="t", state="open", labels=("incident", "approved"), url="https://x"
)
CLOSED = IssueStatus(number=42, title="t", state="closed", labels=("incident",), url="https://x")
OPEN_PR = PullStatus(number=43, title="fix", state="open", merged=False, url="https://x")
MERGED_PR = PullStatus(
    number=43,
    title="fix",
    state="closed",
    merged=True,
    merge_sha="f00dfeed1234abcd",
    url="https://x",
)
DEPLOYED = RunStatus(
    workflow="deploy-app",
    status="completed",
    conclusion="success",
    head_sha="f00dfeed1234abcd",
    url="https://x",
)


@pytest.mark.parametrize(
    ("state", "mitigation_seen", "current", "waiting_for"),
    [
        (LiveState(), False, "healthy", "none"),
        (LiveState(detector=DetectorStatus(score=0.83)), False, "alerting", "system"),
        (LiveState(alerts=(FIRED,)), False, "alerting", "system"),
        (LiveState(alerts=(FIRED,), agent=THREAD), False, "interim", "system"),
        (
            LiveState(agent=AgentStatus(thread_id="t1", approvals=(APPROVAL,))),
            False,
            "interim",
            "human",
        ),
        (LiveState(agent=THREAD), True, "rca", "system"),
        (LiveState(ticket=TicketStatus(issue=ISSUE)), True, "permanent", "human"),
        (LiveState(ticket=TicketStatus(issue=APPROVED)), True, "permanent", "system"),
        (LiveState(ticket=TicketStatus(issue=APPROVED, pull=OPEN_PR)), True, "permanent", "human"),
        (
            LiveState(ticket=TicketStatus(issue=APPROVED, pull=MERGED_PR, runs=(DEPLOYED,))),
            True,
            "permanent",
            "system",
        ),
        (LiveState(ticket=TicketStatus(issue=CLOSED)), True, "resolved", "none"),
    ],
)
def test_given_observed_state_when_derive_stage_then_returns_expected_stage(
    state, mitigation_seen, current, waiting_for
):
    # Act
    stage = derive_stage(state, mitigation_seen)

    # Assert
    assert (stage.current, stage.waiting_for) == (current, waiting_for)


def test_given_fix_deployed_when_derive_stage_then_detail_is_verifying():
    # Arrange
    state = LiveState(ticket=TicketStatus(issue=APPROVED, pull=MERGED_PR, runs=(DEPLOYED,)))

    # Act
    stage = derive_stage(state, True)

    # Assert
    assert stage.detail.startswith("Verifying")


@pytest.mark.parametrize(
    ("previous", "derived", "expected"),
    [
        ("rca", "alerting", "rca"),
        ("rca", "healthy", "healthy"),
        ("interim", "permanent", "permanent"),
        ("resolved", "healthy", "healthy"),
    ],
)
def test_given_previous_stage_when_latch_then_stage_never_regresses_within_incident(
    previous, derived, expected
):
    # Arrange
    prev = StageStatus(current=previous, waiting_for="none", detail="")
    new = StageStatus(current=derived, waiting_for="none", detail="")

    # Act
    result = latch(new, prev)

    # Assert
    assert result.current == expected
