"""Offline checks for portable publication settings."""

import importlib.util
import os
import plistlib
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

from dashboard.config import Config
from dashboard.server import main

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_commands(monkeypatch, tmp_path):
    for name in ("az", "gh", "launchctl", "ssh-keygen"):
        command = tmp_path / name
        command.write_text("#!/bin/sh\necho 'unexpected external command' >&2\nexit 99\n")
        command.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")


def test_given_no_environment_when_loading_config_then_no_private_defaults():
    config = Config.from_env({})

    assert (config.tenant_id, config.subscription_id, config.repo) == ("", "", "")


def test_given_explicit_environment_when_loading_config_then_settings_are_used():
    config = Config.from_env(
        {
            "DASHBOARD_TENANT_ID": "tenant-example",
            "DASHBOARD_SUBSCRIPTION_ID": "subscription-example",
            "DASHBOARD_REPO": "example/vm-anomaly-demo",
        }
    )

    assert (config.tenant_id, config.subscription_id, config.repo) == (
        "tenant-example",
        "subscription-example",
        "example/vm-anomaly-demo",
    )


def test_given_missing_live_settings_when_starting_dashboard_then_fails_before_polling(
    monkeypatch, caplog
):
    for name in ("DASHBOARD_TENANT_ID", "DASHBOARD_SUBSCRIPTION_ID", "DASHBOARD_REPO"):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setattr(
        "dashboard.server.live_sources",
        lambda _: pytest.fail("live sources must not start without configuration"),
    )

    code = main([])

    assert code == 2
    assert "DASHBOARD_SUBSCRIPTION_ID" in caplog.text


@pytest.mark.parametrize(
    ("script", "variable"),
    [
        ("sre-agent/configure.py", "AZURE_SUBSCRIPTION_ID"),
        ("sre-agent/lockdown.py", "AZURE_SUBSCRIPTION_ID"),
        ("infra/deploy.sh", "AZURE_SUBSCRIPTION_ID"),
        ("infra/teardown.sh", "AZURE_SUBSCRIPTION_ID"),
        ("scripts/setup_github.sh", "GITHUB_REPOSITORY"),
    ],
)
def test_given_missing_environment_when_running_setup_then_fails_explicitly(script, variable):
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("AZURE_SUBSCRIPTION_ID", "GITHUB_REPOSITORY")
    }
    command = [sys.executable if script.endswith(".py") else "bash", str(ROOT / script)]

    result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)

    assert result.returncode != 0
    assert variable in result.stderr
    assert "unexpected external command" not in result.stderr


def test_given_repository_missing_when_configuring_agent_then_fails_before_azure():
    env = {**os.environ, "AZURE_SUBSCRIPTION_ID": "subscription-example"}
    env.pop("GITHUB_REPOSITORY", None)

    result = subprocess.run(
        [sys.executable, str(ROOT / "sre-agent/configure.py")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "GITHUB_REPOSITORY" in result.stderr


def test_given_install_without_date_when_scheduling_lockdown_then_fails_before_changes():
    env = {**os.environ, "AZURE_SUBSCRIPTION_ID": "subscription-example"}

    result = subprocess.run(
        [sys.executable, str(ROOT / "sre-agent/lockdown.py"), "--install"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--at" in result.stderr


def test_given_subscription_when_scheduling_lockdown_then_job_preserves_scope(monkeypatch, tmp_path):
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "subscription-example")
    spec = importlib.util.spec_from_file_location("lockdown", ROOT / "sre-agent/lockdown.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PLIST", tmp_path / "lockdown.plist")
    monkeypatch.setattr(module, "LOG", tmp_path / "lockdown.log")
    monkeypatch.setattr(module, "which", lambda _: "/usr/local/bin/uv")
    monkeypatch.setattr(module, "uid", lambda: "501")
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: None)
    module.install(datetime(2030, 1, 2, 12, 0, tzinfo=UTC))

    job = plistlib.loads(module.PLIST.read_bytes())
    assert job["EnvironmentVariables"]["AZURE_SUBSCRIPTION_ID"] == "subscription-example"


@pytest.mark.parametrize("subscription", ["", "subscription-example"])
def test_given_azure_ml_environment_when_creating_client_then_scope_is_explicit(
    monkeypatch, subscription
):
    sdk = ModuleType("azure.ai.ml")
    sdk.MLClient = lambda *args: args
    monkeypatch.setitem(sys.modules, "azure.ai.ml", sdk)
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", subscription)
    spec = importlib.util.spec_from_file_location("ml_common", ROOT / "ml/azureml/common.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "credential", lambda: "offline-credential")

    if subscription:
        client = module.ml_client()

        assert client[1] == subscription
    else:
        with pytest.raises(SystemExit, match="AZURE_SUBSCRIPTION_ID"):
            module.ml_client()
