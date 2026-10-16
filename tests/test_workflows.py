from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def workflows() -> dict[str, dict]:
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    assert {path.name for path in files} >= {"deploy-app.yml", "incident-approved.yml"}
    # BaseLoader preserves the key "on" (YAML 1.1 SafeLoader reads it as True).
    return {path.name: yaml.load(path.read_text(), Loader=yaml.BaseLoader) for path in files}


def test_every_workflow_parses():
    for name, workflow in workflows().items():
        assert isinstance(workflow, dict), name
        assert isinstance(workflow["on"], dict), name
        assert isinstance(workflow["jobs"], dict), name


def test_deploy_app_triggers_and_version_check():
    deploy = workflows()["deploy-app.yml"]
    assert deploy["on"]["push"] == {"branches": ["main"], "paths": ["app/**"]}
    assert deploy["on"]["workflow_dispatch"]["inputs"]["ref"]["required"] == "true"
    assert deploy["permissions"]["id-token"] == "write"
    steps = deploy["jobs"]["deploy"]["steps"]
    assert any(step.get("uses", "").startswith("azure/login@") for step in steps)
    command = steps[-1]["run"]
    assert "scripts/deploy_app.sh" in command
    assert '"version"' in command and '*"$sha\\""' in command
    assert "github.sha" in steps[-1]["env"]["DEPLOY_REF"]


def test_deploy_app_runs_only_when_merge_is_labeled_deploy_or_manual():
    deploy = workflows()["deploy-app.yml"]
    gate = deploy["jobs"]["gate"]
    check = gate["steps"][0]["run"]
    assert deploy["permissions"]["pull-requests"] == "read"
    assert "commits/$GITHUB_SHA/pulls" in check and ",deploy," in check
    assert "workflow_dispatch" in check
    assert deploy["jobs"]["deploy"]["needs"] == "gate"
    assert deploy["jobs"]["deploy"]["if"] == "needs.gate.outputs.deploy == 'true'"


def test_approved_incident_dispatch_trigger():
    incident = workflows()["incident-approved.yml"]
    assert incident["on"]["issues"]["types"] == ["labeled"]
    job = incident["jobs"]["dispatch"]
    assert "github.event.label.name == 'approved'" in job["if"]
    assert "contains(github.event.issue.labels.*.name, 'incident')" in job["if"]
    assert "CODING_AGENT" not in job["env"]
    command = job["steps"][0]["run"]
    assert "copilot-swe-agent[bot]" in command
    assert "Approved by @$APPROVER — dispatched to Copilot." in command
    assert "deploy\\` label to the fix PR before merging" in command
