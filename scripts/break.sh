#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
# Trigger the demo incident (a memory leak, one of the anomaly classes the detector covers):
# deploy an explicitly supplied incident build to vm-app-01.
set -euo pipefail
ref="${1:?Usage: scripts/break.sh <incident-build-ref>; or use scripts/inject_traffic.sh}"
exec "$(dirname "$0")/deploy_app.sh" "$ref"
