import base64
import gzip
from urllib.parse import unquote

from dashboard import queries
from dashboard.config import Config
from dashboard.links import LinkBuilder
from dashboard.model import (
    AgentStatus,
    IssueStatus,
    LiveState,
    StageStatus,
    TicketStatus,
)

CONFIG = Config(tenant_id="tenant-1", subscription_id="sub-1")
HEALTHY = StageStatus(current="healthy", waiting_for="none", detail="")
ISSUE = IssueStatus(
    number=42,
    title="t",
    state="open",
    labels=("incident",),
    url="https://github.com/o/r/issues/42",
)


def test_given_config_when_build_then_vm_link_opens_resource_in_tenant():
    # Act
    links = LinkBuilder(CONFIG).build(LiveState(), HEALTHY)

    # Assert
    assert links["vm"].url == (
        "https://portal.azure.com/#@tenant-1/resource/subscriptions/sub-1/resourceGroups/"
        "rg-vm-anomaly-demo/providers/Microsoft.Compute/virtualMachines/vm-app-01/overview"
    )


def test_given_config_when_build_then_detector_link_embeds_compressed_score_query():
    # Act
    url = LinkBuilder(CONFIG).build(LiveState(), HEALTHY)["detector"].url

    # Assert
    encoded = unquote(url.split("/q/")[1].split("/")[0])
    assert gzip.decompress(base64.b64decode(encoded)).decode() == queries.scores(CONFIG.vm_name)


def test_given_thread_template_when_build_then_agent_link_is_exact_thread_url():
    # Arrange
    config = Config(sre_thread_url_template="https://sre.azure.com/threads/{thread_id}")
    state = LiveState(agent=AgentStatus(thread_id="abc"))

    # Act
    link = LinkBuilder(config).build(state, HEALTHY)["agent"]

    # Assert
    assert (link.url, link.exact) == ("https://sre.azure.com/threads/abc", True)


def test_given_thread_when_build_then_agent_link_opens_thread_in_sre_portal():
    # Arrange
    state = LiveState(agent=AgentStatus(thread_id="abc"))

    # Act
    link = LinkBuilder(CONFIG).build(state, HEALTHY)["agent"]

    # Assert
    expected = (
        "https://sre.azure.com/agents/subscriptions/sub-1/resourceGroups/rg-vm-anomaly-demo/"
        "providers/Microsoft.App/agents/sreagent-vm-anomaly/views/thread/abc"
    )
    assert (link.url, link.exact) == (expected, True)


def test_given_no_thread_when_build_then_agent_link_opens_agent_in_sre_portal():
    # Act
    link = LinkBuilder(CONFIG).build(LiveState(), HEALTHY)["agent"]

    # Assert
    assert link.url.endswith("/agents/sreagent-vm-anomaly")


def test_given_issue_when_build_then_issue_and_stage_link_use_html_url():
    # Arrange
    state = LiveState(ticket=TicketStatus(issue=ISSUE))
    stage = StageStatus(current="permanent", waiting_for="human", detail="")

    # Act
    links = LinkBuilder(CONFIG).build(state, stage)

    # Assert
    assert links["issue"].url == links["stage:permanent"].url == ISSUE.url


def test_given_no_issue_when_build_then_issue_link_is_absent():
    # Act
    links = LinkBuilder(CONFIG).build(LiveState(), HEALTHY)

    # Assert
    assert "issue" not in links


def test_given_non_https_url_when_build_then_link_is_dropped():
    # Arrange
    unsafe = IssueStatus(number=1, title="t", state="open", labels=(), url="javascript:alert(1)")
    state = LiveState(ticket=TicketStatus(issue=unsafe))

    # Act
    links = LinkBuilder(CONFIG).build(state, HEALTHY)

    # Assert
    assert "issue" not in links


def test_given_config_when_build_then_logs_link_has_one_hour_timespan():
    # Act
    url = LinkBuilder(CONFIG).build(LiveState(), HEALTHY)["perf"].url

    # Assert
    assert url.endswith("/timespan/PT1H")
