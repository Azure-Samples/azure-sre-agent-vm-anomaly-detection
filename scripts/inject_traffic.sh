#!/usr/bin/env bash
# Trigger the demo incident without deploying anything: one bulk export
# request (/reports?since=<ts>) on vm-app-01. The running build archives every
# exported report without eviction, so memory jumps within seconds. The export
# window is sized to LEAK_PERCENT of the VM's memory (default 60), which caps
# the leak on any VM size; repeating it adds almost nothing because those
# reports are already archived. scripts/stop_traffic.sh releases the memory.
# The VM denies inbound traffic, so the request is made on the VM itself.
set -euo pipefail

rg="${VM_ANOMALY_RG:-rg-vm-anomaly-demo}"
vm="${VM_ANOMALY_VM:-vm-app-01}"
percent="${LEAK_PERCENT:-60}"
if [[ ! "${percent}" =~ ^[0-9]+$ ]] || (( percent < 10 || percent > 80 )); then
  echo "LEAK_PERCENT must be an integer from 10 to 80" >&2
  exit 2
fi

script="$(cat <<EOF
set -e
total_kb=\$(awk '/^MemTotal:/ {print \$2}' /proc/meminfo)
reports=\$(( total_kb * ${percent} / 100 / 256 ))
since=\$(date -u -d "@\$(( \$(date +%s) - reports ))" +%Y-%m-%dT%H:%M:%SZ)
logger -t demo-history-replay \
  "history replay started: /reports?since=\${since} (\${reports} reports)"
curl -fsS -o /dev/null "http://localhost:8080/reports?since=\${since}"
logger -t demo-history-replay "history replay finished"
curl -fsS http://localhost:8080/stats
EOF
)"

echo "exporting ${percent}% of memory worth of reports on ${vm} (${rg})" >&2
az vm run-command invoke -g "${rg}" -n "${vm}" --command-id RunShellScript \
  --scripts "${script}" --query 'value[0].message' -o tsv
