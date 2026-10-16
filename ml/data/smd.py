"""OmniAnomaly Server Machine Dataset (SMD): 28 machines x 38 metrics, 1-min, labelled test half.

Source: https://github.com/NetManAIOps/OmniAnomaly/tree/master/ServerMachineDataset
Files are normalised to [0, 1] and carry no timestamps; a synthetic 1-min ``timestamp`` is added.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.data.download import RAW_DIR, fetch

BASE_URL = "https://raw.githubusercontent.com/NetManAIOps/OmniAnomaly/master/ServerMachineDataset"
SUBDIRS = ("train", "test", "test_label", "interpretation_label")
N_METRICS = 38
MACHINES = (
    [f"machine-1-{i}" for i in range(1, 9)]
    + [f"machine-2-{i}" for i in range(1, 10)]
    + [f"machine-3-{i}" for i in range(1, 12)]
)
DEFAULT_MACHINES = ["machine-1-1", "machine-1-6", "machine-2-1", "machine-3-7"]
METRIC_COLUMNS = [f"m{i:02d}" for i in range(N_METRICS)]


def download(machine: str) -> dict[str, str]:
    """Download train/test/test_label/interpretation_label for one machine (cached)."""
    paths = {}
    for sub in SUBDIRS:
        dest = RAW_DIR / "smd" / sub / f"{machine}.txt"
        paths[sub] = str(fetch(f"{BASE_URL}/{sub}/{machine}.txt", dest))
    return paths


def _frame(values: np.ndarray, labels: np.ndarray, start: str) -> pd.DataFrame:
    df = pd.DataFrame(values, columns=METRIC_COLUMNS)
    df.insert(0, "timestamp", pd.date_range(start, periods=len(df), freq="1min"))
    df["label"] = labels.astype(int)
    return df


def load(machine: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return ``(train, test)`` DataFrames with ``timestamp``, ``m00..m37`` and ``label``."""
    paths = download(machine)
    train = np.loadtxt(paths["train"], delimiter=",", dtype=float)
    test = np.loadtxt(paths["test"], delimiter=",", dtype=float)
    test_label = np.loadtxt(paths["test_label"], dtype=float)
    train_df = _frame(train, np.zeros(len(train)), "2019-01-01T00:00:00Z")
    test_start = train_df["timestamp"].iloc[-1] + pd.Timedelta(minutes=1)
    return train_df, _frame(test, test_label, str(test_start))


def interpretation(machine: str) -> list[tuple[int, int, list[int]]]:
    """Anomaly segments ``(start, end, [1-based metric dims])`` from interpretation_label."""
    out = []
    with open(download(machine)["interpretation_label"]) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            span, dims = line.split(":")
            a, b = span.split("-")
            out.append((int(a), int(b), [int(d) for d in dims.split(",") if d]))
    return out
