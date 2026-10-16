---
title: Model training and evaluation
description: Train, evaluate, register, and export the sample detector model
---

## Local training

The shipped model is trained on synthetic normal VM telemetry. SMD and NAB
provide separate benchmarks; their models are not used for live scoring.

```bash
uv sync --python 3.11 --extra ml --extra dev
uv run python -m ml.train --dataset synthetic --model iforest --window 30 --out outputs/synthetic-iforest
uv run python -m ml.train --dataset smd --model iforest --out outputs/smd-iforest
uv run python -m ml.evaluate --runs outputs/synthetic-iforest outputs/smd-iforest --report ml/REPORT.md
```

| path | |
|---|---|
| `data/smd.py`, `data/nab.py` | download (cached in git-ignored `data/raw/`) + load as `timestamp, <metrics>, label` |
| `data/synthetic.py` | simulated fleet of 4 GB VMs in the live-metric columns; anomaly-free for training, with injected memory leaks / CPU saturation / disk fills for evaluation |
| `features.py` | `make_features(df, window=30)` - vendored verbatim into `detector/features.py` |
| `models/` | `iforest` (shipped), `sr` (Spectral Residual baseline), `ae` (optional torch MLP AE); `fit(X)` / `score(X) -> [0, 1]` |
| `train.py`, `evaluate.py` | CLI; writes `model.pkl` + `metadata.json` |
| `azureml/` | `submit.py` (submit job to the Bicep-managed workspace/cluster, see `infra/modules/ml.bicep`), `register.py`, `export.py` (-> `detector/model/`) |

## Scoring the shipped artifact

Use the detector's scorer to preserve feature ordering and per-group calibration.
Here `df` contains `timestamp` and the six live metric columns:

```python
from detector.scorer import Scorer

scores = Scorer("detector/model").score(df, computer="vm-app-01")
```

## Azure ML

Azure ML requires `AZURE_SUBSCRIPTION_ID` from the environment setup and an
authenticated Azure CLI session:

```bash
uv run python -m ml.azureml.submit
uv run python -m ml.azureml.register
uv run python -m ml.azureml.export
```

## References

1. [Evaluation results](REPORT.md)
2. [Modeling and evaluation pipeline](../docs/07-modeling-and-evaluation.md)
