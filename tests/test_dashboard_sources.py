import json
from datetime import UTC, datetime

import pytest

from dashboard.config import Config
from dashboard.sources.arm import ArmSource
from dashboard.sources.github import GitHubSource
from dashboard.sources.law import LawSource, parse_health_line
from dashboard.sources.sre_agent import SreAgentSource

CONFIG = Config(subscription_id="sub-1")
NOW = datetime(2026, 9, 23, 13, 0, tzinfo=UTC)


def _law_rows(query, _timespan):
    if query.startswith("Perf"):
        return [
            {"CounterName": "% Used Memory", "Avg": 41.0, "Max": 42.0, "Time": "t"},
            {"CounterName": "% Processor Time", "Avg": 7.5, "Max": 20.0, "Time": "t"},
            {"CounterName": "% Used Space", "Avg": 10.0, "Max": 33.0, "Time": "t"},
        ]
    if query.startswith("Syslog"):
        return [
            {
                "TimeGenerated": "2026-09-23T12:53:00Z",
                "SyslogMessage": "WARNING memory above warning level (256 MB) health rss_mb=612 "
                "cache_entries=2310 cache_bytes_approx=1 version=release/x@a1b2c3d4e5f6",
            },
            {
                "TimeGenerated": "2026-09-23T12:24:30Z",
                "SyslogMessage": "deploy release/x@a1b2c3d4e5f6 by azureuser",
            },
            {
                "TimeGenerated": "2026-09-23T12:20:00Z",
                "SyslogMessage": "history replay started: /report?at= batch",
            },
        ]
    return [
        {"TimeGenerated": "12:45", "Score": 0.7, "TopFeature": "a", "Details": "{}"},
        {
            "TimeGenerated": "12:46",
            "Score": 0.83,
            "TopFeature": "mem_available_mb__slope",
            "Details": json.dumps({"groups": {"memory": 0.83, "cpu": 0.02}}),
        },
    ]


def test_given_law_rows_when_poll_then_returns_metrics_service_and_detector():
    # Act
    changes = LawSource(CONFIG, _law_rows).poll()

    # Assert
    assert (
        changes["metrics"].mem_used_pct,
        changes["metrics"].cpu_pct,
        changes["metrics"].disk_used_pct,
        changes["service"].rss_mb,
        changes["service"].deployed_ref,
        changes["detector"].score,
        changes["detector"].groups,
        len(changes["detector"].series),
    ) == (41.0, 7.5, 33.0, 612.0, "release/x@a1b2c3d4e5f6", 0.83, {"memory": 0.83, "cpu": 0.02}, 2)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "health rss_mb=18 cache_entries=64 cache_bytes_approx=1 version=main@a1",
            (18.0, 64, None, "main@a1"),
        ),
        (
            "health rss_mb=900 cache_entries=64 cache_bytes_approx=1 archive_entries=3400 version=main@a1",
            (900.0, 64, 3400, "main@a1"),
        ),
        ("deploy main@a1 by azureuser", None),
    ],
)
def test_given_syslog_message_when_parse_health_line_then_extracts_fields(message, expected):
    # Act
    result = parse_health_line(message)

    # Assert
    assert result == expected


def _arm_get(url):
    if "/instanceView" in url:
        return {
            "statuses": [{"code": "ProvisioningState/succeeded"}, {"code": "PowerState/running"}]
        }
    rule = (
        "/subscriptions/sub-1/resourceGroups/rg/providers/microsoft.insights/scheduledqueryrules/"
    )
    return {
        "value": [
            {
                "id": "/alerts/old",
                "properties": {
                    "essentials": {
                        "alertRule": rule + "Alert-ML-Anomaly-VM-App-01",
                        "monitorCondition": "Resolved",
                        "severity": "Sev2",
                        "startDateTime": "2026-09-23T10:00:00Z",
                    }
                },
            },
            {
                "id": "/alerts/new",
                "properties": {
                    "essentials": {
                        "alertRule": rule + "alert-ml-anomaly-vm-app-01",
                        "monitorCondition": "Fired",
                        "severity": "Sev2",
                        "startDateTime": "2026-09-23T12:50:51Z",
                    }
                },
            },
        ]
    }


def test_given_arm_payloads_when_poll_then_returns_power_state_and_latest_alerts():
    # Act
    changes = ArmSource(CONFIG, _arm_get).poll()

    # Assert
    ml, memlow = changes["alerts"]
    assert (changes["power_state"], ml.condition, ml.alert_id, memlow.condition) == (
        "running",
        "Fired",
        "/alerts/new",
        "None",
    )


def _github_get(path):
    if "/issues" in path:
        return [
            {"number": 44, "pull_request": {}, "title": "pr", "state": "open", "labels": []},
            {
                "number": 42,
                "title": "VM memory anomaly",
                "state": "open",
                "labels": [{"name": "incident"}, {"name": "approved"}],
                "html_url": "https://github.com/o/r/issues/42",
            },
        ]
    if "/pulls" in path:
        return [
            {"number": 41, "title": "other", "body": "Fixes #420", "state": "open"},
            {
                "number": 43,
                "title": "Bound ReportCache",
                "body": "Fixes #42",
                "state": "closed",
                "merged_at": "2026-09-23T13:10:00Z",
                "merge_commit_sha": "f00dfeed",
                "html_url": "https://github.com/o/r/pull/43",
            },
        ]
    workflow = "deploy-app" if "deploy-app.yml" in path else "incident-approved"
    return {
        "workflow_runs": [
            {
                "status": "completed",
                "conclusion": "success",
                "head_sha": workflow,
                "created_at": "2026-09-23T13:11:00Z",
                "html_url": f"https://github.com/o/r/actions/runs/{workflow}",
            }
        ]
    }


def test_given_github_payloads_when_poll_then_links_issue_pull_and_runs():
    # Act
    ticket = GitHubSource(CONFIG, _github_get, now=lambda: NOW).poll()["ticket"]

    # Assert
    assert (
        ticket.issue.number,
        ticket.issue.labels,
        ticket.pull.number,
        ticket.pull.merged,
        [run.workflow for run in ticket.runs],
    ) == (42, ("incident", "approved"), 43, True, ["incident-approved", "deploy-app"])


def _sre_get(url, scope):
    if url.startswith("https://management.azure.com"):
        return {"properties": {"agentEndpoint": "https://agent.example"}}
    assert scope == "https://azuresre.dev/.default"
    if url.endswith("/api/v1/threads"):
        return {
            "value": [
                {"id": "t-old", "title": "old", "createdAt": "2026-09-20T00:00:00Z"},
                {
                    "id": "t1",
                    "title": "[Sev2] alert-ml-anomaly-vm-app-01",
                    "createdAt": "2026-09-23T12:51:05Z",
                },
            ]
        }
    if url.endswith("/messages"):
        return {
            "value": [
                {"role": "user", "content": "alert", "createdAt": "2026-09-23T12:51:05Z"},
                {
                    "role": "assistant",
                    "content": "Alert acknowledged\ndetails",
                    "createdAt": "2026-09-23T12:51:10Z",
                },
            ]
        }
    return {
        "value": [
            {"id": "ap0", "description": "old", "status": "Approved"},
            {
                "id": "ap1",
                "description": "systemctl restart demo-app.service",
                "status": "Pending",
                "createdAt": "2026-09-23T12:53:05Z",
            },
        ]
    }


def test_given_agent_payloads_when_poll_then_returns_recent_thread_steps_and_pending_approvals():
    # Act
    agent = SreAgentSource(CONFIG, _sre_get, now=lambda: NOW).poll()["agent"]

    # Assert
    assert (
        agent.thread_id,
        [step.text for step in agent.steps],
        [approval.id for approval in agent.approvals],
    ) == ("t1", ["Alert acknowledged"], ["ap1"])


def _sre_incident_get(url, scope):
    if url.startswith("https://management.azure.com"):
        return {"properties": {"agentEndpoint": "https://agent.example"}}
    if url.endswith("/api/v1/threads"):
        return {
            "value": [
                {
                    "id": "inc-1",
                    "title": "[Sev2] alert-ml-anomaly-vm-app-01",
                    "startMessage": {"timeStamp": "2026-09-23T12:32:35.5827401Z"},
                },
                {
                    "id": "chat-1",
                    "title": "Welcome to the sample agent",
                    "startMessage": {"timeStamp": "2026-09-23T12:50:00Z", "text": "Hello"},
                },
            ]
        }
    if url.endswith("/messages"):
        agent = {"role": "SREAgent"}
        return {
            "value": [
                {
                    "timeStamp": "2026-09-23T12:32:35Z",
                    "author": agent,
                    "text": "```incident-alert\n{}",
                },
                {
                    "timeStamp": "2026-09-23T12:32:43Z",
                    "author": agent,
                    "messageType": "Reasoning",
                    "text": "**Thinking**",
                },
                {
                    "timeStamp": "2026-09-23T12:32:47Z",
                    "author": agent,
                    "text": "Starting the incident triage flow.",
                },
                {
                    "timeStamp": "2026-09-23T12:34:58Z",
                    "author": agent,
                    "text": "",
                    "azCliExecution": {
                        "id": "exec-1",
                        "status": "Pending",
                        "command": "az vm run-command invoke -g rg -n vm --command-id RunShellScript "
                        "--scripts 'sudo systemctl restart demo-app.service && curl -f x'",
                        "createdTimestamp": "2026-09-23T12:34:58Z",
                    },
                },
            ]
        }
    return {"value": []}


def test_given_incident_thread_when_poll_then_reads_start_time_agent_steps_and_pending_cli_approval():
    # Act
    agent = SreAgentSource(CONFIG, _sre_incident_get, now=lambda: NOW).poll()["agent"]

    # Assert
    assert (
        agent.thread_id,
        [step.text for step in agent.steps],
        [(a.id, a.action) for a in agent.approvals],
    ) == (
        "inc-1",
        ["Starting the incident triage flow."],
        [("exec-1", "sudo systemctl restart demo-app.service && curl -f x")],
    )


def test_given_replay_marker_when_poll_then_service_reports_replay_start():
    # Act
    service = LawSource(CONFIG, _law_rows).poll()["service"]

    # Assert
    assert service.replay_started_at == "2026-09-23T12:20:00Z"
