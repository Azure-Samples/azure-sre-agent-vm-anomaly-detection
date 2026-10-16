"""Write a placeholder detector/model/{model.pkl,metadata.json} (contract format).

Fits an IsolationForest on *normal* VM telemetry so the detector can be developed/deployed
before the Azure ML artefact from ml/ lands. Do not commit the output.

    python -m detector.make_placeholder_model [--out detector/model] [--threshold 0.8]
    python -m detector.make_placeholder_model --law [--minutes 180]   # fit on the live VM's
        healthy Perf baseline from Log Analytics (same env vars as run_local)
    python -m detector.make_placeholder_model --csv metrics.csv
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from .features import feature_names, make_features
from .law import fetch_perf, pivot_perf
from .scorer import METRIC_COLS

WINDOW = 30


def synthetic_normal(n: int = 4000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    daily = np.sin(2 * np.pi * t / 1440)
    mem = 45 + 3 * daily + rng.normal(0, 0.8, n)
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=n, freq="1min", tz="UTC"),
            "mem_used_pct": mem,
            "mem_available_mb": (100 - mem) / 100 * 4096 + rng.normal(0, 20, n),
            "swap_used_pct": np.clip(rng.normal(0.5, 0.3, n), 0, None),
            "cpu_pct": np.clip(10 + 5 * daily + rng.gamma(2, 2, n), 0, 100),
            "disk_used_pct": 40 + t / n * 0.5 + rng.normal(0, 0.05, n),
            "net_bytes": np.clip(rng.lognormal(11, 0.5, n), 0, None),
        }
    )
    return df


def live_baseline(minutes: int) -> tuple[pd.DataFrame, str]:
    from azure.identity import DefaultAzureCredential
    from azure.monitor.query import LogsQueryClient

    from .run_local import load_env

    env = load_env()
    computer = env.get("TARGET_COMPUTER", "vm-app-01")
    client = LogsQueryClient(DefaultAzureCredential(exclude_interactive_browser_credential=True))
    perf = fetch_perf(client, env["LAW_WORKSPACE_ID"], computer, minutes)
    if perf.empty:
        raise SystemExit(f"no Perf rows for {computer} in the last {minutes} min")
    df = pivot_perf(perf).drop(columns="Computer")
    return df, f"live-perf:{computer}:{minutes}m"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent / "model"))
    ap.add_argument("--threshold", type=float, default=0.8)
    ap.add_argument("--law", action="store_true", help="fit on live Perf from Log Analytics")
    ap.add_argument("--minutes", type=int, default=180, help="lookback for --law")
    ap.add_argument("--csv", help="fit on a pivoted metrics CSV")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.law:
        df, source = live_baseline(args.minutes)
    elif args.csv:
        df = pd.read_csv(args.csv, parse_dates=["timestamp"])
        source = f"csv:{args.csv}"
    else:
        df, source = synthetic_normal(), "synthetic-normal"
    df = df.ffill().bfill().fillna(0.0)
    feats = make_features(df[["timestamp", *METRIC_COLS]], window=WINDOW)
    feats = feats.iloc[min(WINDOW, max(len(feats) - 10, 0)) :]
    names = feature_names(METRIC_COLS)
    X = feats[names].to_numpy(float)
    model = IsolationForest(n_estimators=200, contamination="auto", random_state=0).fit(X)

    # same contract as ml/models/base.py: median -> 0, 99.9 % quantile -> threshold
    raw = -model.score_samples(X)
    q50, qhi = float(np.median(raw)), float(np.quantile(raw, 0.999))
    joblib.dump(model, out / "model.pkl")
    meta = {
        "model": "IsolationForest-placeholder",
        "features": names,
        "window": WINDOW,
        "threshold": args.threshold,
        "trained_on": f"{source} ({len(feats)} rows, detector/make_placeholder_model.py)",
        "metrics": {},
        "calibration": {"q50": q50, "qhi": max(qhi, q50 + 1e-12), "anchor": args.threshold},
        "feature_stats": {
            n: {
                "q50": float(np.median(X[:, j])),
                "qhi": float(np.quantile(X[:, j], 0.999)),
                "direction": 1,
            }
            for j, n in enumerate(names)
        },
        "created": datetime.now(UTC).isoformat(),
        "model_sha256": hashlib.sha256((out / "model.pkl").read_bytes()).hexdigest(),
    }
    (out / "metadata.json").write_text(json.dumps(meta, indent=2))
    print(f"wrote {out}/model.pkl and metadata.json ({len(names)} features)")


if __name__ == "__main__":
    main()
