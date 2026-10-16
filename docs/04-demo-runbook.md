---
title: Demo runbook
description: Trigger, investigate, mitigate, and resolve the sample memory-leak incident
---

## Scenario

The detector, alert and SRE Agent workflow are class-agnostic (memory, CPU, disk); this
runbook walks through the one incident the repo scripts. Where a step is memory-specific,
it is the memory branch of `sre-agent/skills/vm-anomaly-triage/SKILL.md`.

The historical-report traffic triggers a defect already present in the running
application; no deployment is needed to start the incident. Use only the
dedicated demo environment.

## Deploy

```bash
# First configure and load .env using docs/10-environment-setup.md.
az login --tenant "$AZURE_TENANT_ID"
az account set --subscription "$AZURE_SUBSCRIPTION_ID"
infra/deploy.sh            # az deployment of infra/main.bicep: RGs, VM, LAW, DCR/DCE, alerts,
                           # Function shell, roles, SRE Agent, Azure ML workspace + cluster
detector/deploy.sh         # publish function code + model
scripts/status.sh          # app version, last Perf sample, last anomaly score
```

Grant a human the *SRE Agent Administrator* role on `sreagent-vm-anomaly` so that
write actions can be approved in the portal (`infra/deploy.sh --admin <user-object-id>`).

## Alerting

1. Let the VM collect at least 30 minutes of healthy telemetry so the detector
   has a complete feature window. Ingestion and settling add further delay.
2. `scripts/inject_traffic.sh` (or **Inject memory leak** on the status
   dashboard) – makes one bulk export request on the VM,
   `/reports?since=<ts>`, with the window sized to 60 % of the VM's memory
   (`LEAK_PERCENT`). The running `main` build keeps every exported report in
   its unbounded archive (~256 KB each), so memory jumps by that amount
   within seconds; nothing is deployed. A
   repeated export adds almost nothing, which caps the leak. The request is
   logged as `history replay started` in syslog. `scripts/stop_traffic.sh`
   (**Stop incident**) restarts the service and releases the memory.
   `scripts/break.sh <incident-build-ref>` can deploy a separately prepared
   incident variant; no such historical branch is bundled with the sample.
3. Watch `VMAnomalyScore_CL` (`scripts/status.sh` or Log Analytics). Expected:
   score crosses 0.8 within ~10–15 min; `alert-ml-anomaly-vm-app-01` fires.
   `alert-mem-low-vm-app-01` fires much later (only when < 200 MB left) – this
   gap is the point of the ML detector.

   Inspect `Details.groups` to identify memory, CPU, or disk as the leading
   signal. Detection delay depends on the feature window, ingestion, and alert
   evaluation; the synthetic benchmark timing is not a live-service guarantee.

## Interim action

The agent receives the Azure Monitor alert, acknowledges it and follows
`sre-agent/response-plan.md` + skill `vm-anomaly-triage` (memory branch, chosen from `Details.groups`):

- pulls 60 min of memory / swap / CPU from `Perf`, confirms monotonic growth;
- proposes **mitigation**: `systemctl restart demo-app.service` through
  `az vm run-command`; a human approves in **Review mode** before execution.
  The Stop hook checks the final response, not pre-execution tool access.

Chat prompt if you want to drive it manually: see `sre-agent/prompts.md`.

## Root cause analysis

Metrics locate the host and resource (`Computer`, `TopFeature`); the agent
then finds the failing component from that host's logs: the `Syslog`
severity query shows `demo-app` WARNING/ERROR `health rss_mb=… archive_entries=…`
lines whose archive count grows in lock-step with RSS while `cache_entries`
stays flat (kernel OOM lines would appear here too). It then correlates the
onset with `DEPLOY_LOG`, the `Syslog` deploy and `history replay started`
lines, `AzureActivity` run-command and `/version`: no deploy precedes the
onset, the replay batch does. It uses Code Access to read `app/server.py`
**at the deployed ref** and cite `get_historical_report`, which stores every
`/report?at=` result in `archive` without eviction. It creates a
GitHub issue from `.github/ISSUE_TEMPLATE/incident.md` labeled `incident`
and `sre-agent`, including timestamped KQL scores/TopFeature/contributions,
memory trend, deployment evidence, file:line root cause, fix and validation.

## Permanent action

A human reviews the incident issue and approves its fix plan:

```bash
gh issue edit <n> --repo "$GITHUB_REPOSITORY" --add-label approved
```

`incident-approved.yml` dispatches Copilot. Review its fix PR, add the
`deploy` label, and merge it to `main`; `deploy-app.yml` then deploys the
merged SHA. Merges without the `deploy` label, such as documentation or
tooling changes, never deploy. If the workflow
cannot deploy, manually deploy **the merged main code** with `scripts/fix.sh`
(not a different version) and investigate the workflow failure.

After deployment, confirm `/version` contains the merged SHA, `/health`
passes, memory is flat, every minute's Score remains < 0.8 for ten minutes,
and the Azure Monitor alert is resolved. The SRE Agent comments with the
evidence; the approver closes the GitHub issue. The agent never closes issues
or merges pull requests. See
`sre-agent/skills/vm-anomaly-triage/SKILL.md` for exact KQL.

## 5. Horizontal deployment

Fleet-wide rollout is **not implemented**. For a multi-VM incident, identify
hosts running the affected revision, review the rollout with their owners,
deploy the reviewed fix through the fleet's approved deployment process,
and verify each host's revision and recovery.

## 6. Postmortem and standardization

Automated postmortem generation and standardization are **not implemented**.
Use the manual template to record the incident and agree on operational changes.

Use `docs/postmortem-template.md` to record impact, UTC timestamps, approvals,
root cause, and recovery evidence. Include the incident issue, fix PR,
deployment run, and SRE Agent thread.

## Teardown

```bash
infra/teardown.sh   # deletes rg-vm-anomaly-demo and rg-vm-anomaly-ml
```
