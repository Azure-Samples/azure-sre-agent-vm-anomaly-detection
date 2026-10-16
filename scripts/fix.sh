#!/usr/bin/env bash
# Stage 4 (manual fallback): deploy the merged fix from main to vm-app-01.
# Normally .github/workflows/deploy-app.yml does this on merge; see docs/04-demo-runbook.md.
set -euo pipefail
exec "$(dirname "$0")/deploy_app.sh" "${1:-origin/main}"
