"""Train + evaluate an anomaly detector and write ``model.pkl`` + ``metadata.json``.

    python -m ml.train --dataset {smd,nab,synthetic} --model {iforest,sr,ae} --window 30 \
        --out outputs/synthetic-iforest

* ``synthetic`` - one pooled model over several simulated VMs in the live-metric columns,
  trained on anomaly-free series, evaluated on series with injected memory leaks, CPU
  saturations and disk fills. This is the
  model that ships to detector/ (``model.pkl`` is ``{group: sklearn Pipeline}``, one-sided
  clip -> ``IsolationForest`` per resource group; ``Score = max_g calibrate_g(-pipe_g.score_samples(X[f_g]))``).
* ``smd`` / ``nab`` - one model per series (SMD machine / NAB file), evaluated on the labelled
  part; ``model.pkl`` is ``{series: estimator}``. Used for the evaluation report only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

from ml import evaluate as ev
from ml.data import nab, smd, synthetic
from ml.features import feature_names, make_features, metric_columns
from ml.models.base import Detector
from ml.models.iforest import GroupedIForestDetector, IForestDetector
from ml.models.sr import SRDetector

try:  # torch is optional (not in the Azure ML env)
    from ml.models.autoencoder import AEDetector
except ImportError:  # pragma: no cover
    AEDetector = None

DEFAULT_THRESHOLD = 0.8
NAB_PROBATION = 0.15

# Live model: one one-sided forest per resource group, Score = max over groups. Absolute levels
# (memory baseline, disk size) differ between VMs and a restart / rollback legitimately *drops*
# memory or disk, so the model sees how fast memory / swap / disk are *growing* over the window
# plus sustained CPU saturation (window minimum) - direction +1 = increases count, -1 =
# decreases count. ``net_bytes`` is collected and shown to the SRE Agent but is not a model
# input: its scale is per-NIC/per-VM and does not transfer without a per-VM baseline.
LIVE_GROUPS = {
    "memory": {"mem_used_pct__slope": 1, "mem_available_mb__slope": -1, "swap_used_pct__slope": 1},
    "cpu": {"cpu_pct__min": 1},
    "disk": {"disk_used_pct__slope": 1},
}
LIVE_DIRECTIONS = {f: d for g in LIVE_GROUPS.values() for f, d in g.items()}
LIVE_FEATURES = list(LIVE_DIRECTIONS)
LIVE_TRAIN_SERIES = 24


def build_model(
    name: str, directions: dict[str, int] | None = None, groups: dict | None = None
) -> Detector:
    if name == "iforest" and groups:
        return GroupedIForestDetector(groups)
    if name == "iforest":
        return IForestDetector(directions=directions)
    if name == "sr":
        return SRDetector()
    if name == "ae":
        if AEDetector is None:
            raise RuntimeError("model 'ae' needs torch: pip install torch")
        return AEDetector()
    raise ValueError(f"unknown model {name}")


def load_dataset(dataset: str, args) -> tuple[list, list, bool, str]:
    """Return ``(train_series, test_series, pooled, description)``; series = (name, df)."""
    if dataset == "synthetic":
        train = synthetic.load(n_series=args.series or LIVE_TRAIN_SERIES, n_leaks=0, seed=args.seed)
        test = synthetic.load(
            n_series=4, n_leaks=2, n_cpu_saturations=1, n_disk_fills=1, seed=args.seed + 1
        )
        desc = (
            f"synthetic live-metric VMs: {len(train)} anomaly-free train series x "
            f"{synthetic.MINUTES_PER_DAY * 3} min, {len(test)} test series with 2 memory "
            f"leaks (10-20 MB/min on 4 GB), 1 CPU saturation and 1 disk fill each"
        )
        return list(train.items()), list(test.items()), True, desc
    if dataset == "smd":
        machines = args.machines or smd.DEFAULT_MACHINES
        pairs = [(m, *smd.load(m)) for m in machines]
        desc = f"SMD (OmniAnomaly) machines {', '.join(machines)}"
        return [(m, tr) for m, tr, _ in pairs], [(m, te) for m, _, te in pairs], False, desc
    if dataset == "nab":
        series = nab.load_all()
        if args.series:
            series = dict(list(series.items())[: args.series])
        train, test = [], []
        for name, df in series.items():
            cut = int(len(df) * NAB_PROBATION)
            train.append((name, df.iloc[:cut].reset_index(drop=True)))
            test.append((name, df.iloc[cut:].reset_index(drop=True)))
        return train, test, False, f"NAB {nab.CATEGORY} ({len(series)} series)"
    raise ValueError(f"unknown dataset {dataset}")


def inputs(df: pd.DataFrame, model: Detector, window: int, features: list[str] | None):
    metrics = metric_columns(df)
    if model.input_kind == "raw":
        return df[metrics].astype(float)
    feats = make_features(df[["timestamp", *metrics]], window=window)
    return feats[features] if features else feats


def fit_rows(df: pd.DataFrame, window: int) -> np.ndarray:
    mask = np.arange(len(df)) >= window - 1
    if "label" in df:
        mask &= df["label"].to_numpy() == 0
    return mask


def feature_quantiles(X: pd.DataFrame, directions: dict[str, int]) -> dict[str, dict[str, float]]:
    """Per-feature training median / 99.9 % quantile of the one-sided value ``direction * x``.

    detector/ uses them to attribute a score to features (contribution_j = how far past the
    normal range feature j is, in the anomalous direction)."""
    stats = {}
    for c in X.columns:
        v = directions.get(c, 1) * X[c].to_numpy(dtype=float)
        v = v[np.isfinite(v)]
        stats[c] = {
            "q50": float(np.quantile(v, 0.5)),
            "qhi": float(np.quantile(v, 0.999)),
            "direction": int(directions.get(c, 1)),
        }
    return stats


def static_baseline(test: list, warm: int, column: str, threshold: float, sign: int) -> dict:
    """Static rule ``sign * column > sign * threshold`` (e.g. mem_used_pct > 90)."""
    per = {
        name: ev.evaluate(
            sign * df[column].to_numpy()[warm:], df["label"].to_numpy()[warm:], sign * threshold
        )
        for name, df in test
    }
    op = ">" if sign > 0 else "<"
    return {**ev.aggregate(per), "rule": f"{column} {op} {threshold:g}"}


def alert_predictions(scores: np.ndarray, threshold: float) -> np.ndarray:
    return ev.k_of_n(scores >= threshold, 3, 5).astype(float)


def run(args) -> dict:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    train, test, pooled, desc = load_dataset(args.dataset, args)
    live = args.dataset == "synthetic" and args.model != "sr"
    features = LIVE_FEATURES if live else None
    directions = LIVE_DIRECTIONS if live else None
    groups = LIVE_GROUPS if live else None

    per_series: dict[str, dict] = {}
    feature_stats: dict[str, dict[str, float]] = {}
    best: dict[str, dict] = {}
    alert: dict[str, dict] = {}
    calibration: dict = {}
    group_meta: dict = {}
    artefact: object
    test_scores: dict[str, np.ndarray] = {}

    if pooled:
        model = build_model(args.model, directions, groups)
        X = pd.concat(
            [
                inputs(df, model, args.window, features)[fit_rows(df, args.window)]
                for _, df in train
            ],
            ignore_index=True,
        )
        model.fit(X)
        for name, df in test:
            test_scores[name] = model.score(inputs(df, model, args.window, features))
        calibration = model.calibration
        artefact = model.export() if hasattr(model, "export") else model
        if isinstance(X, pd.DataFrame):
            feature_stats = feature_quantiles(X, directions or {})
        if isinstance(model, GroupedIForestDetector):
            group_meta = model.group_calibrations()
    else:
        artefacts = {}
        for (name, tr), (_, te) in zip(train, test):
            model = build_model(args.model, directions)
            model.fit(inputs(tr, model, args.window, features)[fit_rows(tr, args.window)])
            test_scores[name] = model.score(inputs(te, model, args.window, features))
            calibration[name] = model.calibration
            artefacts[name] = model.export() if hasattr(model, "export") else model
        artefact = artefacts

    for name, df in test:
        warm = args.window - 1
        y = df["label"].to_numpy()[warm:]
        s = test_scores[name][warm:]
        per_series[name] = ev.evaluate(s, y, args.threshold)
        best[name] = ev.evaluate(s, y, ev.best_threshold(s, y))
        alert_pred = alert_predictions(s, args.threshold)
        alert[name] = ev.evaluate(alert_pred, y, 0.5)

    baselines = {f"{args.model} + 3-of-5 alert rule": {**ev.aggregate(alert), "rule": "3 of 5 min"}}
    if args.dataset == "synthetic":
        warm = args.window - 1
        baselines["static threshold"] = static_baseline(test, warm, "mem_used_pct", 90, 1)
        baselines["static metric alert"] = static_baseline(test, warm, "mem_available_mb", 200, -1)

    metrics = {
        "per_series": per_series,
        "mean": ev.aggregate(per_series),
        "best_f1_mean": ev.aggregate(best),
        "baselines": baselines,
    }
    first = test[0][1]
    feat_list = features or (
        feature_names(metric_columns(first)) if args.model != "sr" else metric_columns(first)
    )
    metadata = {
        "model": args.model,
        "features": list(feat_list),
        "window": args.window,
        "threshold": args.threshold,
        "trained_on": desc,
        "metrics": metrics,
        "dataset": args.dataset,
        "input_columns": metric_columns(first),
        "per_series": not pooled,
        "directions": directions or {},
        "groups": group_meta,
        "calibration": calibration,
        "feature_stats": feature_stats,
        "score_formula": (
            "F = make_features(df, window); "
            "raw = max_g clip(anchor_g * (-model[g].score_samples(F[groups[g].features]) - q50_g) "
            "/ (qhi_g - q50_g), 0, 1) if groups else -model.score_samples(F[features]); "
            "score = clip(anchor * (raw - q50) / (qhi - q50), 0, 1)"
        ),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "versions": {
            "python": platform.python_version(),
            "sklearn": sklearn.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
    }
    joblib.dump(artefact, out / "model.pkl", compress=3)
    metadata["model_sha256"] = hashlib.sha256((out / "model.pkl").read_bytes()).hexdigest()
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2, default=float))
    pd.DataFrame(
        {"timestamp": first["timestamp"], "score": test_scores[test[0][0]], "label": first["label"]}
        | {c: first[c] for c in metric_columns(first)[:6]}
    ).to_csv(out / "scores_sample.csv", index=False)
    return metadata


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dataset", choices=["smd", "nab", "synthetic"], required=True)
    ap.add_argument("--model", choices=["iforest", "sr", "ae"], default="iforest")
    ap.add_argument("--window", type=int, default=30)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--machines", nargs="*", default=None, help="SMD machines (default: 4)")
    ap.add_argument("--series", type=int, default=None, help="number of series (synthetic/nab)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="outputs/")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    md = run(parse_args(argv))
    m = md["metrics"]["mean"]
    print(
        f"{md['dataset']}/{md['model']}: F1={m['f1']:.3f} PA-F1={m['pa_f1']:.3f} "
        f"detected={m['segments_detected']}/{m['segments']} delay={m['mean_delay']}"
    )


if __name__ == "__main__":
    main()
