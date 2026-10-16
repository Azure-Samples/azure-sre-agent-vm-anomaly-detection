---
title: Azure SRE Agent configuration
description: Connections, Review-mode approvals, scripted setup, and cost controls
---

## Portal setup

`infra/deploy.sh` provisions `id-sreagent-vm-anomaly` and its roles
(Reader, Log Analytics Reader, Monitoring Reader, Monitoring Contributor,
Virtual Machine Contributor) on `rg-vm-anomaly-demo`. It then attempts
`sreagent-vm-anomaly` with `Microsoft.App/agents@2025-05-01-preview`,
Review mode, High access, and that managed identity.

If the service principal cannot create the agent, use the Azure portal:

1. **Azure SRE Agent → Create**: subscription
   selected by `AZURE_SUBSCRIPTION_ID`, RG `rg-vm-anomaly-demo`,
   East US 2, name `sreagent-vm-anomaly`.
2. In **Settings → Basics**, select Review mode and High access.
   Assign `id-sreagent-vm-anomaly` for knowledge graph and action
   identity; add `rg-vm-anomaly-demo` to managed resources. Under
   **Builder → Incident platform**, connect Azure Monitor and save.
   Grant the identity selected for this connection **Monitoring Contributor**
   on `rg-vm-anomaly-demo` only (not the subscription, or the agent analyses
   and bills for alerts of every workload in it) and confirm the fired alert
   appears in the agent.
   The Azure Monitor connection scans alerts each minute; the action group
   does not need a receiver to deliver alerts to the agent.
3. Assign the approving human **SRE Agent Administrator** on the agent
   resource (or rerun `infra/deploy.sh --admin <user-object-id>`).
4. In **Builder → Agent Canvas**, select **Create → Trigger → Incident
   response plan**. Match the Azure Monitor alert (severity 2 and title
   `alert-ml-anomaly-vm-app-01`), route it to a custom agent with the
   instructions in `response-plan.md`, select **Review** (the plan
   otherwise defaults to Autonomous), preview matches and enable it.
   Disable the default quickstart plan if it would duplicate handling.
   Import `skills/vm-anomaly-triage/SKILL.md` under **Builder → Skills**.
   Under **Builder → Hooks**, install the Stop prompt from
   `hooks/vm-remediation-approval.yaml`, activation **Always**;
   verify each resource is enabled. Use `prompts.md` for the demo.

## Connect GitHub for stage 3/4

5. In the portal for `sreagent-vm-anomaly`, go to **Builder → Connectors →
   Add connector → GitHub OAuth connector**. Select OAuth and sign in,
   or PAT and connect a token with issue read/write access to
   the repository configured as `GITHUB_REPOSITORY`. Confirm Connected; ask the agent
   to list issues in that repo. For a BYO GitHub App, grant repository
   **Metadata: Read**, **Contents: Read** and **Issues: Read/Write**;
   grant **Pull requests: Read** and **Actions: Read** if the agent will
   inspect fix PRs and workflow runs. Do not grant merge permission
   unless specifically needed. GitHub Connector manages issues/PRs;
   it is distinct from source-code indexing.
6. Under **Builder → Code Access** (also exposed as **Builder →
   Knowledge base → Add repository**), choose GitHub, authenticate with
   OAuth or PAT, select the repository configured as `GITHUB_REPOSITORY` from the
   dropdown, then **Add repository**. Confirm it can read
   `app/server.py` at the deployed ref, not just on `main`.
   For OAuth/PAT on a public repo, `public_repo`/read
   access suffices for code; private repos need `repo`. Code Access
   alone cannot open the incident issue.
7. Set up GitHub Actions as described in `docs/08-github-actions-setup.md`. The
   agent opens a labeled `incident` issue using the template and asks
   for human review; adding `approved` dispatches the coding agent.
   After a human merges the PR and it deploys, the agent verifies and
   comments the evidence; a human closes the issue. The response instructions
   prohibit the agent from closing issues or merging PRs.

**Approval limitation:** documented hooks support only `Stop` and
`PostToolUse`, neither of which prevents a command *before* it runs.
This hook checks responses, not tool execution. **Review mode is the
pre-execution approval gate** for Azure infrastructure writes. Never
switch to Autonomous for the demo.

## Scripted setup

`configure.py` applies steps 2 to 6 through the agent's data-plane API
instead of the portal, and can be rerun safely. Set `AZURE_SUBSCRIPTION_ID`
and `GITHUB_REPOSITORY=owner/repository` using the environment setup first:

```bash
uv run python sre-agent/configure.py --wait-github 600
```

It grants **Monitoring Contributor** on `rg-vm-anomaly-demo` to both agent
identities (user-assigned and system-assigned), imports the
`vm-anomaly-triage` skill, creates the custom agent `vm-anomaly-responder`
with `response-plan.md` as its instructions and the Stop hook from
`hooks/vm-remediation-approval.yaml`, and creates the Review-mode response
plan `vm-anomaly-ml-alert` that routes the ML alert (Sev0 to Sev2, title
containing the rule name or its display name) to that agent. Agent configuration
uses the data-plane API rather than ARM sub-resource deployment.

GitHub still needs one human step: the script prints an OAuth link, and a
person signs in and selects **Authorize**. The link carries a one-time state
value, so open it immediately after it is printed. Once the agent reports a
connected GitHub domain, the script adds this repository for Code Access.

## Cost and free trial

Azure SRE Agent charges include always-on capacity and active flow measured in
Azure Agent Units (AAU). Background analysis can consume active flow even without
an open incident. Stopping the agent is not equivalent to deleting it and does
not remove every charge. Check current pricing, trial eligibility, and usage
before creating or recreating an agent [1, 2, 3].

| Control | Sample behavior |
|---------|-----------------|
| Managed scope | Monitoring roles target the demo resource group, not unrelated workloads |
| Active-flow limit | Bicep sets `monthlyAgentUnitLimit` to 500 AAU; this is not a cap on all Azure resource charges |
| Stop between demonstrations | Use **Settings > Basics > Stop**; start it before the next incident |
| Teardown | `infra/teardown.sh` deletes the sample resource groups and agent; recreating it can affect trial eligibility |

`lockdown.py` stops the agent, applies the active-flow limit, and restricts
monitoring role grants to the demo resource group. Run it against the selected
demo subscription:

```bash
uv run python sre-agent/lockdown.py
```

For an explicitly scheduled macOS run, use
`--install --at YYYY-MM-DDTHH:MM` with local time; `--uninstall` cancels it.
The scheduled job removes itself after running. If the subscription prevents
writes, inspect the log and rerun manually when writes are available.

## References

1. [Pricing and billing](https://learn.microsoft.com/azure/sre-agent/pricing-billing)
2. [Free trial](https://learn.microsoft.com/azure/sre-agent/evaluate)
3. [Monitor agent usage](https://learn.microsoft.com/azure/sre-agent/monitor-agent-usage)
4. [Azure Monitor alerts](https://learn.microsoft.com/azure/sre-agent/azure-monitor-alerts)
5. [GitHub connector](https://learn.microsoft.com/azure/sre-agent/github-connector)
6. [Connector setup](https://learn.microsoft.com/azure/sre-agent/setup-github-connector)
7. [Code Access](https://learn.microsoft.com/azure/sre-agent/connect-source-code)
8. [Response plans](https://learn.microsoft.com/azure/sre-agent/response-plan)
9. [Skills](https://learn.microsoft.com/azure/sre-agent/agent-skills)
10. [Hooks](https://learn.microsoft.com/azure/sre-agent/agent-hooks)
11. [Run modes](https://learn.microsoft.com/azure/sre-agent/run-modes)
12. [API reference](https://learn.microsoft.com/azure/sre-agent/api-reference)
