---
title: ML evaluation report
description: Synthetic VM, SMD, and NAB evaluation results for the sample models
---

Shipped model: **one one-sided IsolationForest per resource group (memory / cpu / disk) on
synthetic live-metric features, `Score = max` over groups**, exported to
`detector/model/`. SMD / NAB runs are for evaluation
only (different metric schemas, one plain forest per series).

Azure ML training used a single `Standard_DS3_v2` node for the shipped model
and the SMD/NAB iforest + SMD sr runs. The corresponding rows below are
reproducible with seeded training. The `ae` rows were run locally with
the same code (torch is not in the Azure ML env).

## Setup

| | |
|---|---|
| features | `ml.features.make_features(df, window=30)`: trailing rolling mean/std/least-squares slope/min/max + first difference per metric (NaN-safe, fixed column order) |
| shipped features | `memory`: `mem_used_pct__slope` (+), `mem_available_mb__slope` (-), `swap_used_pct__slope` (+); `cpu`: `cpu_pct__min` (+); `disk`: `disk_used_pct__slope` (+) - one-sided around the training median (only the anomalous direction is kept) so that absolute baselines of a new VM and the *recovery* after a restart / fix do not alert |
| calibration | per group: score_g = clip(0.8 * (raw_g - q50) / (q99.9 - q50), 0, 1) on that group's (normal) training scores; Score = max_g score_g, so the fleet threshold **0.8** = "some resource is more anomalous than 99.9 % of its normal training windows" |
| synthetic | 24 anomaly-free simulated 4 GB VMs x 3 days at 1 min for training (CPU baselines 0.5-45 %, varied disk jitter); 4 other seeds x 3 days for test, each with 2 injected post-deployment memory leaks (10-20 MB/min, 3-5 h, until restart), 1 CPU saturation (85-100 % for 30-120 min) and 1 disk fill (0.2-1 %/min, 30-90 min) = 15 labelled segments (8 memory, 3 CPU, 4 disk); diurnal load, CPU bursts, batch jobs, restarts, log rotation (`ml/data/synthetic.py`) |
| SMD | OmniAnomaly Server Machine Dataset, machines 1-1, 1-6, 2-1, 3-7 (38 metrics, 1 min); fit on the train half, evaluate on the labelled test half |
| NAB | `realAWSCloudwatch` (17 series, 5 min); fit on the first 15 % (NAB probation period), evaluate on the rest; labels = `combined_windows.json` |
| metrics | point-wise P/R/F1; **PA-F1** = point-adjusted F1 (Xu et al. 2018: a segment counts as fully detected if any point in it is flagged); detection delay = rows from segment start to the first flag (1 row = 1 min, NAB 5 min); false-alarm events = flagged runs outside any label. P/R/F1 are averaged over series with labelled anomalies. The first `window - 1` rows of every series are skipped |
| thresholds | `0.80 (fixed)` = what the detector uses; `best-F1 (oracle)` = best threshold chosen on the test labels (upper bound, not deployable); `3-of-5 alert rule` = the Azure Monitor alert condition (score > 0.8 in >= 3 of the last 5 minutes) |

Reproduce locally (or see `ml/azureml/job.yaml` for the Azure ML run):

```bash
for r in synthetic-iforest synthetic-ae synthetic-sr smd-iforest smd-ae smd-sr nab-iforest nab-sr; do
  python -m ml.train --dataset ${r%%-*} --model ${r#*-} --out outputs/$r
done
python -m ml.evaluate --runs outputs/{synthetic,smd,nab}-* --report ml/REPORT.md
```

## Results

<!-- results -->
| dataset | model | threshold | series | P | R | F1 | PA-F1 | segments detected | mean delay (rows) | false-alarm events |
|---|---|---|---|---|---|---|---|---|---|---|
| synthetic | ae | 0.80 (fixed) | 4 | 0.862 | 0.892 | 0.876 | 0.933 | 15/15 | 14.1 | 13 |
| synthetic | ae | best-F1 (oracle) | 4 | 0.866 | 0.891 | 0.878 | 0.935 | 15/15 | 14.1 | 10 |
| synthetic | ae + 3-of-5 alert rule | 3 of 5 min | 4 | 0.847 | 0.877 | 0.862 | 0.927 | 15/15 | 16.1 | 8 |
| synthetic | static threshold | mem_used_pct > 90 | 4 | 0.750 | 0.034 | 0.065 | 0.492 | 4/15 | 174.7 | 0 |
| synthetic | static metric alert | mem_available_mb < 200 | 4 | 0.750 | 0.006 | 0.012 | 0.492 | 4/15 | 189.2 | 0 |
| synthetic | iforest | 0.80 (fixed) | 4 | 0.983 | 0.892 | 0.935 | 0.992 | 15/15 | 14.2 | 11 |
| synthetic | iforest | best-F1 (oracle) | 4 | 0.991 | 0.895 | 0.940 | 0.996 | 15/15 | 13.6 | 7 |
| synthetic | iforest + 3-of-5 alert rule | 3 of 5 min | 4 | 0.971 | 0.877 | 0.922 | 0.987 | 15/15 | 16.2 | 3 |
| synthetic | sr | 0.80 (fixed) | 4 | 0.250 | 0.000 | 0.001 | 0.122 | 1/15 | 0.0 | 1 |
| synthetic | sr | best-F1 (oracle) | 4 | 0.116 | 1.000 | 0.208 | 0.208 | 15/15 | 0.0 | 0 |
| synthetic | sr + 3-of-5 alert rule | 3 of 5 min | 4 | 0.000 | 0.000 | 0.000 | 0.000 | 0/15 | - | 0 |
| smd | ae | 0.80 (fixed) | 4 | 0.394 | 0.640 | 0.353 | 0.533 | 45/56 | 4.7 | 408 |
| smd | ae | best-F1 (oracle) | 4 | 0.336 | 0.762 | 0.407 | 0.504 | 49/56 | 2.9 | 608 |
| smd | ae + 3-of-5 alert rule | 3 of 5 min | 4 | 0.397 | 0.629 | 0.350 | 0.529 | 42/56 | 7.8 | 141 |
| smd | iforest | 0.80 (fixed) | 4 | 0.667 | 0.262 | 0.326 | 0.763 | 32/56 | 104.8 | 310 |
| smd | iforest | best-F1 (oracle) | 4 | 0.390 | 0.631 | 0.460 | 0.649 | 49/56 | 4.8 | 919 |
| smd | iforest + 3-of-5 alert rule | 3 of 5 min | 4 | 0.667 | 0.258 | 0.323 | 0.757 | 26/56 | 110.7 | 92 |
| smd | sr | 0.80 (fixed) | 4 | 0.576 | 0.009 | 0.017 | 0.732 | 20/56 | 25.0 | 79 |
| smd | sr | best-F1 (oracle) | 4 | 0.083 | 0.779 | 0.147 | 0.222 | 56/56 | 0.1 | 1455 |
| smd | sr + 3-of-5 alert rule | 3 of 5 min | 4 | 0.000 | 0.000 | 0.000 | 0.000 | 0/56 | - | 0 |
| nab | iforest | 0.80 (fixed) | 17 | 0.178 | 0.146 | 0.087 | 0.424 | 15/30 | 83.7 | 602 |
| nab | iforest | best-F1 (oracle) | 17 | 0.263 | 0.596 | 0.289 | 0.499 | 28/30 | 28.9 | 1331 |
| nab | iforest + 3-of-5 alert rule | 3 of 5 min | 17 | 0.135 | 0.141 | 0.078 | 0.222 | 10/30 | 94.8 | 151 |
| nab | sr | 0.80 (fixed) | 17 | 0.170 | 0.051 | 0.052 | 0.583 | 20/30 | 59.4 | 1700 |
| nab | sr | best-F1 (oracle) | 17 | 0.121 | 0.979 | 0.215 | 0.222 | 30/30 | 0.0 | 523 |
| nab | sr + 3-of-5 alert rule | 3 of 5 min | 17 | 0.204 | 0.016 | 0.024 | 0.351 | 11/30 | 93.8 | 167 |
<!-- /results -->

Per SMD machine (fixed threshold 0.8):

<!-- per-series -->
| dataset | model | thr | series name | P | R | F1 | PA-F1 | segments detected | mean delay (rows) | false-alarm events |
|---|---|---|---|---|---|---|---|---|---|---|
| smd | ae | 0.80 | machine-1-1 | 0.575 | 0.733 | 0.644 | 0.787 | 8/8 | 0.0 | 110 |
| smd | ae | 0.80 | machine-1-6 | 0.230 | 0.975 | 0.373 | 0.377 | 23/30 | 0.0 | 273 |
| smd | ae | 0.80 | machine-2-1 | 0.744 | 0.226 | 0.347 | 0.895 | 9/13 | 9.6 | 14 |
| smd | ae | 0.80 | machine-3-7 | 0.024 | 0.627 | 0.047 | 0.074 | 5/5 | 9.4 | 11 |
| smd | iforest | 0.80 | machine-1-1 | 0.356 | 0.322 | 0.338 | 0.773 | 5/8 | 329.8 | 89 |
| smd | iforest | 0.80 | machine-1-6 | 0.666 | 0.503 | 0.573 | 0.882 | 21/30 | 5.3 | 212 |
| smd | iforest | 0.80 | machine-2-1 | 0.647 | 0.092 | 0.162 | 0.563 | 5/13 | 13.0 | 9 |
| smd | iforest | 0.80 | machine-3-7 | 1.000 | 0.131 | 0.232 | 0.835 | 1/5 | 71.0 | 0 |
| smd | sr | 0.80 | machine-1-1 | 0.769 | 0.004 | 0.007 | 0.998 | 5/8 | 70.2 | 2 |
| smd | sr | 0.80 | machine-1-6 | 1.000 | 0.000 | 0.001 | 0.002 | 1/30 | 1.0 | 0 |
| smd | sr | 0.80 | machine-2-1 | 0.250 | 0.019 | 0.035 | 0.953 | 10/13 | 17.2 | 62 |
| smd | sr | 0.80 | machine-3-7 | 0.286 | 0.014 | 0.026 | 0.975 | 4/5 | 11.8 | 15 |
<!-- /per-series -->

## Findings

* **Synthetic / live contract (what ships):** the grouped IsolationForest flags every injected
  anomaly (15/15: 8 memory leaks, 3 CPU saturations, 4 disk fills) about **14 min** after it
  starts at the fixed 0.8 threshold, and still 15/15 with the 3-of-5 alert rule (~16 min,
  **3 false-alarm events** in 12 VM-days, all from the `disk` group on the noisiest test VM).
  The memory-only static rules can by construction see only the leaks: `mem_used_pct > 90`
  fires on 4/15 segments and **~175 min** late (the leak has to fill the remaining headroom
  first; leaks that are cut short by a restart before reaching 90 % are never seen), and
  `mem_available_mb < 200` (the default Azure Monitor style metric alert) is even later.
  This lead time and class coverage is the point of the demo: the agent gets to act before
  the VM is out of memory / CPU / disk, and is told which resource to look at.
* **Autoencoder** (optional, torch) is close on synthetic data (15/15, PA-F1 0.93) but produces
  more false-alarm events (13 vs 11 at 0.8; 8 vs 3 with the alert rule). The deployed
  detector uses Isolation Forest without the optional Torch dependency.
* **Spectral Residual** is a point/spike detector: it scores 0 on slow ramps at the fixed
  threshold (a leak has no spectral "surprise"), and on SMD / NAB it reaches a high PA-F1
  with a near-zero point-wise F1 - a known artefact of point adjustment (a single lucky spike
  inside a long segment counts as full detection). Kept as the unsupervised baseline.
* **SMD:** IsolationForest on the full 38-metric feature set gives PA-F1 ~0.76 at the fixed
  threshold, but with many
  false-alarm events on machine-1-6 / 1-1: on real multivariate server data a fixed 0.8
  threshold calibrated on training quantiles is noisy, which is why the alert additionally
  requires 3 of 5 minutes. NAB (single-metric, 5 min, tiny training split) is hard for all
  unsupervised models here.
* **Caveat:** the shipped model has only seen simulated VMs. Validate per-group
  calibration and false-alarm rates against representative real telemetry;
  these synthetic results do not establish production accuracy.
