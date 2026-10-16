#!/usr/bin/env bash
# Stage 2 interim action: restart demo-app.service. Restores service health for any app-level
# anomaly (leak, runaway loop, stuck workers) without touching the code - the RCA still has to run.
set -euo pipefail
az vm run-command invoke -g rg-vm-anomaly-demo -n vm-app-01 \
  --command-id RunShellScript \
  --scripts 'sudo systemctl restart demo-app.service && logger -t demo-app "mitigation: restart" && sleep 2 && curl -fsS http://localhost:8080/stats' \
  --query 'value[0].message' -o tsv
