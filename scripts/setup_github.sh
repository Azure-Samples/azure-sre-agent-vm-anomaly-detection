#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
# One-time GitHub repo setup. Requires gh auth with label/variable write access.
set -euo pipefail

repo="${GITHUB_REPOSITORY:?Set GITHUB_REPOSITORY to owner/repository before setup}"
gh label create incident --repo "$repo" --color d73a4a \
  --description "Production anomaly requiring an incident response" --force
gh label create approved --repo "$repo" --color 0e8a16 \
  --description "Human approved the issue fix plan for coding-agent dispatch" --force
gh label create sre-agent --repo "$repo" --color 1d76db \
  --description "Incident investigated by Azure SRE Agent" --force
gh label create deploy --repo "$repo" --color fbca04 \
  --description "Merging this pull request deploys app/ to vm-app-01" --force
