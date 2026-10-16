#!/usr/bin/env bash
# Reset the demo incident started by scripts/inject_traffic.sh: restart
# demo-app.service, which releases the report archive.
set -euo pipefail

rg="${VM_ANOMALY_RG:-rg-vm-anomaly-demo}"
vm="${VM_ANOMALY_VM:-vm-app-01}"

script='logger -t demo-history-replay "history replay reset"
systemctl restart demo-app.service
curl --fail --silent --retry 10 --retry-connrefused --retry-delay 1 \
  http://localhost:8080/health'

echo "resetting demo-app on ${vm} (${rg})" >&2
az vm run-command invoke -g "${rg}" -n "${vm}" --command-id RunShellScript \
  --scripts "${script}" --query 'value[0].message' -o tsv
