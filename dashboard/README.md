---
title: Status dashboard
description: Single-view, animated status dashboard for the VM anomaly demonstration
---

## Status dashboard

A full-screen web view of the VM, detector, alerts, SRE Agent, GitHub incident issue,
fix PR and deployment runs. Source links lead to evidence and approval pages.
The dashboard reference describes the data sources and status derivation [1].

---

### Run

Demo mode plays a scripted memory-leak incident and needs no Azure or GitHub access.

```bash
uv run python -m dashboard.server --demo              # 20x speed, loops every 5 min
uv run python -m dashboard.server --demo --speed 1 --start 53   # hold at the restart approval
```

Live mode signs in with the Azure CLI session (`az login`, `az account set` to the demo
subscription) and reads the GitHub token from the environment.

```bash
export DASHBOARD_TENANT_ID="$AZURE_TENANT_ID"
export DASHBOARD_SUBSCRIPTION_ID="$AZURE_SUBSCRIPTION_ID"
export DASHBOARD_REPO="$GITHUB_REPOSITORY"
export GITHUB_TOKEN="$(gh auth token)"
uv run --extra dashboard python -m dashboard.server
```

Open `http://127.0.0.1:8765`. The server binds to localhost only by default.

The bar under the status banner starts the incident without a deploy:
**Inject memory leak** runs `scripts/inject_traffic.sh` (one bulk history
export on `vm-app-01` that archives 60 % of VM memory within seconds) and
**Stop incident** runs `scripts/stop_traffic.sh` (restart `demo-app`), using the Azure CLI session of the dashboard
process. Inject is disabled while the VM is not running. In demo mode the buttons move the
scripted scenario instead.

| Key | Action |
|-----|--------|
| `D` | Toggle director camera; off enables mouse orbit |
| `1`-`4` | Pin the highlighted stage |
| `0` / `Esc` | Remove the pin |

---

### Configuration

Live mode requires `DASHBOARD_TENANT_ID`, `DASHBOARD_SUBSCRIPTION_ID`, and
`DASHBOARD_REPO`; missing values stop startup before polling.
Other defaults match the resources created by `infra/deploy.sh`. Override any field of
`dashboard/config.py` with a `DASHBOARD_<FIELD>` variable.

| Variable | Purpose |
|----------|---------|
| `DASHBOARD_SUBSCRIPTION_ID`, `DASHBOARD_TENANT_ID` | Azure scope and portal tenant |
| `DASHBOARD_REPO` | GitHub repository in `owner/repository` form |
| `DASHBOARD_FUNCTION_APP` | Detector Function App name for its portal link |
| `DASHBOARD_SRE_THREAD_URL_TEMPLATE` | Optional override of the thread link, with `{thread_id}`; the default follows **Copy link to thread** in the SRE Agent portal |
| `DASHBOARD_WINDOW_HOURS` | How far back incident issues and agent threads count (default 6) |
| `GITHUB_TOKEN` | Read access to issues, pull requests and Actions |

The Azure identity needs Reader and Log Analytics Reader on `rg-vm-anomaly-demo` and
**SRE Agent Reader** on `sreagent-vm-anomaly`.

---

### Layout

```text
dashboard/
├── server.py        # CLI, source wiring, HTTP server (/api/snapshot + web/)
├── store.py         # state updates from sources, snapshot reads
├── stage.py         # stage derivation from evidence
├── events.py        # event log from state changes
├── links.py         # deep links and fallbacks
├── queries.py       # KQL shared by polling and links
├── actions.py       # presenter actions (allow-listed scripts)
├── demo.py          # scripted incident
├── sources/         # law.py, arm.py, sre_agent.py, github.py
└── web/             # index.html, main.js, hud.js, scene.js, vendor/three (three.js 0.186.0, MIT)
```

Tests are in `tests/test_dashboard_*.py`.

### References

1. [Status dashboard reference](../docs/09-status-dashboard.md)
