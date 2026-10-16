---
title: Operator scripts
description: Incident controls, manual recovery, and status helpers
---

## Incident controls

Run these helpers only against the dedicated demo subscription. They use the
active Azure CLI session; confirm the selected subscription first.

| Script | Purpose |
|--------|---------|
| `inject_traffic.sh` | Trigger the demo incident without a deploy: one bulk history export that archives `LEAK_PERCENT` (default 60) % of VM memory |
| `stop_traffic.sh` | Restart `demo-app`, releasing that memory |
| `break.sh <incident-build-ref>` | Deploy a separately prepared incident variant; the sample does not bundle historical release branches |
| `mitigate.sh`, `fix.sh` | Manual fallbacks: restart the service, deploy `main` |
| `status.sh` | Snapshot of version, `Perf` and scores |
