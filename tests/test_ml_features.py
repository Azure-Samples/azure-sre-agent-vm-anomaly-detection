import numpy as np
import pandas as pd
import pytest

from ml.data import synthetic
from ml.features import STATS, feature_names, make_features


def _frame(n: int = 120, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="min", tz="UTC"),
            "b_metric": rng.normal(50, 5, n),
            "a_metric": np.arange(n, dtype=float),
        }
    )


def test_shape_and_column_order():
    df = _frame()
    out = make_features(df, window=10)
    assert out.shape == (len(df), 2 * len(STATS))
    assert list(out.columns) == feature_names(["b_metric", "a_metric"])
    assert list(out.columns)[:6] == [f"b_metric__{s}" for s in STATS]
    assert out.index.equals(df.index)


def test_deterministic():
    df = _frame()
    pd.testing.assert_frame_equal(make_features(df), make_features(df.copy()))


def test_values_on_linear_ramp():
    out = make_features(_frame(), window=10)
    tail = out.iloc[20:]
    np.testing.assert_allclose(tail["a_metric__slope"], 1.0)
    np.testing.assert_allclose(tail["a_metric__diff"], 1.0)
    np.testing.assert_allclose(tail["a_metric__max"] - tail["a_metric__min"], 9.0)


def test_nan_safe():
    df = _frame()
    df.loc[5:15, "b_metric"] = np.nan
    df.loc[40, "a_metric"] = np.nan
    out = make_features(df, window=10)
    assert np.isfinite(out.to_numpy()).all()


def test_label_and_timestamp_ignored():
    df = _frame()
    df["label"] = 1
    assert list(make_features(df).columns) == feature_names(["b_metric", "a_metric"])


def test_window_validation():
    with pytest.raises(ValueError):
        make_features(_frame(), window=1)


def test_synthetic_contract():
    df = synthetic.generate(n_minutes=2 * synthetic.MINUTES_PER_DAY, n_leaks=1, seed=3)
    assert list(df.columns) == ["timestamp", *synthetic.LIVE_COLUMNS, "label"]
    assert (df["timestamp"].diff().dropna() == pd.Timedelta(minutes=1)).all()
    leak = df[df["label"] == 1]
    assert len(leak) > 0
    growth = np.polyfit(np.arange(len(leak)), 4096 - leak["mem_available_mb"], 1)[0]
    assert 5 < growth < 30  # MB/min on a 4 GB VM
    pd.testing.assert_frame_equal(df, synthetic.generate(2 * 1440, n_leaks=1, seed=3))
