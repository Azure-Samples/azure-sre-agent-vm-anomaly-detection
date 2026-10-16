"""Common detector interface: ``fit(X)`` then ``score(X) -> np.ndarray`` in [0, 1].

Raw anomaly scores (higher = more anomalous) are calibrated against the training distribution:
the training median maps to 0 and the training ``CAL_QUANTILE`` quantile maps to
``CAL_ANCHOR`` (0.8 = the fleet ``SCORE_THRESHOLD``), linearly, clipped to [0, 1]. So a score
above 0.8 means "more anomalous than 99.9 % of the (normal) training windows".
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CAL_QUANTILE = 0.999
CAL_ANCHOR = 0.8


def as_array(X) -> np.ndarray:
    if isinstance(X, pd.DataFrame):
        return X.to_numpy(dtype=float)
    return np.asarray(X, dtype=float)


def fit_calibration(raw_train: np.ndarray) -> dict[str, float]:
    raw_train = np.asarray(raw_train, dtype=float)
    q50 = float(np.quantile(raw_train, 0.5))
    qhi = float(np.quantile(raw_train, CAL_QUANTILE))
    if qhi - q50 < 1e-12:
        qhi = q50 + 1e-12
    return {"q50": q50, "qhi": qhi, "anchor": CAL_ANCHOR, "quantile": CAL_QUANTILE}


def apply_calibration(raw: np.ndarray, cal: dict[str, float]) -> np.ndarray:
    """``clip(anchor * (raw - q50) / (qhi - q50), 0, 1)`` - also used by detector/."""
    z = cal["anchor"] * (np.asarray(raw, dtype=float) - cal["q50"]) / (cal["qhi"] - cal["q50"])
    return np.clip(z, 0.0, 1.0)


class Detector:
    name = "base"

    def __init__(self) -> None:
        self.calibration: dict[str, float] | None = None

    def raw_score(self, X) -> np.ndarray:
        raise NotImplementedError

    def _fit(self, X) -> None:
        raise NotImplementedError

    def fit(self, X) -> Detector:
        self._fit(X)
        self.calibration = fit_calibration(self.raw_score(X))
        return self

    def score(self, X) -> np.ndarray:
        if self.calibration is None:
            raise RuntimeError("fit() first")
        return apply_calibration(self.raw_score(X), self.calibration)
