---
title: Online VM anomaly scorer
description: Function timer, model artifact, configuration, and local scoring
---

## Scoring cycle

Azure Functions (Python v2 model) timer app, runs every minute (`0 * * * * *`):

```
Perf (Log Analytics, last 60 min) ─▶ law.pivot_perf ─▶ features.make_features ─▶ scorer.score
                                                                                      │
      VMAnomalyScore_CL  ◀── Logs Ingestion API (DCE / DCR stream) ◀── last 1-min bin ┘
```

| File | Role |
|------|------|
| `function_app.py` | timer trigger; calls `cycle.run_cycle` and logs failures |
| `cycle.py` | one scoring cycle: query → pivot → score last row → upload |
| `law.py` | KQL for `Perf` + pivot into `mem_used_pct, mem_available_mb, swap_used_pct, cpu_pct, disk_used_pct, net_bytes` |
| `features.py` | `make_features(df, window=30)` – identical to `ml/features.py` (parity test) |
| `scorer.py` | loads `model/model.pkl` + `model/metadata.json`, emits `VMAnomalyScore_CL` rows |
| `run_local.py` | `--once` (against LAW) / `--csv file` (offline) |
| `make_placeholder_model.py` | Optional local baseline generator; replaces the output directory's model, so use a separate output path |
| `deploy.sh` | `func azure functionapp publish` or zip deploy with remote build |

## Environment variables / app settings

| Name | Meaning |
|------|---------|
| `LAW_WORKSPACE_ID` | Log Analytics workspace *customer id* (GUID) |
| `DCE_ENDPOINT` | `https://dce-vm-anomaly-….ingest.monitor.azure.com` |
| `DCR_IMMUTABLE_ID` | immutable id of `dcr-vm-anomaly-scores` |
| `DCR_STREAM` | `Custom-VMAnomalyScore_CL` |
| `TARGET_COMPUTER` | `vm-app-01` |
| `SCORE_THRESHOLD` | overrides `metadata.json.threshold` (default 0.8) |
| `LOOKBACK_MINUTES` | optional, default 60 |
| `SETTLE_MINUTES` | optional, default 2 — bins younger than this are rescored next cycle instead of uploaded (Perf counters of one minute arrive at different times) |
| `MODEL_DIR` | optional, default `detector/model` |

Auth is `DefaultAzureCredential`: the Function's system-assigned identity in Azure
(Log Analytics Reader on the LAW, Monitoring Metrics Publisher on the DCR), your
`az login` / service-principal env vars locally.

## Model artefact contract

The shipped `model/model.pkl` is a joblib dictionary of estimators for memory,
CPU, and disk. `model/metadata.json` contains their feature lists, calibration,
feature statistics, input columns, window, threshold, and artifact checksum.

The scorer computes rolling features, calibrates each group's negated
`score_samples` output into `[0, 1]`, and takes the maximum as `Score`.
`IsAnomaly = Score >= threshold`. `Details.groups` and the feature contributions
identify the leading resource and signal. Single-estimator artifacts with
`score_samples` or `score` are also supported.

Model artifacts must come from the trusted, reviewed repository export. The
`model_sha256` in `metadata.json` detects a mismatched or corrupted `model.pkl`
when present; it does **not** authenticate the pickle because someone able to
replace both files can also replace the hash. `joblib.load` can execute code
from an untrusted pickle, so do not deploy artifacts from unreviewed sources.

## Run locally

```bash
uv sync --python 3.11 --extra detector --extra dev
cp detector/local.settings.json.example detector/local.settings.json   # fill in values
uv run python -m detector.run_local --once --dry-run        # score without upload
uv run python -m detector.run_local --once                  # score and upload
uv run python -m detector.run_local --csv some_metrics.csv  # offline
uv run pytest tests/test_detector*.py
```

The CSV uses `timestamp` and the six live metrics listed above, or a raw `Perf`
export. The reviewed model is bundled; generating a replacement is not required.

Or with Core Tools: `cd detector && func start` (needs `local.settings.json` and Azurite).

## Deploy

```bash
detector/deploy.sh                       # finds func-vm-anomaly-* in rg-vm-anomaly-demo
detector/deploy.sh 'your-function-app-name'   # replace with the deployed name
```

Verify: `VMAnomalyScore_CL | order by TimeGenerated desc | take 10` in the LAW.
