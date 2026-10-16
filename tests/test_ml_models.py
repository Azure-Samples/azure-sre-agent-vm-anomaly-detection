import joblib
import numpy as np
import pandas as pd
import pytest

from ml.models.base import apply_calibration, fit_calibration
from ml.models.iforest import GroupedIForestDetector, IForestDetector
from ml.models.sr import SRDetector, saliency_score


def _data(n: int = 400, d: int = 3, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, 1, (n, d))


def test_calibration_maps_quantiles():
    raw = np.linspace(0, 1, 1001)
    cal = fit_calibration(raw)
    s = apply_calibration(np.array([-1.0, cal["q50"], cal["qhi"], 10.0]), cal)
    np.testing.assert_allclose(s, [0.0, 0.0, cal["anchor"], 1.0])


def test_iforest_fit_score():
    X = _data()
    model = IForestDetector(n_estimators=50, max_samples=128).fit(X)
    s = model.score(X)
    assert s.shape == (len(X),) and s.min() >= 0 and s.max() <= 1
    assert (s > 0.8).mean() < 0.01
    outlier = model.score(np.full((1, 3), 8.0))
    assert outlier[0] > 0.8


def test_iforest_one_sided_export(tmp_path):
    cols = ["up", "down", "free"]
    X = pd.DataFrame(_data(), columns=cols)
    model = IForestDetector(n_estimators=50, max_samples=128, directions={"up": 1, "down": -1})
    model.fit(X)
    ref = model.reference  # training medians: values on the "normal" side collapse onto them
    probe = pd.DataFrame(
        [[-8.0, 8.0, 0.0], [8.0, ref[1], 0.0], [ref[0], ref[1], 0.0]], columns=cols
    )
    s = model.score(probe)
    assert s[0] == s[2] < s[1]  # "up" going down / "down" going up are clipped away
    joblib.dump(model.export(), tmp_path / "m.pkl")
    est = joblib.load(tmp_path / "m.pkl")
    raw = -est.score_samples(probe)
    np.testing.assert_allclose(apply_calibration(raw, model.calibration), s)
    with pytest.raises(TypeError):
        IForestDetector(directions={"up": 1}).fit(_data())


def test_sr_detects_spike():
    x = np.sin(np.linspace(0, 20, 500))
    x[300] += 5
    sal = saliency_score(x)
    assert int(np.argmax(sal)) in range(295, 306)
    model = SRDetector().fit(_data(500, 2))
    s = model.score(np.c_[x, x])
    assert s.shape == (500,) and 0 <= s.min() and s.max() <= 1


def test_score_before_fit():
    with pytest.raises(RuntimeError):
        IForestDetector().score(_data(10))


def test_autoencoder_optional():
    pytest.importorskip("torch")
    from ml.models.autoencoder import AEDetector

    X = _data(300, 4)
    s = AEDetector(epochs=2).fit(X).score(X)
    assert s.shape == (300,) and s.min() >= 0 and s.max() <= 1


def test_grouped_iforest_scores_single_dimension_anomalies(tmp_path):
    cols = ["a_up", "a_down", "b_up", "c_up"]
    X = pd.DataFrame(_data(2000, 4), columns=cols)
    groups = {"a": {"a_up": 1, "a_down": -1}, "b": {"b_up": 1}, "c": {"c_up": 1}}
    model = GroupedIForestDetector(groups, n_estimators=50, max_samples=128).fit(X)
    assert model.features == cols
    probe = pd.DataFrame(
        [[0, 0, 0, 0], [0, 0, 8, 0], [0, 0, 0, 8], [0, 0, -8, 0]], columns=cols, dtype=float
    )
    s = model.score(probe)
    assert s[0] < 0.8 and s[1] > 0.8 and s[2] > 0.8 and s[3] < 0.8
    per = model.group_scores(probe)
    assert per["b"][1] > 0.8 and per["c"][1] < 0.8 and per["c"][2] > 0.8
    # exported artefact + group calibrations reproduce score() (the detector/ contract)
    joblib.dump(model.export(), tmp_path / "m.pkl")
    est = joblib.load(tmp_path / "m.pkl")
    meta = model.group_calibrations()
    raw = np.max(
        [
            apply_calibration(
                -est[g].score_samples(probe[meta[g]["features"]]), meta[g]["calibration"]
            )
            for g in est
        ],
        axis=0,
    )
    np.testing.assert_allclose(apply_calibration(raw, model.calibration), s)
    with pytest.raises(TypeError):
        GroupedIForestDetector(groups).fit(_data(10, 4))
