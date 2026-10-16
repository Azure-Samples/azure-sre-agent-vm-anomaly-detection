"""One scoring cycle: LAW -> pivot -> score -> upload not-yet-uploaded recent bins."""

from __future__ import annotations

import logging
from collections.abc import Mapping

import pandas as pd

try:
    from .law import fetch_last_scored, fetch_perf, pivot_perf
    from .scorer import get_scorer
except ImportError:
    from law import fetch_last_scored, fetch_perf, pivot_perf  # type: ignore[no-redef]
    from scorer import get_scorer  # type: ignore[no-redef]

log = logging.getLogger("detector")

REQUIRED = ("LAW_WORKSPACE_ID", "DCE_ENDPOINT", "DCR_IMMUTABLE_ID", "DCR_STREAM")

# computer -> TimeGenerated of the last uploaded bin. Seeded from VMAnomalyScore_CL on a cold
# start so a recycled worker does not re-upload bins an earlier worker already sent.
_last_uploaded: dict[str, str] = {}
RECENT_BINS = 5  # Perf lands with a few minutes of lag, so emit every bin we haven't sent yet
# Counters of one minute arrive at different times; a bin is only final once it is older than
# this. Younger bins are rescored on the next cycle instead of being uploaded incomplete.
SETTLE_MINUTES = 2


def _utc(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return t.tz_convert("UTC").tz_localize(None) if t.tzinfo else t


def credential():
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


def score_frame(metrics: pd.DataFrame, computer: str, last_only: bool = True) -> pd.DataFrame:
    """Score pivoted metrics; returns VMAnomalyScore_CL rows (last bin only by default)."""
    if metrics.empty:
        return pd.DataFrame()
    scored = get_scorer().score(metrics, computer=computer)
    return scored.tail(1) if last_only else scored


def pending_rows(
    scored: pd.DataFrame, computer: str, watermark: pd.Timestamp | None = None
) -> pd.DataFrame:
    """Up to RECENT_BINS settled rows not uploaded yet for this computer."""
    ts = scored["TimeGenerated"].map(_utc)
    if watermark is not None:
        scored, ts = scored[ts <= _utc(watermark)], ts[ts <= _utc(watermark)]
    last = _last_uploaded.get(computer)
    if last is None:
        return scored.tail(RECENT_BINS)
    return scored[ts > _utc(last)].head(RECENT_BINS)


def upload(rows: list[dict], env: Mapping[str, str], cred=None) -> None:
    from azure.monitor.ingestion import LogsIngestionClient

    client = LogsIngestionClient(endpoint=env["DCE_ENDPOINT"], credential=cred or credential())
    client.upload(rule_id=env["DCR_IMMUTABLE_ID"], stream_name=env["DCR_STREAM"], logs=rows)
    log.info("uploaded %d row(s) to %s", len(rows), env["DCR_STREAM"])


def run_cycle(env: Mapping[str, str], cred=None, dry_run: bool = False) -> pd.DataFrame | None:
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        log.error("missing app settings: %s", ", ".join(missing))
        return None
    from azure.monitor.query import LogsQueryClient

    computer = env.get("TARGET_COMPUTER", "vm-app-01")
    minutes = int(env.get("LOOKBACK_MINUTES", "60"))
    cred = cred or credential()
    logs = LogsQueryClient(cred)
    if computer not in _last_uploaded:
        last = fetch_last_scored(logs, env["LAW_WORKSPACE_ID"], computer, minutes)
        if last:
            _last_uploaded[computer] = last
            log.info("cursor seeded from VMAnomalyScore_CL: %s", last)
    perf = fetch_perf(logs, env["LAW_WORKSPACE_ID"], computer, minutes)
    if perf.empty:
        log.warning("no Perf rows for %s in the last %d min", computer, minutes)
        return None
    metrics = pivot_perf(perf)
    log.info("%d Perf rows -> %d 1-min bins", len(perf), len(metrics))
    scored = score_frame(metrics, computer, last_only=False)
    if scored.empty:
        return None
    settle = int(env.get("SETTLE_MINUTES", SETTLE_MINUTES))
    watermark = pd.Timestamp.now(tz="UTC").floor("min") - pd.Timedelta(minutes=settle)
    pending = pending_rows(scored, computer, watermark)
    if dry_run:
        log.info("dry run, not uploading:\n%s", pending.to_string())
    elif pending.empty:
        log.info("no new bins since %s, skipping", _last_uploaded.get(computer))
    else:
        upload(pending.to_dict(orient="records"), env, cred)
        _last_uploaded[computer] = str(pending["TimeGenerated"].iloc[-1])
    return pending
