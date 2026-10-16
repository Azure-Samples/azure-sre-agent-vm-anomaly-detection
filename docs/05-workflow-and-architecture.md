---
title: Workflow and architecture
description: Telemetry paths, incident stages, and human approval boundaries
---

The Azure resources and telemetry paths support alerting, interim action,
root cause analysis, and permanent action.

## System architecture

![System architecture](media/system-architecture.svg)

Service-level view only: system boundaries (GitHub, the application/operations resource
group that is the SRE Agent's RBAC scope, the Azure ML resource group, humans), the Azure
and GitHub services used, their responsibilities and the flows between them. Concrete
resource names, tables and repository paths are in the component table below. Service
icons are the official Azure architecture icons (Microsoft) and the GitHub mark, embedded
inline in the SVG; the Azure logo represents SRE Agent.

## Incident workflow (stages 1-4)

![Incident workflow](media/incident-workflow.svg)

The swimlane describes each step by its purpose and the lane responsible for it; it is
not specific to any anomaly class: the detector scores memory, CPU and disk and the skill
branches on the resource it names. The concrete commands, KQL, thresholds and the
`ReportCache` memory-leak defect used as the scripted demo incident are in the stage
walkthrough below.

The dashed orange arrows between the SRE Agent lane and the VM + Azure Monitor lane (stage 2
triage, stage 3 "Answer the agent's questions") are the agent's investigation access. None of
it is a push channel: the agent pulls from each source on demand, at any point in stages 2-4,
with the managed identity `id-sreagent-vm-anomaly` (Reader, Log Analytics Reader, Monitoring
Reader, Monitoring Contributor, Virtual Machine Contributor on the demo resource group -
`infra/modules/roles.bicep`).

| Source | What the agent gets from it | Read / write | Used in |
|---|---|---|---|
| Azure Monitor / Log Analytics | KQL over `Perf`, `Syslog`, `VMAnomalyScore_CL`, `AzureActivity`; fired-alert list via the Azure Monitor incident connection | read | 1 (alert intake), 2, 3, 4 (verification) |
| Virtual machine | `az vm run-command invoke`: process table, service journal, `/opt/demo-app/DEPLOY_LOG`, `/version`, `/stats`, `systemctl restart` | read and write - every run-command is an infrastructure write and needs Review-mode approval | 2, 3, 4 |
| Azure Resource Graph + Activity Log | resource inventory, configuration and change history of the managed resource group; this is what the agent's knowledge graph is built from (Reader is sufficient for Resource Graph queries) | read | 3 (what changed, when, by whom), 4 |
| GitHub | Code Access: read the source at the deployed revision; GitHub connector: open and update the incident issue; a human closes it | read (code), write (issues) | 3, 4 |

Azure ML training and Function deployment are separate operator tasks; the incident
workflow uses their outputs through the sources above.

## Components

| Component | Azure resource / repo path | Role |
|-----------|----------------------------|------|
| Demo resource group | `rg-vm-anomaly-demo` (eastus2), `infra/main.bicep`, `infra/deploy.sh`, `infra/teardown.sh` | Everything the SRE Agent manages; created and torn down by one script |
| Application VM | `vm-app-01` (Ubuntu, `Standard_D2s_v7`), `infra/modules/vm.bicep`, `infra/modules/network.bicep` | Hosts the demo service and the Azure Monitor Agent |
| Demo service | `demo-app.service` on the VM: `app/server.py`, `app/demo-app.service`, `app/install.sh`, `app/deploy.sh`; `/opt/demo-app` (root-owned), service user `demoapp`, port 8080 | Reporting HTTP service: `/health`, `/version`, `/report`, `/reports`, `/stats`; bounded `ReportCache` and an intentionally unbounded historical-report archive |
| Demo incident (latent leak) | `app/server.py` `get_historical_report`, triggered by `scripts/inject_traffic.sh` | Historical reports (`/report?at=`) are archived without eviction; one bulk export (`/reports?since=`) on the VM adds 60 % of VM memory within seconds without any deploy. `scripts/break.sh <incident-build-ref>` supports a separately prepared deploy-triggered variant |
| Deploy path | `scripts/deploy_app.sh <ref>` -> `az vm run-command` -> `app/deploy.sh <ref> <server.py>` on the VM | Installs `server.py@<sha>`, writes `version.env`, restarts the unit, appends `/opt/demo-app/DEPLOY_LOG` and logs `demo-app deploy <ref>` to syslog |
| Continuous deploy | GitHub Actions `.github/workflows/deploy-app.yml` (on push to `main` touching `app/**` when the merged PR has the `deploy` label, or manual dispatch with a ref) | Runs `scripts/deploy_app.sh <ref>` - the same run-command path - triggered by the merge of the fix PR |
| Approval dispatch | GitHub Actions `.github/workflows/incident-approved.yml` (issue labeled `approved` and carrying `incident`) | Assigns Copilot so the coding agent starts the fix PR |
| Telemetry | Azure Monitor Agent + DCR `dcr-vm-perf`, `infra/modules/monitoring.bicep` | Guest `Perf` counters (memory, swap, CPU, disk, network; 60 s) and `Syslog` (daemon/syslog/user) into Log Analytics |
| Log Analytics | `law-vm-anomaly-demo`; tables `Perf`, `Syslog`, `AzureActivity`, custom `VMAnomalyScore_CL`; DCE `dce-vm-anomaly` + DCR `dcr-vm-anomaly-scores` | Single query surface for the detector, the alert rules and the SRE Agent |
| Detector | Azure Functions `func-vm-anomaly-*` (Python, timer every minute): `detector/function_app.py`, `cycle.py`, `law.py`, `features.py` (vendored from `ml/features.py`), `scorer.py`, `model/`, `detector/deploy.sh` | Reads 60 min of `Perf`, pivots to the six live metrics, builds rolling features, scores with one calibrated IsolationForest per resource group (memory / cpu / disk, `Score = max`), uploads new bins to `VMAnomalyScore_CL` (`Score`, `IsAnomaly`, `TopFeature`, `Details{metrics, contributions, groups}`) |
| Alert rules | `alert-ml-anomaly-vm-app-01` (scheduled query: `IsAnomaly` in >= 3 of the last 5 minutes), `alert-mem-low-vm-app-01` (memory-only static safety net: Available Memory < 200 MB), action group `ag-vm-anomaly` | Turn scores of any anomaly class into an Azure Monitor alert that reaches the SRE Agent |
| SRE Agent | `sreagent-vm-anomaly` (`Microsoft.App/agents`, Review mode), managed identity `id-sreagent-vm-anomaly`, `infra/modules/sre-agent.bicep`, `infra/modules/roles.bicep`; `sre-agent/response-plan.md`, `sre-agent/skills/vm-anomaly-triage/SKILL.md`, `sre-agent/hooks/vm-remediation-approval.yaml`, `sre-agent/prompts.md` | Triage, mitigation proposal, RCA, GitHub issue, verification and close-out |
| ML resource group | `rg-vm-anomaly-ml`, Azure ML workspace `mlw-vm-anomaly`; `ml/train.py`, `ml/evaluate.py`, `ml/features.py`, `ml/models/`, `ml/data/`, `ml/azureml/{job.yaml,env.yaml,submit.py,register.py,export.py}`, `ml/REPORT.md` | Trains the shipped model on synthetic anomaly-free live-metric VM series and evaluates it on injected leaks / CPU saturation / disk fills; benchmarks the model family on SMD (28 machines x 38 metrics) and NAB; registers `vm-anomaly-detector`, exports `model.pkl` + `metadata.json` (calibration, `feature_stats`) into `detector/model/` |
| GitHub repository | Configured through `GITHUB_REPOSITORY`; labels `incident`, `approved`; coding agent (Copilot) | Incident record, approval boundary and fix delivery (issue -> PR -> merge -> deploy) |
| Operator tooling | `scripts/inject_traffic.sh`, `scripts/stop_traffic.sh`, `scripts/break.sh`, `scripts/mitigate.sh`, `scripts/fix.sh`, `scripts/status.sh` | Trigger and reset the demo incident, manual fallbacks for stages 2 and 4, snapshot of version / `Perf` / scores |

## Data flow: how VM telemetry reaches the SRE Agent

Short version:

- VM logs and metrics are **not** sent to the SRE Agent, to Azure ML or to the Azure
  Function. The only intermediary is Log Analytics (`law-vm-anomaly-demo`).
- The Azure Function **polls** Log Analytics (`Perf`), scores locally with the model
  artifact shipped in the Function package, and **writes the scores back** to Log Analytics
  (`VMAnomalyScore_CL`). There is no ML integration inside Azure Monitor and no Azure ML
  online endpoint; Azure ML is offline training only.
- Azure Monitor evaluates the score table with a scheduled query and fires an alert.
- The SRE Agent picks up the alert and then queries Log Analytics **on demand** with KQL;
  it touches the VM only through approved `run-command` calls.

```text
VM (vm-app-01) --AMA--> DCR dcr-vm-perf --> Log Analytics law-vm-anomaly-demo
                                             | Perf  | Syslog | AzureActivity | VMAnomalyScore_CL
        Logs Query API (Perf, last 60 min)   ^                        ^          ^
Azure Function detector (timer, every 1 min) |                        |          |
        model.pkl + metadata.json (local)    v                        |          |
        Logs Ingestion API -> DCE dce-vm-anomaly -> DCR dcr-vm-anomaly-scores --'          |
                                                                                            |
Azure Monitor scheduled query (PT1M / PT5M, AnomalyMinutes >= 3) -> alert -> ag-vm-anomaly |
        SRE Agent Azure Monitor connection scans fired alerts every minute                   |
SRE Agent (Review mode) --on-demand KQL--> Log Analytics --------------------------------------'
                        --approved run-command--> VM        --Code Access--> GitHub source
```

### A. VM telemetry (metrics + logs)

1. **VM produces data.** Linux performance counters, syslog (including
   `demo-app` health lines from `app/server.py` and the deploy marker `logger -t demo-app
   "deploy <ref> by <user>"` written by `app/deploy.sh` together with
   `/opt/demo-app/DEPLOY_LOG`). The VM calls none of the downstream services.
2. **Azure Monitor Agent collects.** AMA runs as a VM extension bound by a Data Collection
   Rule association (`infra/modules/monitoring.bicep`). `dcr-vm-perf` collects the
   six guest counters every 60 s (`Memory\% Used Memory`, `Memory\Available MBytes Memory`,
   `Memory\% Used Swap Space`, `Processor(*)\% Processor Time`, `Logical Disk(*)\% Used
   Space`, `Network(*)\Total Bytes`; `monitoring.bicep`) and syslog facilities
   `daemon`, `syslog`, `user` at Info and above (`monitoring.bicep`).
3. **DCR delivers to Log Analytics.** Streams `Microsoft-Perf` and `Microsoft-Syslog` go to
   the single workspace destination (`monitoring.bicep`), landing in the `Perf` and
   `Syslog` tables. Azure control-plane operations (deployments, run-command, restarts)
   arrive separately through the subscription Activity Log diagnostic setting (`infra/main.bicep`) as `AzureActivity`.

   *Bypassed at this point:* Azure ML, the Azure Function, the SRE Agent, GitHub and the
   deploy workflow. Telemetry moves only VM -> AMA -> DCR -> Log Analytics.

### B. ML scoring

4. **Timer trigger.** The detector is an Azure Functions timer function on
   `0 * * * * *` (every minute; `detector/function_app.py`). Azure Monitor does not
   invoke the model; the schedule is the only trigger.
5. **Function polls Log Analytics.** `run_cycle` (`detector/cycle.py`) creates an
   `azure.monitor.query.LogsQueryClient` with the Function's managed identity (role: Log
   Analytics Reader, `infra/modules/roles.bicep`) and runs the `Perf` KQL in
   `detector/law.py` over `LOOKBACK_MINUTES` (default 60) for `TARGET_COMPUTER`.
   `pivot_perf` (`law.py`) bins rows to one minute, aggregates the per-instance
   CPU/disk/network counters, forward-fills gaps and yields the six model metrics.
6. **Local model inference.** `score_frame` loads `detector/model/model.pkl` +
   `metadata.json` (SHA-256 checked, `detector/scorer.py`), applies the same
   `make_features` as training and produces `Score`, `IsAnomaly` (score >= 0.8),
   `TopFeature` and `Details{metrics, contributions}`.
7. **Write-back through the Logs Ingestion API.** Only bins older than `SETTLE_MINUTES`
   (2) and newer than the last uploaded bin are sent (`cycle.py`) via
   `azure.monitor.ingestion.LogsIngestionClient` -> Data Collection Endpoint
   `dce-vm-anomaly` -> DCR `dcr-vm-anomaly-scores` (stream
   `Custom-VMAnomalyScore_CL`, `monitoring.bicep`) -> table `VMAnomalyScore_CL`
   (table `monitoring.bicep`). Role: Monitoring Metrics Publisher on the DCR.

   *Bypassed by scoring:* the SRE Agent, Azure Monitor alert evaluation, Azure ML (used
   only offline to produce the artifact), GitHub, VM run-command. The Function reads
   `Perf`, scores locally, writes `VMAnomalyScore_CL`; nothing else.

### C. Alert evaluation

8. **Scheduled query rule** `alert-ml-anomaly-vm-app-01` (`monitoring.bicep`):
   `evaluationFrequency: PT1M`, `windowSize: PT5M`, query
   `VMAnomalyScore_CL | where Computer =~ "vm-app-01" and IsAnomaly | summarize count() by bin(TimeGenerated, 1m) | summarize AnomalyMinutes=count()`,
   fires when `AnomalyMinutes >= 3` (three anomalous one-minute bins in the last five).
   The memory-only safety net `alert-mem-low-vm-app-01` (`monitoring.bicep`) evaluates
   `Perf` directly (`Available MBytes Memory` avg < 200 over 5 min) on the same schedule.
   Both attach action group `ag-vm-anomaly` (`monitoring.bicep`).

### D. SRE Agent

9. **Alert routing.** `ag-vm-anomaly` has no receivers (`monitoring.bicep`). The
   agent does not receive a push: its **Azure Monitor incident-platform connection** scans
   fired alerts in the managed resource group every minute
   (`sre-agent/README.md`), and the incident response plan matches severity 2 /
   title `alert-ml-anomaly-vm-app-01` and routes it to the `vm-anomaly-triage` skill in
   Review mode (`sre-agent/README.md`, `sre-agent/response-plan.md`). Without
   that portal configuration the alert fires in Azure Monitor but no agent conversation
   starts.
10. **On-demand KQL.** The agent receives the alert, not the logs. With its managed
    identity (`id-sreagent-vm-anomaly`: Reader, Log Analytics Reader, Monitoring
    Reader/Contributor, Virtual Machine Contributor scoped to `rg-vm-anomaly-demo`,
    `infra/modules/roles.bicep`) it queries `VMAnomalyScore_CL`, `Perf`, `Syslog`
    and `AzureActivity` around the alert timestamp (`sre-agent/response-plan.md`,
    queries in `sre-agent/skills/vm-anomaly-triage/SKILL.md`).
11. **VM access only when needed.** Process state, `/version`, `/stats`,
    `/opt/demo-app/DEPLOY_LOG` and the restart are `az vm run-command invoke` calls
    (`SKILL.md`); each requires Review-mode approval, including read-only ones. This
    is a control-plane operation, not a log channel.
12. **Source access.** Root cause uses the GitHub Code Access connector to read
    `app/server.py` at the deployed ref (`response-plan.md`); the repo is never in
    the telemetry path.

### Bypass summary

| Path | Hops | Never touches |
|---|---|---|
| Metrics | VM `Perf` -> AMA -> `dcr-vm-perf` -> LAW `Perf` -> Function query -> local model -> DCE -> `dcr-vm-anomaly-scores` -> LAW `VMAnomalyScore_CL` -> scheduled query -> alert -> agent connection scan -> agent KQL | Azure ML online, SRE Agent (until alert), GitHub |
| Syslog | VM syslog -> AMA -> `dcr-vm-perf` -> LAW `Syslog` -> agent KQL after the incident | Function, model, `VMAnomalyScore_CL`, Azure ML |
| Deployment / RCA | `deploy.sh` -> `DEPLOY_LOG` + syslog marker; Azure ops -> `AzureActivity`; agent correlates timestamps -> Code Access reads source | Function, model, alert rules |

The agent uses metrics for detection, logs and deployment records for RCA, and approved
VM / GitHub operations for remediation.

Measured model comparisons are in `docs/06-modeling-alternatives.md`.

## Stage-by-stage walkthrough

Commands and KQL below are the ones used in `docs/04-demo-runbook.md` and
`sre-agent/skills/vm-anomaly-triage/SKILL.md`; follow the runbook for the full text.
Numbers refer to the arrows in the workflow diagram.

### Stage 1 - Alerting (arrows 1-5)

1. The demo incident is triggered without a deploy: `scripts/inject_traffic.sh`
   uses run-command to make one bulk export request, `/reports?since=<ts>`, sized to
   60 % of the VM's memory, and logs `history replay started`. The running build
   archives every exported report without eviction, so memory jumps within seconds. (Variant: `scripts/break.sh <incident-build-ref>` deploys a separately prepared incident build
   through `app/deploy.sh`, which writes `DEPLOY_LOG` and the syslog marker
   `demo-app deploy <ref>`.)
2. AMA ships `Perf` and `Syslog` to `law-vm-anomaly-demo` every 60 s.
3. The detector timer (`detector/function_app.py::score_vm`, `0 * * * * *`) runs
   `cycle.run_cycle`: `law.fetch_perf` (last 60 min) -> `law.pivot_perf` (six metrics) ->
   `features.make_features(window=30)` -> `scorer.Scorer.score` (one IsolationForest per
   resource group, each calibrated so that 0.8 = 99.9th percentile of normal training
   windows; `Score` is the maximum and `Details.groups` names the resource).
4. New 1-minute bins are uploaded through the Logs Ingestion API into
   `VMAnomalyScore_CL`. The scheduled-query alert evaluates every minute:

   ```kql
   VMAnomalyScore_CL | where IsAnomaly | summarize count() by bin(TimeGenerated, 1m) | summarize AnomalyMinutes=count()
   ```

   and fires when `AnomalyMinutes >= 3` over the 5-minute window. The static
   `alert-mem-low-vm-app-01` is kept as the memory-only safety net that fires much later.
5. The SRE Agent Azure Monitor incident connection discovers the fired alert;
   `ag-vm-anomaly` has no delivery receivers. The agent records the first anomalous
   timestamp and starts triage.
   Operator check at any time: `scripts/status.sh`.

### Stage 2 - Interim action (arrows 6-7)

- Triage with the `vm-anomaly-triage` skill: the `VMAnomalyScore_CL` query names the
  resource (`Details.groups`, `TopFeature`), then the matching `Perf` queries from the skill's
  branch table (memory / swap in the demo incident), run as
  `az monitor log-analytics query -w "$LAW_ID" -t PT90M --analytics-query '<KQL>' -o table`,
  plus process RSS and `/stats` (cache entries, approximate bytes, hit ratio).
- The agent proposes `systemctl restart demo-app.service` (not the VM), explains the
  brief interruption, and waits for Review-mode approval (arrow 6).
- After approval (arrow 7) it runs

  ```bash
  az vm run-command invoke -g rg-vm-anomaly-demo -n vm-app-01 --command-id RunShellScript \
    --scripts 'sudo systemctl restart demo-app.service; curl -fsS http://localhost:8080/health' \
    --query 'value[0].message' -o tsv
  ```

  (manual fallback: `scripts/mitigate.sh`). The affected counter recovers (memory is freed in
  the demo incident), and `/health` succeeds. The defect is still deployed:
  another historical export can reproduce the incident after the restart.

### Stage 3 - Root cause analysis (arrows 8-9)

- Localise the failing component. The metric score names the host and the resource
  (`Computer`, `TopFeature`); the agent then reads that host's logs: `Syslog` WARNING/ERROR
  grouped by `ProcessName` shows `demo-app` health lines (`rss_mb=… archive_entries=…`) whose
  archive count grows with RSS, plus any kernel OOM lines; on the guest (approved run-command)
  `journalctl -u demo-app -p warning`, `/stats` and `ps` RSS confirm the process.
- Correlate the onset with deployment and traffic markers: the `Syslog` queries
  (`SyslogMessage has "demo-app deploy"`, `ProcessName == "demo-history-replay"`), the `AzureActivity` run-command query from the
  skill, and `cat /opt/demo-app/DEPLOY_LOG; curl -fsS http://localhost:8080/version`
  through run-command (also an approved write).
- Code Access (read) opens `app/server.py` at the deployed sha and pinpoints
  `get_historical_report`: every `/report?at=` result is stored in `archive` and never
  evicted, so the bulk export adds a 256 KB report per exported second.
- The agent opens a GitHub issue with label `incident` containing: problem statement,
  evidence (KQL results, deploy and traffic markers, RSS), root cause `app/server.py` file:line,
  fix plan (bound the archive, for example with the existing `ReportCache` LRU), validation plan (`/version` reports
  the fixed sha, affected counter back at baseline, `Score < 0.8`, alert resolved).

### Stage 4 - Permanent action (arrows 10-16)

- A human reviews the issue and adds the label
  `approved` (arrow 11). `incident-approved.yml` reacts to that label and dispatches the
  coding agent (Copilot).
- The coding agent implements the bounded cache in `app/server.py`, adds a test and opens a
  PR referencing the issue (arrow 12). The PR is reviewed and merged to `main`.
- The reviewer adds the `deploy` label before merging; `deploy-app.yml` runs on the push to
  `main` touching `app/`, confirms the label on the merged PR, and deploys
  `app/server.py@<sha>` via `az vm run-command` (arrow 13) - the same path as
  `scripts/deploy_app.sh <ref>`; `scripts/fix.sh` (`deploy_app.sh origin/main`) is the manual
  fallback.
- Verification by the SRE Agent: `/version` returns the merged sha,
  the affected `Perf` counter is back at baseline for ten minutes, `VMAnomalyScore_CL` scores
  stay below 0.8 (the one-sided features do not alert on the *drop* after a fix), the alert
  resolves.
  The agent comments the evidence, approvals and timestamps on the issue, and the
  approver closes it (arrow 16). The response instructions prohibit the agent from
  closing issues or merging PRs.

### Stages 5-6

Horizontal deployment applies the reviewed fix to other affected hosts.
Postmortem and standardization record the incident and improve operating
practices. Neither stage is implemented as automation; the runbook describes
manual follow-up and provides a postmortem template.

## Governance model

- **Review mode is the pre-execution gate.** `sreagent-vm-anomaly` runs with
  `actionConfiguration.mode=Review`; every Azure infrastructure write - including every
  `az vm run-command` invocation, even when it only reads files on the VM - must be approved
  by a human holding **SRE Agent Administrator** on the agent resource
  (`infra/deploy.sh --admin <user-object-id>`). Never switch the agent to Autonomous for the demo.
- **RBAC scope.** The agent acts through `id-sreagent-vm-anomaly`, whose roles (Reader,
  Log Analytics Reader, Monitoring Reader, Monitoring Contributor, Virtual Machine Contributor)
  are assigned on `rg-vm-anomaly-demo` only (`infra/modules/roles.bicep`); the ML resource
  group and the rest of the subscription are out of reach. The detector identity has only
  Log Analytics Reader on the workspace and Monitoring Metrics Publisher on the scores DCR.
- **Labels as the code-change approval boundary.** The agent may open issues (label
  `incident`) but does not change code. Only the label `approved`, added by a human,
  lets the coding agent open a PR; the PR still goes
  through normal review and branch protection before `deploy-app.yml` deploys it.
- **Hooks are post-execution only.** `sre-agent/hooks/vm-remediation-approval.yaml` is a
  `Stop` prompt hook: it checks that the agent's final response states the required approvals
  and rejects responses claiming an unapproved write. Documented hook events (`Stop`,
  `PostToolUse`) cannot block a command before it runs, so the hook is an audit control,
  not the approval gate - Review mode is.
- **Independent approval boundaries.** Review-mode approval gates infrastructure
  actions; the `approved` issue label dispatches the coding agent. Human PR review,
  the `deploy` label, and merge authorize delivery of the fix. A human closes the
  incident after reviewing recovery evidence.

## How the repository directories map to the diagrams

| Directory | Diagram element |
|-----------|-----------------|
| `infra/` | Azure resource groups, VM, monitoring, Function host, SRE Agent, identities, and roles |
| `app/` | Demo web service inside the VM; `deploy.sh` installs the selected source revision |
| `scripts/` | Developer / Deploy lane (`break.sh`, `deploy_app.sh`), manual fallbacks (`mitigate.sh`, `fix.sh`) and the operator's `status.sh` |
| `detector/` | "Azure Functions" box and the Detector lane (workflow arrows 3-4 and 14) |
| `ml/` | "Azure Machine Learning" resource-group boundary; the dashed "exported model artifact" flow into the repository (`detector/model/`) - see `docs/07-modeling-and-evaluation.md` |
| `sre-agent/` | Orange SRE Agent box and lane: response plan (stage order), skill (KQL and run-command procedures), hook (post-execution check), prompts |
| `.github/workflows/` | "GitHub Actions" box: `deploy-app.yml` (workflow arrow 13) and `incident-approved.yml` (label trigger behind arrows 11-12) |
| `docs/` | Architecture, runbook, model evaluation, and manual postmortem template |
| `tests/` | Not drawn; offline tests that keep `detector/features.py` in sync with `ml/features.py` and the detector output schema stable |
