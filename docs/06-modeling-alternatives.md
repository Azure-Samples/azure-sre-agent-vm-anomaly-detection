---
title: Detection methods and trade-offs
description: Measured model comparisons and the sample detection approach
---

The sample uses grouped Isolation Forest models to detect trends and sustained
resource pressure with a small CPU-only inference package. Measured comparisons
come from `ml/REPORT.md`; they describe these datasets, not general model rankings.

## Measured models

| Model | Where | Synthetic F1 / PA-F1 | SMD PA-F1 | Verdict |
|---|---|---|---|---|
| **Isolation Forest**, one forest per resource group (memory / cpu / disk) on one-sided rolling-window features, `Score = max` over groups | `ml/models/iforest.py` – **shipped** | 0.935 / 0.992, 15/15 anomalies (leaks, CPU saturation, disk fills), 14 min delay, 3 false-alarm events in 12 VM-days with the 3-of-5 rule | 0.763 (single forest) | Best trade-off: trains in seconds on CPU, deterministic, pickle-able, no GPU, contribution per feature via `feature_stats`. |
| Spectral Residual | `ml/models/sr.py` | 0.001 / 0.122 at the fixed threshold | 0.732 (fixed threshold) | Weak on slow ramps in this evaluation; included as a baseline. |
| Dense autoencoder (reconstruction error) | `ml/models/autoencoder.py` | 0.876 / 0.933, 13 false-alarm events | 0.533 | Detects all 15 synthetic segments but produces more false alarms and requires the optional Torch dependency. |
| Static thresholds (`mem_used_pct > 90`, `mem_available_mb < 200`; memory only) | `infra/modules/monitoring.bicep` safety-net alert | 4/15 anomalies (leaks only), ~3 h delay | – | A comparison for remaining memory headroom, not a detector of CPU or disk incidents. |

---

## Scoring

The Azure Function loads a reviewed, SHA-256-pinned model artifact and scores
telemetry locally. Azure ML provides training and registration, not an online
endpoint. This keeps the live scoring path independent of ML workspace availability.

Per-resource forests avoid diluting CPU or disk signals among unrelated memory
features. One-sided features suppress recovery-direction changes, and group scores
give the investigation a resource-specific starting point.

The synthetic results support this demonstration, not production accuracy.
Real telemetry requires validation of normal ranges, detection delay, and false
alarms.
