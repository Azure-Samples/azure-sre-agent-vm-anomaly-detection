#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
set -euo pipefail
az account set --subscription "${AZURE_SUBSCRIPTION_ID:?Set AZURE_SUBSCRIPTION_ID before teardown}"
rg='rg-vm-anomaly-demo'
if az group exists -n "$rg" | rg -q true; then
  law_id="$(az monitor log-analytics workspace show -g "$rg" \
    -n law-vm-anomaly-demo --query id -o tsv)"
  existing="$(az monitor diagnostic-settings subscription list \
    --query "[?name=='activity-to-law'].workspaceId | [0]" -o tsv)"
  if [[ "${existing,,}" == "${law_id,,}" ]]; then
    az monitor diagnostic-settings subscription delete -n activity-to-law
  fi
  az group delete -n "$rg" --yes --no-wait
  echo "Deletion started for $rg (Azure may take several minutes)."
fi

ml_rg='rg-vm-anomaly-ml'
if az group exists -n "$ml_rg" | rg -q true; then
  az group delete -n "$ml_rg" --yes --no-wait
  echo "Deletion started for $ml_rg (Azure may take several minutes)."
fi
