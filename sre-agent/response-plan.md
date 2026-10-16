# VM anomaly incident response plan

Route Azure Monitor alert `alert-ml-anomaly-vm-app-01` (severity 2,
`vm-app-01`) to the `vm-anomaly-triage` skill in **Review** mode.
A SRE Agent Administrator reviews infrastructure writes before execution.
The alert is class-agnostic: the ML score is the maximum over per-resource
detectors (memory, cpu, disk), so the same plan runs for a leak, a runaway
process or a filling disk; the skill's branch table picks the checks.

1. **Triage:** record alert/onset time; run the skill's exact
   `VMAnomalyScore_CL` query and read `Details.groups`, `TopFeature` and
   `Details.contributions` to name the affected resource, then the `Perf`
   query for that resource (keep the others as context). Confirm 3 of 5
   minute scores ≥ 0.8, the counter's trend, service impact.
2. **Interim mitigation:** when the failing unit is `demo-app.service`,
   propose `systemctl restart demo-app.service` through VM run-command;
   explain the interruption and obtain Review approval first. Check
   `/health`, `/stats`, and that the affected counter returns towards
   baseline. Do not call a restart a permanent resolution.
3. **Root cause:** first localise the failing component: the skill's
   `Syslog` severity query names the process (for `demo-app`, the
   WARNING/ERROR `health rss_mb=… cache_entries=… archive_entries=…`
   lines; kernel OOM, disk-full or lockup lines otherwise), then run the
   `Syslog` deploy and traffic-marker queries and the `AzureActivity` query,
   read `/opt/demo-app/DEPLOY_LOG` and `/version` with approval, and
   correlate deploys and traffic changes with anomaly onset. Use Code
   Access to inspect the suspect module at the **deployed ref** and cite the
   file:line that explains the counter's behaviour (demo incident: no
   deploy precedes the onset; a `demo-history-replay` batch requests
   `/report?at=` and `app/server.py` keeps every historical report in the
   unbounded `archive`). Open a GitHub issue from the incident template with label
   `incident`, evidence, fix plan, validation, and rollout. Ask a human to
   review and add `approved` (dispatch to the configured coding agent);
   monitor the resulting fix PR.
4. **Permanent resolution:** after human-reviewed fix PR merge into
   `main` and successful `deploy-app.yml`, verify `/version` matches
   the merged SHA and `/health` is healthy, the affected counter is back
   at its pre-incident level, every score is < 0.8 for 10 minutes, and the
   Azure Monitor alert resolves. Comment on the issue with the
   PR/deployment/metric evidence, or with the missing evidence, and ask
   the approver to close it. **Never close an issue and never merge a pull
   request**: both are human decisions. If the anomaly stopped through
   any other change (manual redeploy, restart, traffic stopped), report
   that the code defect is still unfixed and leave the issue open.

The permanent action is fixing the code and deploying it through the
normal workflow. Review mode, not the Stop hook, gates pre-execution
infrastructure writes (including read-only run-command).
