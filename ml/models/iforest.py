"""Isolation Forest on windowed features - the default (shipped) model.

``directions`` optionally makes features one-sided before the forest: ``{column: +1}`` keeps only
values above the training median (everything below collapses onto it), ``{column: -1}`` only
values below. For the live model this means "memory / disk growing" or "CPU pinned high" is
anomalous while the drop after a restart / rollback, or a VM that idles lower than the training
fleet, is not. The clip is a plain ``FunctionTransformer(np.clip)`` so the exported artefact is
pure sklearn/numpy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer

from ml.models.base import CAL_ANCHOR, CAL_QUANTILE, Detector


def _one_sided(
    columns: list[str], directions: dict[str, int], reference: np.ndarray
) -> FunctionTransformer:
    lo = np.array(
        [reference[i] if directions.get(c, 0) > 0 else -np.inf for i, c in enumerate(columns)]
    )
    hi = np.array(
        [reference[i] if directions.get(c, 0) < 0 else np.inf for i, c in enumerate(columns)]
    )
    return FunctionTransformer(
        np.clip, kw_args={"a_min": lo, "a_max": hi}, validate=True, feature_names_out="one-to-one"
    )


class IForestDetector(Detector):
    name = "iforest"
    input_kind = "features"

    def __init__(
        self,
        n_estimators: int = 200,
        max_samples: int | str = 512,
        directions: dict[str, int] | None = None,
        seed: int = 0,
    ):
        super().__init__()
        self.directions = directions or {}
        self.reference: np.ndarray | None = None  # per-column clip point (training median)
        self.forest = IsolationForest(
            n_estimators=n_estimators, max_samples=max_samples, random_state=seed
        )
        self.estimator: Pipeline | IsolationForest = self.forest

    def _fit(self, X) -> None:
        if self.directions:
            if not isinstance(X, pd.DataFrame):
                raise TypeError("directions need a DataFrame with named feature columns")
            self.reference = np.median(X.to_numpy(float), axis=0)
            clip = _one_sided(list(X.columns), self.directions, self.reference)
            self.estimator = Pipeline([("one_sided", clip), ("iforest", self.forest)])
        else:
            X = X if isinstance(X, pd.DataFrame) else np.asarray(X, dtype=float)
        self.estimator.fit(X)

    def raw_score(self, X) -> np.ndarray:
        X = X if isinstance(X, pd.DataFrame) else np.asarray(X, dtype=float)
        return -self.estimator.score_samples(X)

    def export(self) -> Pipeline | IsolationForest:
        """Pure-sklearn artefact for detector/: ``raw = -estimator.score_samples(X[features])``."""
        return self.estimator


class GroupedIForestDetector(Detector):
    """One one-sided :class:`IForestDetector` per resource group; ``score = max`` over groups.

    A single forest over all features under-scores anomalies that live in one dimension (a
    pinned CPU, a filling disk) because most random splits look at unrelated features. Scoring
    each group against its own normal range and taking the maximum keeps every resource class
    on the same "beyond the 99.9 % quantile = 0.8" scale, and the winning group names the
    affected resource. ``groups`` = ``{group: {feature: direction}}``; the exported artefact is
    ``{group: sklearn Pipeline}`` plus per-group calibrations (see :meth:`group_calibrations`).
    """

    name = "iforest-grouped"
    input_kind = "features"

    def __init__(self, groups: dict[str, dict[str, int]], seed: int = 0, **kw):
        super().__init__()
        self.groups = groups
        self.detectors = {
            g: IForestDetector(directions=d, seed=seed, **kw) for g, d in groups.items()
        }

    @property
    def features(self) -> list[str]:
        return [f for d in self.groups.values() for f in d]

    def _fit(self, X) -> None:
        if not isinstance(X, pd.DataFrame):
            raise TypeError("groups need a DataFrame with named feature columns")
        for g, det in self.detectors.items():
            det.fit(X[list(self.groups[g])])

    def group_scores(self, X: pd.DataFrame) -> dict[str, np.ndarray]:
        return {g: det.score(X[list(self.groups[g])]) for g, det in self.detectors.items()}

    def raw_score(self, X) -> np.ndarray:
        return np.max(list(self.group_scores(X).values()), axis=0)

    def fit(self, X) -> GroupedIForestDetector:
        self._fit(X)
        # group scores are already calibrated to [0, 1]; the top level is the identity map
        self.calibration = {
            "q50": 0.0,
            "qhi": CAL_ANCHOR,
            "anchor": CAL_ANCHOR,
            "quantile": CAL_QUANTILE,
        }
        return self

    def group_calibrations(self) -> dict[str, dict]:
        return {
            g: {"features": list(self.groups[g]), "calibration": det.calibration}
            for g, det in self.detectors.items()
        }

    def export(self) -> dict[str, Pipeline | IsolationForest]:
        """``{group: estimator}``; detector/ scores ``max_g calibrate_g(-est_g.score_samples(X[f_g]))``."""
        return {g: det.export() for g, det in self.detectors.items()}
