import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from dashboard.actions import Action, ActionRunner
from dashboard.config import Config
from dashboard.demo import DemoClock, DemoScenario
from dashboard.server import create_server
from dashboard.store import StatusStore


def test_given_demo_scenario_when_played_then_stages_follow_incident_order():
    # Arrange
    scenario = DemoScenario()
    clock = DemoClock(speed=1.0)
    store = StatusStore(Config(), mode="demo", clock=clock.now)
    seen: list[str] = []

    # Act
    for step in range(int(scenario.length_min * 4)):
        clock.minutes = step / 4
        store.apply("demo", scenario.changes_at(clock.minutes))
        current = store.snapshot().stage.current
        if not seen or seen[-1] != current:
            seen.append(current)

    # Assert
    assert seen == ["healthy", "alerting", "interim", "rca", "permanent", "resolved"]


@pytest.fixture
def dashboard_url():
    http = create_server(lambda: {"stage": {"current": "healthy"}}, "127.0.0.1", 0)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    yield f"http://127.0.0.1:{http.server_port}"
    http.shutdown()
    http.server_close()
    worker.join()


def test_given_server_when_get_snapshot_then_returns_json_without_cache(dashboard_url):
    # Act
    with urlopen(f"{dashboard_url}/api/snapshot") as response:
        body = json.load(response)
        cache = response.headers["Cache-Control"]

    # Assert
    assert (body["stage"]["current"], cache) == ("healthy", "no-store")


def test_given_server_when_get_index_then_serves_page_with_csp(dashboard_url):
    # Act
    with urlopen(f"{dashboard_url}/") as response:
        page = response.read().decode()
        csp = response.headers["Content-Security-Policy"]

    # Assert
    assert ("importmap" in page, "default-src 'self'" in csp) == (True, True)


def test_given_path_outside_web_root_when_get_then_returns_not_found(dashboard_url):
    # Act
    with pytest.raises(HTTPError) as error:
        urlopen(f"{dashboard_url}/../server.py")

    # Assert
    assert error.value.code == 404


def test_given_foreign_host_header_when_get_snapshot_then_rejects_request(dashboard_url):
    # Arrange
    request = Request(f"{dashboard_url}/api/snapshot", headers={"Host": "attacker.example"})

    # Act
    with pytest.raises(HTTPError) as error:
        urlopen(request)

    # Assert
    assert error.value.code == 403


@pytest.fixture
def action_server():
    ran: list[str] = []
    runner = ActionRunner(
        [Action("inject", "Inject", "Deploy the leak", lambda: ran.append("x") or "ok")]
    )
    http = create_server(dict, "127.0.0.1", 0, runner)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    yield f"http://127.0.0.1:{http.server_port}", ran
    http.shutdown()
    http.server_close()
    worker.join()


def _post(base, path, headers):
    request = Request(f"{base}{path}", data=b"{}", method="POST", headers=headers)
    try:
        with urlopen(request) as response:
            return response.status
    except HTTPError as error:
        return error.code


@pytest.mark.parametrize(
    ("path", "headers", "expected"),
    [
        ("/api/actions/inject", {}, 403),
        ("/api/actions/inject", {"X-Dashboard-Action": "1", "Origin": "https://evil.example"}, 403),
        ("/api/actions/inject", {"Origin": "SELF"}, 403),
        ("/api/actions/unknown", {"X-Dashboard-Action": "1", "Origin": "SELF"}, 404),
        ("/api/actions/inject", {"X-Dashboard-Action": "1", "Origin": "SELF"}, 202),
    ],
)
def test_given_action_request_when_post_then_only_same_origin_dashboard_requests_run(
    action_server, path, headers, expected
):
    # Arrange
    base, _ = action_server
    headers = {k: (base if v == "SELF" else v) for k, v in headers.items()}

    # Act
    status = _post(base, path, headers)

    # Assert
    assert status == expected


def test_given_server_without_actions_when_post_then_returns_not_found(dashboard_url):
    # Act
    status = _post(
        dashboard_url, "/api/actions/inject", {"X-Dashboard-Action": "1", "Origin": dashboard_url}
    )

    # Assert
    assert status == 404
