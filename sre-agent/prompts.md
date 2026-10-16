# Demo prompts

1. "For vm-app-01, show minute-by-minute anomaly Score, TopFeature and
   Details.groups / Details.contributions (which resource: memory, cpu, disk) and the first bad time."
2. "Investigate the ML alert with vm-anomaly-triage. Propose a temporary
   demo-app.service restart for Review-mode approval, then check health."
3. "Correlate Syslog (deploy and traffic markers), Azure Activity Log,
   DEPLOY_LOG and /version with onset. Inspect app/server.py at the
   deployed ref using Code Access, identify the code path that keeps
   growing, and open an incident GitHub issue using the template and an
   actionable fix plan. Do not deploy an older version."
4. "After I approve the issue and the fix PR merges to main, verify the
   workflow deployment SHA via /version, the affected resource back to baseline and scores below
   0.8 for 10 minutes, and the resolved alert; comment the evidence and
   leave closing the issue to me."
