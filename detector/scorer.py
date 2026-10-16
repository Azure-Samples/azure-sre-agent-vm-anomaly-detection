"""Load detector/model/{model.pkl,metadata.json} and score a metrics DataFrame.

Output schema == VMAnomalyScore_CL:
    TimeGenerated, Computer, Score, IsAnomaly, Model, TopFeature, Details

Scoring mirrors ml/models/base.py exactly (train/serve parity, see tests):
    F     = make_features(df, window)
    raw   = -model.score_samples(F[features])                       # single forest
    raw   = max_g calibrate_g(-model[g].score_samples(F[f_g]))      # {group: forest} artefact
    score = clip(anchor * (raw - q50) / (qhi - q50), 0, 1)
Details.groups carries the per-group scores so the SRE Agent sees which resource (memory,
cpu, disk, ...) drove the anomaly before it looks at TopFeature.
Per-feature contributions (for RCA) use metadata["feature_stats"]: how far feature j is past
its normal training range in the anomalous direction, same linear scale as the score.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

try:
    from .features import make_features
except ImportError:  # Azure Functions host imports function_app.py as a top-level module
    from features import make_features  # type: ignore[no-redef]

log = logging.getLogger(__name__)

MODEL_DIR = Path(os.environ.get("MODEL_DIR", Path(__file__).parent / "model"))
METRIC_COLS = [
    "mem_used_pct",
    "mem_available_mb",
    "swap_used_pct",
    "cpu_pct",
    "disk_used_pct",
    "net_bytes",
]
OUTPUT_COLS = ["TimeGenerated", "Computer", "Score", "IsAnomaly", "Model", "TopFeature", "Details"]


def apply_calibration(raw: np.ndarray, cal: dict[str, float]) -> np.ndarray:
    z = cal["anchor"] * (np.asarray(raw, dtype=float) - cal["q50"]) / (cal["qhi"] - cal["q50"])
    return np.clip(z, 0.0, 1.0)


def load_model(model_dir: Path):
    """Check a trusted model's supplied hash for mismatches before loading it."""
    meta = json.loads((model_dir / "metadata.json").read_text())
    blob = (model_dir / "model.pkl").read_bytes()
    expected = meta.get("model_sha256")
    actual = hashlib.sha256(blob).hexdigest()
    if expected and actual != expected:
        raise ValueError(f"model.pkl sha256 {actual} != metadata model_sha256 {expected}")
    if not expected:
        log.warning("metadata.json has no model_sha256; loading unverified model.pkl")
    return joblib.load(model_dir / "model.pkl"), meta


class Scorer:
    def __init__(self, model_dir: Path | str = MODEL_DIR):
        model_dir = Path(model_dir)
        self.model, self.meta = load_model(model_dir)
        self.features: list[str] = list(self.meta["features"])
        self.window: int = int(self.meta.get("window", 30))
        self.name: str = str(self.meta.get("model", type(self.model).__name__))
        env_thr = os.environ.get("SCORE_THRESHOLD")
        self.threshold = float(env_thr) if env_thr else float(self.meta.get("threshold", 0.8))
        self.calibration: dict[str, float] | None = self.meta.get("calibration") or None
        if self.calibration and "q50" not in self.calibration:  # per-series artefact
            self.calibration = None
        self.feature_stats: dict[str, dict[str, float]] = self.meta.get("feature_stats") or {}
        self.groups: dict[str, dict] = self.meta.get("groups") or {}
        if isinstance(self.model, dict) and not self.groups:
            raise ValueError("model.pkl is a {group: estimator} dict but metadata has no groups")

    def group_scores(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        return {
            g: apply_calibration(
                -np.asarray(est.score_samples(X[self.groups[g]["features"]])),
                self.groups[g]["calibration"],
            )
            for g, est in self.model.items()
        }

    def _raw(self, X: pd.DataFrame) -> np.ndarray:
        if isinstance(self.model, dict):
            return np.max(list(self.group_scores(X).values()), axis=0)
        if hasattr(self.model, "score_samples"):
            return -np.asarray(self.model.score_samples(X), float)
        if hasattr(self.model, "score"):  # ml.models.base.Detector (already calibrated)
            return np.asarray(self.model.score(X), float)
        raise TypeError(f"unsupported model artefact {type(self.model).__name__}")

    def _normalise(self, raw: np.ndarray) -> np.ndarray:
        if self.calibration:
            return apply_calibration(raw, self.calibration)
        return np.clip(raw, 0.0, 1.0)

    def contributions(self, x: np.ndarray) -> dict[str, float]:
        """Feature -> excess over its normal range (>=0.8 means beyond the 99.9 % quantile)."""
        out: dict[str, float] = {}
        for j, name in enumerate(self.features):
            st = self.feature_stats.get(name)
            if not st or st["qhi"] - st["q50"] <= 0:
                continue
            v = st.get("direction", 1) * float(x[j])
            out[name] = round(max(0.0, 0.8 * (v - st["q50"]) / (st["qhi"] - st["q50"])), 4)
        return out

    def score(self, df: pd.DataFrame, computer: str | None = None) -> pd.DataFrame:
        """`df` has columns timestamp, <metric cols> (and optionally Computer).

        Returns one row per input row."""
        if df.empty:
            return pd.DataFrame(columns=OUTPUT_COLS)
        df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)
        metrics = [c for c in df.columns if c not in ("timestamp", "Computer")]
        feats = make_features(df[["timestamp", *metrics]], window=self.window)
        X = feats.reindex(columns=self.features, fill_value=0.0).to_numpy(dtype=float)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        Xf = pd.DataFrame(X, columns=self.features)
        score = self._normalise(self._raw(Xf))
        groups = self.group_scores(Xf) if isinstance(self.model, dict) else {}
        rows = []
        for i in range(len(df)):
            contrib = self.contributions(X[i])
            top = max(contrib, key=contrib.get) if contrib else "n/a"
            details = {
                "metrics": {c: _json_num(df.at[i, c]) for c in metrics},
                "contributions": dict(sorted(contrib.items(), key=lambda kv: -kv[1])),
            }
            if groups:
                details["groups"] = {g: float(round(s[i], 4)) for g, s in groups.items()}
            comp = computer or (df.at[i, "Computer"] if "Computer" in df.columns else "unknown")
            rows.append(
                {
                    "TimeGenerated": pd.Timestamp(df.at[i, "timestamp"]).isoformat(),
                    "Computer": comp,
                    "Score": float(round(score[i], 6)),
                    "IsAnomaly": bool(score[i] >= self.threshold),
                    "Model": self.name,
                    "TopFeature": top,
                    "Details": json.dumps(details, sort_keys=True),
                }
            )
        return pd.DataFrame(rows, columns=OUTPUT_COLS)


def _json_num(v):
    if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
        return None
    return float(v)


_scorer: Scorer | None = None


def get_scorer() -> Scorer:
    global _scorer
    if _scorer is None:
        _scorer = Scorer()
        log.info("loaded model %s (threshold=%.3f)", _scorer.name, _scorer.threshold)
    return _scorer


def score(df: pd.DataFrame, computer: str | None = None) -> pd.DataFrame:
    return get_scorer().score(df, computer)
