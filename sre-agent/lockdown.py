"""Keep sreagent-vm-anomaly stopped and scoped to rg-vm-anomaly-demo.

    uv run python sre-agent/lockdown.py            # apply once (exit 3 while the subscription is disabled)
    uv run python sre-agent/lockdown.py --install --at YYYY-MM-DDTHH:MM  # macOS

Applies, idempotently: stop the agent, cap monthly active flow at the minimum 500 AAU, and
replace subscription-wide Monitoring Contributor grants of both agent identities with grants
on rg-vm-anomaly-demo, so the Azure Monitor connection only analyses that resource group.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

log = logging.getLogger("lockdown")
SUBSCRIPTION = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
RG = "rg-vm-anomaly-demo"
AGENT = "sreagent-vm-anomaly"
IDENTITY = "id-sreagent-vm-anomaly"
MONITORING_CONTRIBUTOR = "749f88d5-cbae-40b8-bcfc-e573ddc772fa"
MIN_AAU_LIMIT = 500
ARM = "https://management.azure.com"
AGENT_ID = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RG}/providers/Microsoft.App/agents/{AGENT}"
)
AGENT_URL = f"{ARM}{AGENT_ID}?api-version=2025-05-01-preview"
LABEL = "com.vm-anomaly.sre-agent-lockdown"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG = Path.home() / ".cache" / "vm-anomaly" / "sre-agent-lockdown.log"
EXIT_DISABLED = 3


def az(*args: str) -> str:
    return subprocess.run(
        ["az", *args, "-o", "tsv"], capture_output=True, text=True, check=True
    ).stdout.strip()


def subscription_enabled() -> bool:
    state = az(
        "rest",
        "-m",
        "GET",
        "--url",
        f"{ARM}/subscriptions/{SUBSCRIPTION}?api-version=2022-12-01",
        "--query",
        "state",
    )
    return state == "Enabled"


def stop_agent() -> None:
    power = az("rest", "-m", "GET", "--url", AGENT_URL, "--query", "properties.powerState")
    if power != "Stopped":
        az("rest", "-m", "POST", "--url", AGENT_URL.replace("?", "/stop?"))
        log.info("stopped %s (was %s)", AGENT, power)
    limit = az(
        "rest", "-m", "GET", "--url", AGENT_URL, "--query", "properties.monthlyAgentUnitLimit"
    )
    if limit != str(MIN_AAU_LIMIT):
        body = json.dumps({"properties": {"monthlyAgentUnitLimit": MIN_AAU_LIMIT}})
        az("rest", "-m", "PATCH", "--url", AGENT_URL, "--body", body)
        log.info("monthly active flow limit %s -> %d AAU", limit, MIN_AAU_LIMIT)


def scope_roles_to_rg() -> None:
    principals = {
        IDENTITY: az("identity", "show", "-g", RG, "-n", IDENTITY, "--query", "principalId"),
        f"{AGENT} (system-assigned)": az(
            "resource", "show", "--ids", AGENT_ID, "--query", "identity.principalId"
        ),
    }
    subscription = f"/subscriptions/{SUBSCRIPTION}"
    rg = f"{subscription}/resourceGroups/{RG}"
    for name, principal in principals.items():
        wide = az(
            "role",
            "assignment",
            "list",
            "--assignee",
            principal,
            "--scope",
            subscription,
            "--role",
            MONITORING_CONTRIBUTOR,
            "--query",
            f"[?scope=='{subscription}'].id",
        ).split()
        for assignment in wide:
            az("role", "assignment", "delete", "--ids", assignment)
            log.info("removed subscription-wide Monitoring Contributor from %s", name)
        scoped = az(
            "role",
            "assignment",
            "list",
            "--assignee",
            principal,
            "--scope",
            rg,
            "--role",
            MONITORING_CONTRIBUTOR,
            "--query",
            "[].id",
        )
        if not scoped:
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
                rg,
            )
            log.info("granted Monitoring Contributor on %s to %s", RG, name)


def apply() -> int:
    if not subscription_enabled():
        log.info("subscription is disabled (read only); nothing can be changed yet")
        return EXIT_DISABLED
    stop_agent()
    scope_roles_to_rg()
    return 0


def run_scheduled() -> int:
    """launchd entry: apply once, then remove the job whatever the outcome."""
    try:
        code = apply()
        if code == EXIT_DISABLED:
            log.warning("still disabled; run sre-agent/lockdown.py manually once it is re-enabled")
        return code
    finally:
        uninstall()


def install(at: datetime) -> None:
    script = Path(__file__).resolve()
    uv = which("uv")
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    when = "".join(
        f"<key>{key}</key><integer>{value}</integer>"
        for key, value in (
            ("Month", at.month),
            ("Day", at.day),
            ("Hour", at.hour),
            ("Minute", at.minute),
        )
    )
    PLIST.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>{uv}</string><string>run</string><string>--python</string><string>3.11</string>
    <string>python</string><string>{script}</string><string>--scheduled</string>
  </array>
  <key>WorkingDirectory</key><string>{script.parent.parent}</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:{Path(uv).parent}</string>
    <key>AZURE_SUBSCRIPTION_ID</key><string>{escape(SUBSCRIPTION)}</string>
  </dict>
  <key>StartCalendarInterval</key><dict>{when}</dict>
  <key>StandardOutPath</key><string>{LOG}</string>
  <key>StandardErrorPath</key><string>{LOG}</string>
</dict></plist>
""",
        encoding="utf-8",
    )
    subprocess.run(["launchctl", "bootstrap", f"gui/{uid()}", str(PLIST)], check=True)
    log.info("scheduled one run at %s local time; log: %s", at.strftime("%Y-%m-%d %H:%M"), LOG)


def uninstall() -> None:
    subprocess.run(["launchctl", "bootout", f"gui/{uid()}/{LABEL}"], check=False)
    PLIST.unlink(missing_ok=True)


def which(name: str) -> str:
    return subprocess.run(
        ["which", name], capture_output=True, text=True, check=True
    ).stdout.strip()


def uid() -> str:
    return subprocess.run(["id", "-u"], capture_output=True, text=True, check=True).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--install", action="store_true", help="schedule one run with macOS launchd")
    group.add_argument("--uninstall", action="store_true", help="remove the scheduled run")
    group.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--at",
        type=datetime.fromisoformat,
        help="required with --install: local time of the scheduled run",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.uninstall:
        uninstall()
        return 0
    if not SUBSCRIPTION:
        log.error("Set AZURE_SUBSCRIPTION_ID before managing the SRE Agent")
        return 2
    if args.install and args.at is None:
        parser.error("--install requires --at YYYY-MM-DDTHH:MM")
    if args.install:
        uninstall()
        install(args.at)
        return 0
    az("account", "set", "--subscription", SUBSCRIPTION)
    if args.scheduled:
        return run_scheduled()
    return apply()


if __name__ == "__main__":
    sys.exit(main())
