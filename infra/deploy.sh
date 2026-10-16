#!/usr/bin/env bash
# Copyright (c) Microsoft Corporation.
# SPDX-License-Identifier: MIT
# Thin wrapper around `az deployment sub create` for infra/main.bicep. Everything the system
# needs (RGs, VM, AMA/DCR/LAW, alerts, Function, roles, SRE Agent, Azure ML) is declared there;
# this script only signs in, supplies the SSH key and runs the deployment.
#   infra/deploy.sh [--admin <human-user-object-id>] [--what-if]
set -euo pipefail

dir="$(cd "$(dirname "$0")" && pwd)"
subscription="${AZURE_SUBSCRIPTION_ID:?Set AZURE_SUBSCRIPTION_ID before deploying}"
key="${HOME}/.ssh/vm-anomaly-demo"
what_if=()
while (( $# )); do
  case "$1" in
    --admin) export VM_ANOMALY_SRE_ADMIN_OBJECT_ID="$2"; shift 2 ;;
    --what-if) what_if=(--what-if); shift ;;
    *) echo 'Usage: infra/deploy.sh [--admin <human-user-object-id>] [--what-if]' >&2; exit 2 ;;
  esac
done

az account set --subscription "$subscription"
[[ -f "$key.pub" ]] || ssh-keygen -q -t ed25519 -N '' -f "$key"
export VM_ANOMALY_SSH_PUBLIC_KEY
VM_ANOMALY_SSH_PUBLIC_KEY="$(<"$key.pub")"
# The VM's cloud-init customData is immutable, so an existing VM is left alone.
if [[ -z "${VM_ANOMALY_CREATE_VM:-}" ]] && az vm show -g rg-vm-anomaly-demo -n vm-app-01 -o none 2>/dev/null; then
  export VM_ANOMALY_CREATE_VM=false
fi

az deployment sub create --name vm-anomaly-demo --location eastus2 \
  --template-file "$dir/main.bicep" --parameters "$dir/main.bicepparam" ${what_if[@]+"${what_if[@]}"} \
  --query properties.outputs -o json
