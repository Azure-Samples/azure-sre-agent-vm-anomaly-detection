---
name: VM anomaly incident
about: Track an SRE Agent investigation through code fix and verification
title: "VM memory anomaly: "
labels: incident, sre-agent
---

## Problem

Alert ID, onset time (UTC), VM, and deployed ref from `/version`:

## Impact

Observed service health, latency, or errors:

## Evidence

KQL result links or timestamps for `VMAnomalyScore_CL` (Score trend, TopFeature,
`Details.contributions`) and `Perf` memory trend; `Syslog` deploy marker;
`/opt/demo-app/DEPLOY_LOG` line; Azure Activity Log run-command event:

## Root cause

Deployed commit, file:line, and how the code produces the memory growth:

## Proposed fix

Code change and expected steady-state behavior (do not roll back):

## Validation plan

Tests; after merge and deployment, `/version` SHA, `/health`, flat memory slope,
Score < 0.8 for 10 min, and resolved alert:

## Rollout

Link the fix PR with `Refs #<issue>` (not `Fixes`), a human merges it to `main`,
monitor `deploy-app.yml`, then comment with evidence; the approver closes this issue:
