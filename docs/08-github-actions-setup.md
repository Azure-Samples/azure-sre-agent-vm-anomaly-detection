---
title: GitHub Actions setup
description: Configure Azure deployment and Copilot incident dispatch workflows
---

## GitHub Actions setup

1. Set Actions secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and
   `AZURE_SUBSCRIPTION_ID` for the service principal authorized to run
   `az vm run-command` on `vm-app-01`. Create an OIDC federated credential
   (do **not** run this as part of CI):

   ```bash
   az ad app federated-credential create --id "$AZURE_CLIENT_ID" --parameters \
     "{\"name\":\"vm-anomaly-main\",\"issuer\":\"https://token.actions.githubusercontent.com\",\"subject\":\"repo:${GITHUB_REPOSITORY}:ref:refs/heads/main\",\"audiences\":[\"api://AzureADTokenExchange\"]}"
   ```

   Set `GITHUB_REPOSITORY=owner/repository` and `AZURE_CLIENT_ID` for the
   demo repository before running this command. This subject covers
   pushes to `main` and manual dispatches **from** `main`.
   If dispatching this workflow from another branch, add a credential for
   that branch subject as well. The `ref` input controls the app code deployed,
   not the branch from which the workflow runs. Merging a change under
   `app/**` to `main` deploys it only when the pull request carries the
   `deploy` label; every other merge is skipped with a notice.
2. Set Actions secret `CODING_AGENT_TOKEN` to a **user** token, not
   `GITHUB_TOKEN`/an installation token, so the Copilot assignment originates
   from a user. GitHub's preview issues API requires a fine-grained PAT with
   metadata read and Actions, Contents, Issues, Pull requests read/write, or a
   classic PAT with `repo`.
   Limit it to this repository where possible. Enable Copilot cloud agent for
   this repo and authorize the user to assign issues to it.
3. Run `scripts/setup_github.sh` once to create the labels. Label
   an `incident` issue `approved` only after a human has reviewed the fix plan.
   Anyone permitted to apply this label can trigger coding-agent dispatch.
   The `deploy` label marks a pull request whose merge should deploy the app.
   `issues: labeled` runs only after the workflow is on the default branch;
   adding the label to an already-approved issue does not retrigger it.

## References

1. [Azure Login OIDC](https://learn.microsoft.com/azure/developer/github/connect-from-azure-openid-connect)
2. [Copilot issues API](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/use-cloud-agent-via-the-api)
3. [GitHub issue events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#issues)
