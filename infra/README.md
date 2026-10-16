---
title: Infrastructure
description: Bicep resources, deployment boundaries, and redeployment guidance
---

## Resources

All system provisioning is declarative Bicep at subscription scope (`main.bicep`):

| module | resources |
|---|---|
| `network.bicep` | vnet, subnet, NSG |
| `vm.bicep` | `vm-app-01` (cloud-init installs `app/`), Azure Monitor Agent extension |
| `monitoring.bicep` | Log Analytics `law-vm-anomaly-demo`, Perf/Syslog DCR + association, DCE + `VMAnomalyScore_CL` DCR, action group, ML and baseline scheduled-query alerts |
| `function.bicep` | Flex Consumption Function host and app settings, storage, identities |
| `roles.bicep` | `id-sreagent-vm-anomaly` + RBAC for the agent and the Function |
| `sre-agent.bicep` | `sreagent-vm-anomaly` (Review mode, High access), optional SRE Agent Administrator assignment |
| `ml.bicep` | `rg-vm-anomaly-ml`: Azure ML workspace `mlw-vm-anomaly` + dependencies, `cpu-ds3v2` cluster (0..1) |
| `main.bicep` | both resource groups, Activity Log → LAW diagnostic setting |

`deploy.sh` uses the existing Azure CLI login, ensures an SSH key exists, and runs
`az deployment sub create` with `main.bicepparam` (all knobs are environment
variables; subscription selection is required). `--what-if` previews;
`--admin <object-id>` grants the approving human SRE Agent Administrator.
`teardown.sh` deletes the resource groups.

First complete `docs/10-environment-setup.md`: sign in with Azure CLI and set
`AZURE_SUBSCRIPTION_ID`. Both wrappers reject a missing subscription. ML
dependency overrides are empty by default, so fresh deployments generate
names for the target environment instead of reusing existing resources.

Not in Bicep, by design: code deployments (`detector/deploy.sh` publishes the
Function code, `scripts/deploy_app.sh` ships an app revision to the VM) and the
SRE Agent configuration (response plan, skills, GitHub connector, Code Access —
see `sre-agent/README.md`, scripted by `sre-agent/configure.py`). The Bicep
declares the resources; that configuration sets the agent's behaviour on top of them.

## Redeploying after teardown

`teardown.sh` deletes the resource groups, but several resources are only
soft-deleted and are recovered or block the next `deploy.sh`:

| Resource | Behaviour on redeploy | Action |
|----------|-----------------------|--------|
| Log Analytics `law-vm-anomaly-demo` | Recovered under the same name, with its old data | If no new `Perf` rows arrive within about 20 minutes, restart the agent on the VM: `systemctl restart azuremonitoragent` through `az vm run-command` |
| Key Vault (generated name) | Deployment fails with a name conflict | Recover the vault using `az keyvault recover --name <your-vault-name>` |
| Azure ML workspace `mlw-vm-anomaly` | Deployment fails with "Soft-deleted workspace exists" | Recover or permanently delete it in the Azure ML studio; the live demo does not need Azure ML |
| SRE Agent `sreagent-vm-anomaly` | Created again, which consumes one of three free trials | See [SRE Agent cost and free trial](../sre-agent/README.md#cost-and-free-trial) |

A freshly created alert rule can fail with "The workspace could not be found"
when the workspace was created seconds earlier; rerun `deploy.sh`.
After deployment, run `uv run python sre-agent/configure.py` to configure the
agent without the portal.
