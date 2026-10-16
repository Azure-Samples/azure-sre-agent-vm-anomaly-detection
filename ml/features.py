"""Windowed feature engineering shared by ml/ (training) and detector/ (live scoring).

Pure numpy/pandas on purpose: detector/ vendors a byte-identical copy
(``detector/features.py``), kept in sync by ``tests/test_feature_parity.py``.

Contract: ``make_features(df, window=30) -> DataFrame``

* input: a DataFrame with an optional ``timestamp`` column, optional ``label`` column and
  one or more numeric metric columns, one row per sample (1 min for the live VM);
* output: same index as ``df``, one block of columns per metric column (in input order)::

      <metric>__mean, <metric>__std, <metric>__slope, <metric>__min, <metric>__max, <metric>__diff

  where the first five are trailing rolling statistics over ``window`` rows and ``diff`` is the
  first difference. ``slope`` is the least-squares slope in metric units per row (per minute
  at 1-min resolution). NaNs in the input are skipped by the rolling statistics; any value that
  cannot be computed (e.g. an all-NaN window, the std of one sample) is returned as 0.0.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

NON_METRIC_COLUMNS = ("timestamp", "label")
STATS = ("mean", "std", "slope", "min", "max", "diff")


def metric_columns(df: pd.DataFrame) -> list[str]:
    """Metric columns of ``df`` in input order (everything except timestamp/label)."""
    return [c for c in df.columns if c not in NON_METRIC_COLUMNS]


def feature_names(metrics: list[str]) -> list[str]:
    """Deterministic feature column names produced by :func:`make_features`."""
    return [f"{m}__{s}" for m in metrics for s in STATS]


def _rolling_slope(y: pd.Series, window: int) -> pd.Series:
    """Least-squares slope of ``y`` against row position over a trailing window, NaN-aware."""
    values = y.to_numpy(dtype=float)
    valid = ~np.isnan(values)
    t = np.arange(len(values), dtype=float)
    t = t - t.mean() if len(t) else t
    yv = np.where(valid, values, 0.0)
    m = valid.astype(float)

    def rsum(a: np.ndarray) -> np.ndarray:
        return pd.Series(a).rolling(window, min_periods=1).sum().to_numpy()

    n = rsum(m)
    st = rsum(m * t)
    sy = rsum(yv)
    stt = rsum(m * t * t)
    sty = rsum(m * t * yv)
    denom = n * stt - st * st
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = (n * sty - st * sy) / denom
    slope[(n < 2) | (np.abs(denom) < 1e-9)] = np.nan
    return pd.Series(slope, index=y.index)


def make_features(df: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    if window < 2:
        raise ValueError("window must be >= 2")
    metrics = metric_columns(df)
    blocks: dict[str, pd.Series] = {}
    for col in metrics:
        y = pd.to_numeric(df[col], errors="coerce").astype(float)
        roll = y.rolling(window, min_periods=1)
        blocks[f"{col}__mean"] = roll.mean()
        blocks[f"{col}__std"] = roll.std(ddof=0)
        blocks[f"{col}__slope"] = _rolling_slope(y, window)
        blocks[f"{col}__min"] = roll.min()
        blocks[f"{col}__max"] = roll.max()
        blocks[f"{col}__diff"] = y.ffill().diff()
    out = pd.DataFrame(blocks, index=df.index, columns=feature_names(metrics))
    return out.replace([np.inf, -np.inf], np.nan).fillna(0.0).astype(float)
