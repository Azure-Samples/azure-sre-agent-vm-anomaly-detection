"""Log Analytics access: KQL for `Perf` and pivot into the live metric columns."""

from __future__ import annotations

import logging
from datetime import timedelta

import pandas as pd

log = logging.getLogger(__name__)

# counter name -> (metric column, aggregation across instances)
COUNTERS = {
    "% Used Memory": ("mem_used_pct", "mean"),
    "Available MBytes Memory": ("mem_available_mb", "mean"),
    "% Used Swap Space": ("swap_used_pct", "mean"),
    "% Processor Time": ("cpu_pct", "mean"),
    "% Used Space": ("disk_used_pct", "max"),
    "Total Bytes": ("net_bytes", "sum"),
}
METRIC_COLS = [v[0] for v in COUNTERS.values()]
# read-only / virtual mounts that always report 0 or 100 % used
PSEUDO_FS = ("/snap", "/dev", "/run", "/sys", "/proc", "/boot/efi")

PERF_QUERY = """
Perf
| where TimeGenerated > ago({minutes}m)
| where Computer == "{computer}" or Computer startswith "{computer}."
| where CounterName in ({counters})
| project TimeGenerated, Computer, ObjectName, CounterName, InstanceName, CounterValue
"""


def perf_query(computer: str, minutes: int = 60) -> str:
    counters = ", ".join(f'"{c}"' for c in COUNTERS)
    return PERF_QUERY.format(minutes=minutes, computer=computer, counters=counters).strip()


def pivot_perf(perf: pd.DataFrame, freq: str = "1min") -> pd.DataFrame:
    """Pivot raw Perf rows into DataFrame[timestamp, Computer, <metric cols>] at 1-min bins.

    cpu_pct: mean over instances (or `_Total` only when present),
    disk_used_pct: max over real filesystems (pseudo mounts such as /snap/* dropped),
    net_bytes: sum over interfaces (or `total` only when present), converted from the
    cumulative counter AMA reports into bytes per bin; memory: mean.
    Missing bins are forward-filled; missing counters become NaN columns.
    """
    if perf is None or perf.empty:
        return pd.DataFrame(columns=["timestamp", "Computer", *METRIC_COLS])
    df = perf.copy()
    df["TimeGenerated"] = pd.to_datetime(df["TimeGenerated"], utc=True)
    df["CounterValue"] = pd.to_numeric(df["CounterValue"], errors="coerce")
    df["bin"] = df["TimeGenerated"].dt.floor(freq)
    df["InstanceName"] = df["InstanceName"].fillna("")
    cpu = df["CounterName"] == "% Processor Time"
    cpu_total = df["InstanceName"] == "_Total"
    cpu_total_bins = df.loc[cpu & cpu_total, "bin"]
    df = df[~cpu | ~df["bin"].isin(cpu_total_bins) | cpu_total]
    net = df["CounterName"] == "Total Bytes"
    net_total = df["InstanceName"] == "total"
    net_total_bins = df.loc[net & net_total, "bin"]
    df = df[~net | ~df["bin"].isin(net_total_bins) | net_total]
    disk = df["CounterName"] == "% Used Space"
    pseudo = df["InstanceName"].str.startswith(PSEUDO_FS, na=False)
    if (disk & ~pseudo).any():
        df = df[~disk | ~pseudo]
    computer = str(df["Computer"].iloc[0]).split(".")[0]

    series = {}
    for counter, (col, agg) in COUNTERS.items():
        sub = df[df["CounterName"] == counter]
        if sub.empty:
            continue
        # aggregate across instances inside each bin (using latest sample per instance)
        per_inst = (
            sub.sort_values("TimeGenerated").groupby(["bin", "InstanceName"])["CounterValue"].last()
        )
        series[col] = per_inst.groupby(level="bin").agg(agg)
    if not series:
        return pd.DataFrame(columns=["timestamp", "Computer", *METRIC_COLS])
    wide = pd.DataFrame(series)
    full_idx = pd.date_range(wide.index.min(), wide.index.max(), freq=freq)
    wide = wide.reindex(full_idx).ffill()
    if "net_bytes" in wide:  # AMA reports a cumulative byte counter -> bytes per bin
        wide["net_bytes"] = wide["net_bytes"].diff().clip(lower=0)
    wide = wide.reindex(columns=METRIC_COLS)
    wide.index.name = "timestamp"
    out = wide.reset_index()
    out.insert(1, "Computer", computer)
    return out


def _tables(resp) -> list:
    from azure.monitor.query import LogsQueryStatus

    if resp.status == LogsQueryStatus.PARTIAL:
        log.warning("partial LAW result: %s", resp.partial_error)
        return resp.partial_data
    return resp.tables


def fetch_last_scored(client, workspace_id: str, computer: str, minutes: int = 60) -> str | None:
    """ISO TimeGenerated of the newest VMAnomalyScore_CL row already in LAW (dedup cursor)."""
    q = f'VMAnomalyScore_CL | where Computer == "{computer}" | summarize Last=max(TimeGenerated)'
    resp = client.query_workspace(workspace_id, q, timespan=timedelta(minutes=minutes))
    tables = _tables(resp)
    if not tables or not tables[0].rows or tables[0].rows[0][0] is None:
        return None
    return pd.Timestamp(tables[0].rows[0][0]).isoformat()


def table_to_frame(table) -> pd.DataFrame:
    """azure.monitor.query LogsTable -> DataFrame."""
    return pd.DataFrame(data=table.rows, columns=table.columns)


def fetch_perf(client, workspace_id: str, computer: str, minutes: int = 60) -> pd.DataFrame:
    """Run the Perf query with an azure.monitor.query LogsQueryClient."""
    resp = client.query_workspace(
        workspace_id, perf_query(computer, minutes), timespan=timedelta(minutes=minutes)
    )
    tables = _tables(resp)
    if not tables:
        return pd.DataFrame()
    return table_to_frame(tables[0])
