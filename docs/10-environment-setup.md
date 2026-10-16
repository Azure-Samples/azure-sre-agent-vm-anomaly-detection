---
title: Environment setup
description: Configure a personal Azure and GitHub environment for the sample
---

## Prerequisites

Use Python 3.11 or later, uv, Git, Azure CLI with Bicep, and GitHub CLI.
Shell deployment helpers target Bash 4 or later on Linux or WSL; on macOS,
use Bash 4 or later and GNU coreutils for GNU-specific commands.

For live mode, use a dedicated Azure subscription with permission to create
resources and role assignments, sufficient VM quota in East US 2, and access
to Azure SRE Agent. Use a GitHub repository you administer, such as a fork of
this sample. Copilot incident dispatch also needs an authorized user.

**Do not deploy to production.** The web application intentionally contains a
memory leak, and the incident helpers consume VM resources.

## Local settings

From the repository root:

```bash
uv sync --python 3.11 --extra dev --extra dashboard --extra detector
cp .env.example .env
```

Edit `.env` before loading it. No program loads this file automatically.

| Setting | Value |
|---------|-------|
| `AZURE_TENANT_ID` | Your Microsoft Entra tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Your dedicated demo subscription ID |
| `GITHUB_REPOSITORY` | Your demo repository in `owner/repository` form |
| `DASHBOARD_TENANT_ID`, `DASHBOARD_SUBSCRIPTION_ID`, `DASHBOARD_REPO` | Inherit the preceding values when the example is sourced |
| `DASHBOARD_FUNCTION_APP` | Optional: Function App name from deployment outputs |

```bash
set -a
source .env
set +a
az login --tenant "$AZURE_TENANT_ID"
az account set --subscription "$AZURE_SUBSCRIPTION_ID"
az account show --query '{subscription:id,tenant:tenantId}' -o table
gh auth login
```

Confirm the selected subscription before any deployment, incident injection,
or teardown. Application scripts use the active Azure CLI subscription.
The provisioning, teardown, SRE Agent, and Azure ML helpers require
`AZURE_SUBSCRIPTION_ID` explicitly. Secrets are never supplied in this template.
Use interactive sign-in locally and OIDC for GitHub Actions; do not put client
secrets or tokens in command arguments or source control.

## Preview, deploy, and configure

```bash
uv run --no-sync python -m dashboard.server --demo
```

Stop the offline preview before starting live mode on the same port.
Demo links use synthetic identifiers and are not links to deployed resources.

After confirming quota, permissions, and expected charges:

```bash
bash infra/deploy.sh --what-if
bash infra/deploy.sh --admin '<approving-user-object-id>'
bash detector/deploy.sh
uv run --no-sync python sre-agent/configure.py --wait-github 600
bash scripts/setup_github.sh
```

Resource names such as `vm-app-01` and `rg-vm-anomaly-demo` are shared sample
defaults. Globally unique ML dependency names are generated from your resource
group ID. Leave `VM_ANOMALY_ML_STORAGE`, `VM_ANOMALY_ML_KEYVAULT`,
`VM_ANOMALY_ML_APPINSIGHTS`, `VM_ANOMALY_ML_LAW`, and `VM_ANOMALY_ML_ACR`
unset for a fresh deployment. For an existing workspace, set them to its
existing dependencies before redeploying.

Follow the GitHub Actions setup and demo runbook for OIDC, human approval,
incident injection, and recovery. Keep SRE Agent in **Review** mode.

```bash
export GITHUB_TOKEN="$(gh auth token)"
uv run --no-sync python -m dashboard.server
```

For Azure ML training and registration, install the optional dependencies
with `uv sync --extra ml --extra dev --extra dashboard --extra detector`. The shipped detector
model was trained on synthetic data; training is not required for the demo.

## Cleanup

```bash
bash infra/teardown.sh
```

This deletes both sample resource groups in `AZURE_SUBSCRIPTION_ID`. Review
the SRE Agent cost guidance before deleting or recreating an agent. Keep
`.env`, private keys, local Azure settings, downloaded datasets, and generated
outputs out of commits.
