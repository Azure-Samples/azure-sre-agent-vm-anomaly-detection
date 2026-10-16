---
title: Technology overview
description: Azure services, detection methods, and datasets
---

## Azure service roles

| Service | Role in this sample |
|---------|---------------------|
| Azure Monitor Agent and Log Analytics | Collect guest performance counters, application Syslog, and Azure Activity Log evidence |
| Azure Functions | Query recent telemetry and run the packaged detector model every minute |
| Azure Monitor alerts | Evaluate the custom score table and expose fired incidents |
| Azure SRE Agent | Investigate alerts, propose approved mitigation, inspect source code, and report recovery evidence |
| Azure Machine Learning | Train, evaluate, register, and export model artifacts; not an online inference dependency |
| GitHub | Track incident issues, human approvals, coding-agent PRs, and deployment runs |

SRE Agent uses separate Azure Monitor, GitHub connector, and Code Access
connections. The GitHub connector handles incident records; Code Access reads
the source revision running on the VM [1, 2].

**Review mode** is the approval boundary for Azure infrastructure writes.
The Stop hook checks the agent's final response after tool use; it does not
prevent execution. The approving human needs SRE Agent Administrator access
to the agent resource [3, 4].

---

## Detection approach

The shipped detector uses one Isolation Forest per memory, CPU, or disk
feature group. Rolling slopes capture memory/disk growth, while the CPU
window minimum captures sustained saturation. The maximum calibrated group
score determines the alert signal.

The scripted incident triggers a latent memory leak through historical-report
traffic, without changing the deployed application. Investigation correlates
traffic and deployment evidence rather than assuming a deployment caused
every anomaly.

Spectral Residual and an optional autoencoder provide benchmark comparisons.
The sample does not provision the retired Azure AI Anomaly Detector service [5].

## Data sources

| Source | Use |
|--------|-----|
| Synthetic live-metric VM series | Training and primary evaluation of the shipped model |
| SMD: 38 metrics per server, with labelled test data | Benchmark evaluation with one model per machine [6] |
| NAB `realAWSCloudwatch`: 17 labelled cloud-metric series | Univariate benchmark evaluation [7] |
| The deployed VM's `Perf` and `Syslog` tables | Live scoring and incident investigation |

SMD and NAB are downloaded separately. They are not the training data for
the shipped live model and are not bundled in the repository.

## References

1. [Azure SRE Agent: Azure Monitor alerts](https://learn.microsoft.com/azure/sre-agent/azure-monitor-alerts)
2. [Azure SRE Agent: Code Access](https://learn.microsoft.com/azure/sre-agent/connect-source-code)
3. [Azure SRE Agent: Run modes](https://learn.microsoft.com/azure/sre-agent/run-modes)
4. [Azure SRE Agent: Agent hooks](https://learn.microsoft.com/azure/sre-agent/agent-hooks)
5. [Azure AI Anomaly Detector](https://learn.microsoft.com/azure/ai-services/anomaly-detector/)
6. [OmniAnomaly Server Machine Dataset](https://github.com/NetManAIOps/OmniAnomaly/tree/master/ServerMachineDataset)
7. [Numenta Anomaly Benchmark](https://github.com/numenta/NAB)
