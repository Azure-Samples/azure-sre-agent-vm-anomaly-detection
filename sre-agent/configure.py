"""Configure sreagent-vm-anomaly through its data plane (replaces the portal steps).

    uv run python sre-agent/configure.py            # apply all settings, print GitHub sign-in link
    uv run python sre-agent/configure.py --wait-github 600   # also wait for OAuth, then add Code Access

Applies: Monitoring Contributor on rg-vm-anomaly-demo for the Azure Monitor connection, the vm-anomaly-triage
skill, a custom agent with the response plan and the approval Stop hook, a Review-mode
incident response plan for the ML alert, GitHub OAuth, and the repository for Code Access.
Tokens come from the Azure CLI session and are never printed or passed as arguments.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

log = logging.getLogger("configure")
HERE = Path(__file__).parent
SUBSCRIPTION = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
RG = "rg-vm-anomaly-demo"
AGENT = "sreagent-vm-anomaly"
IDENTITY = "id-sreagent-vm-anomaly"
WORKSPACE = "law-vm-anomaly-demo"
REPO = os.environ.get("GITHUB_REPOSITORY", "").strip()
ALERT_RULE = "alert-ml-anomaly-vm-app-01"
ALERT_TITLE = "ML VM anomaly on vm-app-01"
SKILL = "vm-anomaly-triage"
CUSTOM_AGENT = "vm-anomaly-responder"
PLAN = "vm-anomaly-ml-alert"
MONITORING_CONTRIBUTOR = "749f88d5-cbae-40b8-bcfc-e573ddc772fa"
ARM_VERSION = "2025-05-01-preview"
# No UpdateGithubIssue: closing an incident issue is left to a human.
TOOLS = [
    "SearchMemory",
    "RunAzCliReadCommands",
    "RunAzCliWriteCommands",
    "GetAzCliHelp",
    "QueryLogAnalyticsByWorkspaceId",
    "CreateGithubIssue",
    "CreateGithubIssueComment",
    "FetchGithubIssue",
    "FetchGithubIssues",
    "FetchGithubIssueComments",
    "FindConnectedGitHubRepo",
]


def az(*args: str) -> str:
    return subprocess.run(
        ["az", *args, "-o", "tsv"], capture_output=True, text=True, check=True
    ).stdout.strip()


class DataPlane:
    def __init__(self, endpoint: str) -> None:
        self._endpoint = endpoint.rstrip("/")

    def call(self, method: str, path: str, body: object | None = None) -> object:
        token = az(
            "account",
            "get-access-token",
            "--resource",
            "https://azuresre.dev",
            "--query",
            "accessToken",
        )
        data = None if body is None else json.dumps(body).encode()
        request = Request(f"{self._endpoint}{path}", data=data, method=method)
        request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Content-Type", "application/json")
        with urlopen(request, timeout=60) as response:
            raw = response.read()
        return json.loads(raw) if raw.strip() else {}

    def put(self, path: str, body: object, attempts: int = 1) -> None:
        for attempt in range(1, attempts + 1):
            try:
                self.call("PUT", path, body)
                log.info("PUT %s ok", path)
                return
            except HTTPError as error:
                detail = error.read().decode(errors="replace")[:300]
                if attempt == attempts:
                    raise RuntimeError(f"PUT {path} failed: {error.code} {detail}") from error
                log.info("PUT %s -> %s, retrying (%s)", path, error.code, detail[:120])
                time.sleep(20)


def hook_prompt() -> str:
    lines = (
        (HERE / "hooks" / "vm-remediation-approval.yaml").read_text(encoding="utf-8").splitlines()
    )
    start = next(i for i, line in enumerate(lines) if line.strip() == "prompt: |") + 1
    return "\n".join(line.strip() for line in lines[start:] if line.startswith("    ")).strip()


def skill_description(content: str) -> str:
    for line in content.splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return "Triage VM anomaly alerts from VMAnomalyScore_CL"


def grant_monitoring_contributor(agent_id: str) -> None:
    """The Azure Monitor connection reads fired alerts; scope it to the demo resource group
    so the agent does not analyse (and bill for) alerts of unrelated workloads."""
    principals = {
        IDENTITY: az("identity", "show", "-g", RG, "-n", IDENTITY, "--query", "principalId"),
        f"{AGENT} (system-assigned)": az(
            "resource", "show", "--ids", agent_id, "--query", "identity.principalId"
        ),
    }
    scope = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RG}"
    for name, principal in principals.items():
        existing = az(
            "role",
            "assignment",
            "list",
            "--assignee",
            principal,
            "--scope",
            scope,
            "--role",
            MONITORING_CONTRIBUTOR,
            "--query",
            "[].id",
        )
        if existing:
            log.info("Monitoring Contributor already assigned on %s to %s", RG, name)
            continue
        az(
            "role",
            "assignment",
            "create",
            "--assignee-object-id",
            principal,
            "--assignee-principal-type",
            "ServicePrincipal",
            "--role",
            MONITORING_CONTRIBUTOR,
            "--scope",
            scope,
        )
        log.info("granted Monitoring Contributor on %s to %s", RG, name)


def configure(plane: DataPlane, workspace_id: str) -> None:
    skill = (HERE / "skills" / SKILL / "SKILL.md").read_text(encoding="utf-8")
    plane.put(
        f"/api/v2/extendedAgent/skills/{SKILL}",
        {
            "name": SKILL,
            "type": "Skill",
            "tags": [],
            "properties": {
                "name": SKILL,
                "description": skill_description(skill),
                "tools": [],
                "skillContent": skill,
                "additionalFiles": [],
            },
        },
    )
    context = (
        f"Environment: subscription {SUBSCRIPTION}, resource group {RG}, VM vm-app-01, "
        f"Log Analytics workspace {WORKSPACE} (workspace ID {workspace_id}), "
        f"GitHub repository {REPO}.\n\n"
    )
    plan = (HERE / "response-plan.md").read_text(encoding="utf-8")
    plane.put(
        f"/api/v2/extendedAgent/agents/{CUSTOM_AGENT}",
        {
            "name": CUSTOM_AGENT,
            "type": "ExtendedAgent",
            "tags": [],
            "owner": "",
            "properties": {
                "instructions": context + plan,
                "handoffDescription": "Triages VM anomaly alerts, mitigates with approval, finds the root cause, and drives the GitHub fix.",
                "handoffs": [],
                "tools": TOOLS,
                "mcpTools": [],
                "allowParallelToolCalls": True,
                "agentType": "Autonomous",
                "temperature": 0.2,
                "enableSkills": True,
                "allowedSkills": [SKILL],
                "hooks": {"Stop": [{"type": "prompt", "prompt": hook_prompt(), "timeout": 30}]},
            },
        },
    )
    plane.put(
        f"/api/v2/extendedAgent/incidentFilters/{PLAN}",
        {
            "name": PLAN,
            "type": "IncidentFilter",
            "tags": [],
            "properties": {
                "incidentPlatform": "AzMonitor",
                "priorities": ["Sev0", "Sev1", "Sev2"],
                "titleContains": "",
                "titleContainsAll": [],
                "titleContainsAny": [ALERT_RULE, ALERT_TITLE],
                "titleNotContains": [],
                "handlingAgent": CUSTOM_AGENT,
                "agentMode": "Review",
                "maxAutomatedInvestigationAttempts": 3,
                "mergeEnabled": True,
                "mergeWindowHours": 3,
                "isEnabled": True,
            },
        },
        attempts=5,
    )
    try:
        plane.call("DELETE", "/api/v1/incidentPlayground/filters/quickstart_response_plan")
        log.info("removed the default quickstart response plan")
    except HTTPError as error:
        log.info("no quickstart response plan to remove (%s)", error.code)


def github_connected(plane: DataPlane) -> bool:
    domains = plane.call("GET", "/api/v2/github/domains")
    values = domains.get("values") or domains.get("value") if isinstance(domains, dict) else domains
    return bool(values)


def connect_github(plane: DataPlane, wait_s: int) -> bool:
    if not github_connected(plane):
        config = plane.call("GET", "/api/v2/github/oauth/config")
        url = config.get("oAuthUrl") if isinstance(config, dict) else None
        print(f"\nAuthorize GitHub for the SRE Agent by opening:\n  {url}\n", flush=True)
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline and not github_connected(plane):
            time.sleep(10)
        if not github_connected(plane):
            log.warning("GitHub is not connected yet; rerun with --wait-github after signing in")
            return False
    log.info("GitHub connected")
    plane.put(
        f"/api/v2/repos/{quote(REPO.split('/')[1], safe='')}",
        {
            "name": REPO.split("/")[1],
            "type": "CodeRepo",
            "properties": {
                "url": f"https://github.com/{REPO}",
                "type": "GitHub",
                "branch": "main",
                "description": "Demo app, detector and incident workflows",
            },
        },
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--wait-github", type=int, default=0, help="seconds to wait for GitHub OAuth"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not SUBSCRIPTION or not REPO:
        log.error("Set AZURE_SUBSCRIPTION_ID and GITHUB_REPOSITORY (owner/repository)")
        return 2
    if len(REPO.split("/")) != 2 or not all(REPO.split("/")):
        log.error("GITHUB_REPOSITORY must use owner/repository format")
        return 2
    az("account", "set", "--subscription", SUBSCRIPTION)
    agent_id = (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RG}/providers/Microsoft.App/agents/{AGENT}"
    )
    endpoint = az(
        "rest",
        "-m",
        "GET",
        "--url",
        f"https://management.azure.com{agent_id}?api-version={ARM_VERSION}",
        "--query",
        "properties.agentEndpoint",
    )
    workspace_id = az(
        "monitor",
        "log-analytics",
        "workspace",
        "show",
        "-g",
        RG,
        "-n",
        WORKSPACE,
        "--query",
        "customerId",
    )
    plane = DataPlane(endpoint)
    grant_monitoring_contributor(agent_id)
    configure(plane, workspace_id)
    return 0 if connect_github(plane, args.wait_github) else 1


if __name__ == "__main__":
    sys.exit(main())
