#!/usr/bin/env bash
set -euo pipefail
workspace="$(az monitor log-analytics workspace show -g rg-vm-anomaly-demo \
  -n law-vm-anomaly-demo --query customerId -o tsv)"
echo 'VM version, app stats, last deploys, process RSS:'
az vm run-command invoke -g rg-vm-anomaly-demo -n vm-app-01 \
  --command-id RunShellScript \
  --scripts 'curl -fsS http://localhost:8080/version; echo; curl -fsS http://localhost:8080/stats; echo; tail -3 /opt/demo-app/DEPLOY_LOG; ps -C python3 -o pid,rss,args' \
  --query 'value[0].message' -o tsv
echo 'Latest guest Perf counters (memory, swap, CPU, disk, network):'
az monitor log-analytics query -w "$workspace" -t PT3H \
  --analytics-query "Perf | where Computer =~ 'vm-app-01' and TimeGenerated > ago(10m) | summarize arg_max(TimeGenerated, CounterValue) by ObjectName, CounterName, InstanceName | project TimeGenerated, ObjectName, CounterName, InstanceName, CounterValue | order by ObjectName, CounterName, InstanceName" -o table
echo 'Last five anomaly scores (table may be empty until detector deploys):'
az monitor log-analytics query -w "$workspace" -t PT3H \
  --analytics-query "VMAnomalyScore_CL | top 5 by TimeGenerated desc | project TimeGenerated, Computer, Score, IsAnomaly, TopFeature, Model" -o table
