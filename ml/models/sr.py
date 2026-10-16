"""Spectral Residual saliency (Ren et al., KDD 2019) - unsupervised univariate baseline.

Applied per metric column on the raw series; the multivariate score is the max over columns.
"""

from __future__ import annotations

import numpy as np

from ml.models.base import Detector, as_array

EPS = 1e-8


def _moving_average(x: np.ndarray, n: int) -> np.ndarray:
    return np.convolve(x, np.ones(n) / n, mode="same") if n > 1 else x


def _trailing_mean(x: np.ndarray, n: int) -> np.ndarray:
    c = np.cumsum(np.insert(x, 0, 0.0))
    idx = np.arange(1, len(x) + 1)
    lo = np.maximum(idx - n, 0)
    return (c[idx] - c[lo]) / (idx - lo)


def _extend(x: np.ndarray, m: int = 5, k: int = 5) -> np.ndarray:
    """Append ``k`` extrapolated points so the last real points are not at the FFT edge."""
    if len(x) <= m:
        return np.concatenate([x, np.repeat(x[-1], k)])
    g = np.mean([(x[-1] - x[-1 - i]) / i for i in range(1, m + 1)])
    return np.concatenate([x, np.repeat(x[-m] + g * m, k)])


def saliency_score(x: np.ndarray, amp_window: int = 3, score_window: int = 21) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 4 or np.nanstd(x) < EPS:
        return np.zeros(n)
    x = np.where(np.isnan(x), np.nanmean(x), x)
    xe = _extend(x)
    spec = np.fft.fft(xe)
    amp = np.abs(spec)
    log_amp = np.log(amp + EPS)
    residual = log_amp - _moving_average(log_amp, amp_window)
    sal = np.abs(np.fft.ifft(np.exp(residual) * spec / (amp + EPS)))[:n]
    base = _trailing_mean(sal, score_window)
    return np.clip((sal - base) / (base + EPS), 0.0, None)


class SRDetector(Detector):
    name = "sr"
    input_kind = "raw"

    def __init__(self, amp_window: int = 3, score_window: int = 21):
        super().__init__()
        self.amp_window = amp_window
        self.score_window = score_window

    def _fit(self, X) -> None:
        return None

    def raw_score(self, X) -> np.ndarray:
        A = as_array(X)
        if A.ndim == 1:
            A = A[:, None]
        cols = [
            saliency_score(A[:, j], self.amp_window, self.score_window) for j in range(A.shape[1])
        ]
        return np.max(np.vstack(cols), axis=0)
