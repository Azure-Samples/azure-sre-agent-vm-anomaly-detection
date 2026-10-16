---
name: vm-anomaly-triage
description: Triage ML-detected VM anomalies (memory, CPU, disk, application), localise the failing process from its logs, correlate the deployed code, and track an approved fix through a GitHub issue.
---

# VM anomaly triage

For `alert-ml-anomaly-vm-app-01` on `vm-app-01`, use the Log Analytics
workspace `law-vm-anomaly-demo`. The alert fires when at least three of five
one-minute `VMAnomalyScore_CL` scores reach 0.8. The score is the maximum of
one detector per resource group (`memory`, `cpu`, `disk`), so it fires for
*any* anomaly class; `Details.groups` names the group and `TopFeature` /
`Details.contributions` the feature that drove it. Record timestamps in UTC.

## Stage 2: establish onset, name the resource, mitigate

```kql
VMAnomalyScore_CL
| where TimeGenerated > ago(90m) and Computer =~ "vm-app-01"
| extend d = parse_json(Details)
| project TimeGenerated, Score, IsAnomaly, Model, TopFeature,
          groups=d.groups, metrics=d.metrics, contributions=d.contributions
| order by TimeGenerated asc
```

The first minute with `Score >= 0.8` is the onset. The winning entry of
`groups` selects the branch below; pull the matching `Perf` counters and
keep the other groups as context (a leak can drag swap and CPU with it).

```kql
Perf
| where TimeGenerated > ago(90m) and Computer =~ "vm-app-01"
| where (ObjectName == "Memory")                                          // memory / swap
    or (ObjectName == "Processor" and InstanceName == "_Total")          // cpu
    or (ObjectName == "Logical Disk" and InstanceName == "/")            // disk
    or (ObjectName == "Network")                                          // network
| summarize Value=avg(CounterValue) by bin(TimeGenerated, 1m), ObjectName, CounterName, InstanceName
| order by TimeGenerated asc
```

| `groups` winner / `TopFeature` | what to confirm | guest checks (Review approval first) |
|---|---|---|
| `memory`: `mem_used_pct__slope`, `mem_available_mb__slope`, `swap_used_pct__slope` | steady growth of used memory / swap, falling available MB | `ps -eo pid,rss,comm --sort=-rss \| head`, `/stats`, `journalctl -k -p warning` (OOM) |
| `cpu`: `cpu_pct__min` | `% Processor Time` floor pinned high for the whole window | `top -bn1 \| head -20`, `ps -eo pid,pcpu,comm --sort=-pcpu \| head`, run-queue in `uptime` |
| `disk`: `disk_used_pct__slope` | `% Used Space` on `/` climbing minute by minute | `df -h /`, `du -xsh /var/log /tmp /opt/demo-app 2>/dev/null`, `journalctl -u demo-app --since -1h \| tail` |
| service / application (any group, plus 5xx or `/health` failures) | `/health`, `/version`, `Syslog` errors | `systemctl status demo-app`, `curl localhost:8080/health` |

Explain the brief interruption and request **Review-mode approval before**
run-command (even for read-only guest checks). When the failing unit is
`demo-app.service`, mitigate with a service restart, not a VM restart:

```bash
az vm run-command invoke -g rg-vm-anomaly-demo -n vm-app-01 \
  --command-id RunShellScript \
  --scripts 'sudo systemctl restart demo-app.service && curl -fsS http://localhost:8080/health && curl -fsS http://localhost:8080/stats' \
  --query 'value[0].message' -o tsv
```

Confirm the affected counter returns towards baseline. A restart only buys
time: the still-deployed code will reproduce the anomaly.

## Stage 3: localise the failing component, read its logs, then the code

Metrics only say *which host* and *which resource* (`Computer`,
`groups`, `TopFeature`). Next find *which process/service* on that host is
failing and what it logged. The demo app logs one health line per minute
(`health rss_mb=… cache_entries=…`) and escalates to WARNING/ERROR when its
RSS crosses its budget; the kernel/systemd log OOM kills, restarts and
disk-full errors.

```kql
Syslog
| where TimeGenerated > ago(2h) and Computer =~ "vm-app-01"
| where SeverityLevel in ("warning", "err", "error", "crit", "alert", "emerg")
    or SyslogMessage has_any ("Out of memory", "oom-kill", "Killed process",
                               "Failed with result", "No space left on device",
                               "soft lockup", "hung_task")
| summarize Count=count(), First=min(TimeGenerated), Last=max(TimeGenerated),
            Sample=any(SyslogMessage) by ProcessName, SeverityLevel
| order by Count desc
```

The process whose warnings start at the onset is the suspect. For
`demo-app`, its health line gives the internal counters:

```kql
Syslog
| where TimeGenerated > ago(2h) and Computer =~ "vm-app-01"
| where ProcessName =~ "demo-app"
| parse SyslogMessage with * "rss_mb=" RssMb:real " cache_entries=" Entries:long " cache_bytes_approx=" CacheBytes:long *
| parse SyslogMessage with * "archive_entries=" Archive:long *
| parse SyslogMessage with * "version=" Version
| project TimeGenerated, SeverityLevel, RssMb, Entries, CacheBytes, Archive, Version
| order by TimeGenerated asc
```

Worked example (the scripted demo incident, a memory leak): rising
`Archive` in lock-step with `RssMb` (≈256 KB per entry) while `Entries`
stays at 64 pins the growth to the `demo-app` process and its historical
report archive, and `Version` shows that no new build was deployed. For a CPU or disk anomaly use the same query shape on the
process that `top`/`du` named. If run-command is approved, confirm on the
guest: `systemctl status demo-app`, `journalctl -u demo-app -p warning
--since -2h`, `curl localhost:8080/stats`, plus the branch checks above.

Then find what changed on that system:

```kql
Syslog
| where TimeGenerated > ago(24h) and Computer =~ "vm-app-01"
| where (ProcessName =~ "demo-app" and SyslogMessage contains "deploy")
    or SyslogMessage contains "demo-app deploy"
| project TimeGenerated, ProcessName, SyslogMessage
| order by TimeGenerated desc
```

```kql
AzureActivity
| where TimeGenerated > ago(24h) and ResourceGroup =~ "rg-vm-anomaly-demo"
| where OperationNameValue has "runCommand" or OperationNameValue has "virtualMachines"
| project TimeGenerated, Caller, ResourceId, OperationNameValue, ActivityStatusValue
| order by TimeGenerated desc
```

If approved to invoke run-command, collect the on-VM deploy record and
running version (the deployment also appears in `Syslog`):

```bash
az vm run-command invoke -g rg-vm-anomaly-demo -n vm-app-01 \
  --command-id RunShellScript \
  --scripts 'tail -20 /opt/demo-app/DEPLOY_LOG; curl -fsS http://localhost:8080/version; ps -C python3 -o pid,rss,pcpu,args' \
  --query 'value[0].message' -o tsv
```

Correlate the first sustained anomalous scores and the affected `Perf`
counter with the deployment timestamp and Activity Log caller. `/version`
reports the deployed ref (`<branch>@<sha>`). With Code Access connected to
the GitHub repository specified in the environment context, read the suspect module (for `demo-app`,
`app/server.py`) **at that deployed ref**, then compare with `main`, and
name the change or code path that explains the counter's behaviour. In
the demo incident no deploy precedes the onset: the `Syslog` marker
`history replay started` (`ProcessName == "demo-history-replay"`) does,
and `get_historical_report` in `app/server.py` stores every exported report
(`/reports?since=`, one per second of history) in `archive` without eviction,
so one request added gigabytes within seconds. Cite the deployed commit and file:line; do not infer the cause
solely from a coincident deployment or traffic marker. If no deployment precedes the
onset, say so and treat the cause as environmental (noisy neighbour, cron,
log growth, external traffic) in the issue.

Using the GitHub connector, open an issue in that repository using
`.github/ISSUE_TEMPLATE/incident.md`, with label `incident` (and
`sre-agent`). Include Problem, Impact, timestamped KQL Evidence
(Score/groups/TopFeature/contributions, the affected `Perf` counter,
Syslog, Activity Log, DEPLOY_LOG), Root cause (deployed ref and file:line),
Proposed fix, Validation plan, and Rollout. Request a human review of the
plan and the `approved` label. That label dispatches the selected coding
agent; do not deploy an alternate version as the permanent action.

## Stage 4: verify the merged fix and report

After the fix PR merges to `main`, wait for `deploy-app.yml` to succeed
(it runs only when the merged PR has the `deploy` label; if it was skipped, ask
the approver to deploy). Request Review-mode approval for a
guest `/version` and `/health` check; the returned version must contain
the **merged commit's short SHA**. Check `DEPLOY_LOG` for that SHA.
Observe ten minutes of the affected `Perf` counter with the query above,
and ten minutes of one-minute scores with this query:

```kql
VMAnomalyScore_CL
| where TimeGenerated > ago(10m) and Computer =~ "vm-app-01"
| extend d = parse_json(Details)
| summarize PeakScore=max(Score), Groups=make_bag(d.groups) by bin(TimeGenerated, 1m)
| order by TimeGenerated asc
```

Require the affected counter back at its pre-incident level with a flat
slope, `PeakScore < 0.8` in every observed minute for ten minutes, and the
Azure Monitor alert resolved. If samples are missing or the detector is not
running, report verification as incomplete. Then comment on the GitHub issue
with the PR, deployed SHA, metric evidence and alert status, and ask the
approver to close it. Never close the issue or merge a pull request yourself. Do not restart the VM or change infrastructure
as a substitute for a code fix.
