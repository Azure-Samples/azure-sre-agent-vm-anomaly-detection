"""Numenta Anomaly Benchmark - realAWSCloudwatch (EC2/RDS/ELB CloudWatch metrics, 5-min).

Source: https://github.com/numenta/NAB/tree/master/data/realAWSCloudwatch and
labels/combined_windows.json. ``label`` is 1 inside a NAB anomaly window.
"""

from __future__ import annotations

import json

import pandas as pd

from ml.data.download import RAW_DIR, fetch

BASE_URL = "https://raw.githubusercontent.com/numenta/NAB/master"
CATEGORY = "realAWSCloudwatch"
FILES = [
    "ec2_cpu_utilization_24ae8d.csv",
    "ec2_cpu_utilization_53ea38.csv",
    "ec2_cpu_utilization_5f5533.csv",
    "ec2_cpu_utilization_77c1ca.csv",
    "ec2_cpu_utilization_825cc2.csv",
    "ec2_cpu_utilization_ac20cd.csv",
    "ec2_cpu_utilization_c6585a.csv",
    "ec2_cpu_utilization_fe7f93.csv",
    "ec2_disk_write_bytes_1ef3de.csv",
    "ec2_disk_write_bytes_c0d644.csv",
    "ec2_network_in_257a54.csv",
    "ec2_network_in_5abac7.csv",
    "elb_request_count_8c0756.csv",
    "grok_asg_anomaly.csv",
    "iio_us-east-1_i-a2eb1cd9_NetworkIn.csv",
    "rds_cpu_utilization_cc0c53.csv",
    "rds_cpu_utilization_e47b3b.csv",
]


def download() -> None:
    fetch(f"{BASE_URL}/labels/combined_windows.json", RAW_DIR / "nab" / "combined_windows.json")
    for name in FILES:
        fetch(f"{BASE_URL}/data/{CATEGORY}/{name}", RAW_DIR / "nab" / CATEGORY / name)


def windows() -> dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]]:
    download()
    with open(RAW_DIR / "nab" / "combined_windows.json") as fh:
        raw = json.load(fh)
    return {
        key.split("/", 1)[1]: [(pd.Timestamp(a), pd.Timestamp(b)) for a, b in spans]
        for key, spans in raw.items()
        if key.startswith(CATEGORY + "/")
    }


def load(name: str) -> pd.DataFrame:
    """One series as ``timestamp, value, label``."""
    download()
    df = pd.read_csv(RAW_DIR / "nab" / CATEGORY / name, parse_dates=["timestamp"])
    label = pd.Series(0, index=df.index)
    for a, b in windows().get(name, []):
        label[(df["timestamp"] >= a) & (df["timestamp"] <= b)] = 1
    df["label"] = label.astype(int)
    return df


def load_all() -> dict[str, pd.DataFrame]:
    return {name.removesuffix(".csv"): load(name) for name in FILES}
