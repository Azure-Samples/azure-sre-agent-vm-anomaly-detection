"""Offline tests for detector/: pivot, features, scorer schema, cycle with mocked Azure SDKs."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd
import pytest

from detector import cycle, law, scorer
from detector.features import feature_names, make_features
from detector.make_placeholder_model import main as make_placeholder

METRICS = scorer.METRIC_COLS


# ----------------------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def model_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("model")
    with mock.patch.object(sys, "argv", ["x", "--out", str(out)]):
        make_placeholder()
    return out


def test_model_artifact_integrity_is_verified(model_dir, tmp_path):
    """model.pkl is a pickle: it is only unpickled when it matches metadata['model_sha256']."""
    scorer.Scorer(model_dir)  # placeholder + shipped artefacts carry a matching hash
    scorer.Scorer(scorer.MODEL_DIR)
    bad = tmp_path / "tampered"
    bad.mkdir()
    (bad / "metadata.json").write_text((model_dir / "metadata.json").read_text())
    (bad / "model.pkl").write_bytes((model_dir / "model.pkl").read_bytes() + b"\x00")
    with pytest.raises(ValueError, match="sha256"):
        scorer.Scorer(bad)


@pytest.fixture
def sc(model_dir, monkeypatch):
    monkeypatch.delenv("SCORE_THRESHOLD", raising=False)
    return scorer.Scorer(model_dir)


def fake_perf(n_bins: int = 5, computer: str = "vm-app-01") -> pd.DataFrame:
    t0 = pd.Timestamp("2025-06-01T10:00:00Z")
    rows = []
    for i in range(n_bins):
        ts = t0 + pd.Timedelta(minutes=i, seconds=17)
        rows += [
            (ts, computer, "Memory", "% Used Memory", None, 40 + i),
            (ts, computer, "Memory", "Available MBytes Memory", None, 2000 - 10 * i),
            (ts, computer, "Memory", "% Used Swap Space", None, 1.0),
            (ts, computer, "Processor", "% Processor Time", "_Total", 20.0),
            (ts, computer, "Processor", "% Processor Time", "0", 10.0),
            (ts, computer, "Processor", "% Processor Time", "1", 30.0),
            (ts, computer, "Logical Disk", "% Used Space", "/", 50.0),
            (ts, computer, "Logical Disk", "% Used Space", "/boot", 70.0),
            (ts, computer, "Logical Disk", "% Used Space", "/snap/core22/1", 100.0),
            (ts, computer, "Network", "Total Bytes", "eth0", 1000.0 * (i + 1)),
            (ts, computer, "Network", "Total Bytes", "lo", 500.0 * (i + 1)),
        ]
    return pd.DataFrame(
        rows,
        columns=[
            "TimeGenerated",
            "Computer",
            "ObjectName",
            "CounterName",
            "InstanceName",
            "CounterValue",
        ],
    )


def metrics_frame(n: int = 60, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-06-01", periods=n, freq="1min", tz="UTC"),
            "mem_used_pct": 45 + rng.normal(0, 0.8, n),
            "mem_available_mb": 2200 + rng.normal(0, 20, n),
            "swap_used_pct": np.abs(rng.normal(0.5, 0.3, n)),
            "cpu_pct": 10 + rng.gamma(2, 2, n),
            "disk_used_pct": 40 + rng.normal(0, 0.05, n),
            "net_bytes": rng.lognormal(11, 0.5, n),
        }
    )


# ----------------------------------------------------------------------------- pivot
def test_pivot_perf_columns_and_aggregation():
    out = law.pivot_perf(fake_perf())
    assert list(out.columns) == ["timestamp", "Computer", *METRICS]
    assert len(out) == 5
    assert (out["Computer"] == "vm-app-01").all()
    r = out.iloc[0]
    assert r["cpu_pct"] == 20.0  # _Total only, not mean of cores
    assert r["disk_used_pct"] == 70.0  # max over real filesystems, /snap/* ignored
    assert np.isnan(r["net_bytes"])  # cumulative counter -> first diff undefined
    assert out["net_bytes"].iloc[1:].tolist() == [1500.0] * 4  # summed bytes per bin
    assert r["mem_used_pct"] == 40 and r["mem_available_mb"] == 2000
    assert out["timestamp"].iloc[-1] == pd.Timestamp("2025-06-01T10:04:00Z")


def test_pivot_perf_without_total_uses_mean_and_fills_gaps():
    perf = fake_perf(3)
    perf = perf[perf["InstanceName"] != "_Total"]
    perf = perf[perf["TimeGenerated"] != perf["TimeGenerated"].unique()[1]]  # drop middle bin
    out = law.pivot_perf(perf)
    assert len(out) == 3
    assert out["cpu_pct"].iloc[0] == 20.0  # mean(10, 30)
    assert out["mem_used_pct"].tolist() == [40.0, 40.0, 42.0]  # ffilled gap


def test_pivot_perf_net_total_instance_and_counter_reset():
    perf = fake_perf(3)
    perf = perf[perf["CounterName"] != "Total Bytes"]
    t = perf["TimeGenerated"].unique()
    extra = pd.DataFrame(
        [
            (t[0], "vm-app-01", "Network", "Total Bytes", "total", 5000.0),
            (t[0], "vm-app-01", "Network", "Total Bytes", "eth0", 4000.0),
            (t[1], "vm-app-01", "Network", "Total Bytes", "total", 5300.0),
            (t[1], "vm-app-01", "Network", "Total Bytes", "eth0", 4300.0),
            (t[2], "vm-app-01", "Network", "Total Bytes", "total", 100.0),  # counter reset
            (t[2], "vm-app-01", "Network", "Total Bytes", "eth0", 100.0),
        ],
        columns=perf.columns,
    )
    out = law.pivot_perf(pd.concat([perf, extra]))
    assert out["net_bytes"].iloc[1:].tolist() == [300.0, 0.0]


def test_pivot_perf_uses_individual_instances_when_aggregate_missing_from_bin():
    perf = fake_perf(3)
    timestamps = perf["TimeGenerated"].unique()
    missing = perf["TimeGenerated"] == timestamps[1]
    perf = perf[~(missing & (perf["InstanceName"] == "_Total"))].copy()
    perf.loc[missing & (perf["InstanceName"] == "0"), "CounterValue"] = 40.0
    perf.loc[missing & (perf["InstanceName"] == "1"), "CounterValue"] = 60.0
    totals = pd.DataFrame(
        [
            (timestamps[0], "vm-app-01", "Network", "Total Bytes", "total", 1500.0),
            (timestamps[2], "vm-app-01", "Network", "Total Bytes", "total", 4500.0),
        ],
        columns=perf.columns,
    )
    out = law.pivot_perf(pd.concat([perf, totals]))
    assert out["cpu_pct"].tolist() == [20.0, 50.0, 20.0]
    assert out["net_bytes"].iloc[1:].tolist() == [1500.0, 1500.0]


def test_pivot_perf_empty_and_missing_counter():
    assert law.pivot_perf(pd.DataFrame()).empty
    perf = fake_perf(2)
    perf = perf[perf["CounterName"] != "% Used Swap Space"]
    out = law.pivot_perf(perf)
    assert out["swap_used_pct"].isna().all() and list(out.columns)[2:] == METRICS


def test_perf_query_mentions_contract_counters():
    q = law.perf_query("vm-app-01", 60)
    for c in law.COUNTERS:
        assert f'"{c}"' in q
    assert "ago(60m)" in q and "vm-app-01" in q


# ----------------------------------------------------------------------------- features
def test_features_shape_order_and_determinism():
    df = metrics_frame()
    f1 = make_features(df, window=30)
    f2 = make_features(df.copy(), window=30)
    assert list(f1.columns) == feature_names(METRICS)
    assert f1.shape == (60, 6 * 6)
    pd.testing.assert_frame_equal(f1, f2)
    assert np.isfinite(f1.to_numpy()).all()


def test_features_values():
    df = pd.DataFrame(
        {"timestamp": pd.date_range("2025-01-01", periods=5, freq="1min"), "m": [1.0, 2, 3, 4, 5]}
    )
    f = make_features(df, window=3)
    assert f["m__mean"].tolist() == [1, 1.5, 2, 3, 4]
    assert f["m__slope"].tolist() == pytest.approx([0, 1, 1, 1, 1])
    assert f["m__diff"].tolist() == [0, 1, 1, 1, 1]
    assert f["m__min"].tolist() == [1, 1, 1, 2, 3] and f["m__max"].tolist() == [1, 2, 3, 4, 5]


def test_features_nan_safe():
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=4, freq="1min"),
            "m": [np.nan, 2, np.nan, 4],
        }
    )
    f = make_features(df, window=3)
    assert np.isfinite(f.to_numpy()).all()
    assert f["m__mean"].tolist() == [0, 2, 2, 3]


# ----------------------------------------------------------------------------- scorer
def test_scorer_output_schema(sc):
    out = sc.score(metrics_frame(), computer="vm-app-01")
    assert list(out.columns) == scorer.OUTPUT_COLS
    assert len(out) == 60
    assert out["Score"].between(0, 1).all()
    assert out["IsAnomaly"].dtype == bool
    assert (out["Model"] == "IsolationForest-placeholder").all()
    assert set(out["TopFeature"]) <= set(feature_names(METRICS))
    details = json.loads(out["Details"].iloc[-1])
    assert set(details["metrics"]) == set(METRICS)
    assert set(details["contributions"]) <= set(feature_names(METRICS))
    assert out["TimeGenerated"].iloc[-1].startswith("2025-06-01T00:59:00")


def test_scorer_flags_memory_leak(sc):
    df = metrics_frame(90)
    leak = np.arange(90) >= 45
    df.loc[leak, "mem_used_pct"] += np.linspace(0, 40, leak.sum())
    df.loc[leak, "mem_available_mb"] -= np.linspace(0, 1500, leak.sum())
    df.loc[leak, "swap_used_pct"] += np.linspace(0, 30, leak.sum())
    out = sc.score(df, computer="vm-app-01")
    assert not out["IsAnomaly"].iloc[30:45].any()  # after the rolling-window warm-up
    assert out["IsAnomaly"].iloc[-1]
    assert out["TopFeature"].iloc[-1].startswith(("mem_", "swap_"))


def test_scorer_threshold_env_override(model_dir, monkeypatch):
    monkeypatch.setenv("SCORE_THRESHOLD", "0.0")
    out = scorer.Scorer(model_dir).score(metrics_frame(5))
    assert out["IsAnomaly"].all()
    assert (out["Computer"] == "unknown").all()


def test_scorer_empty(sc):
    assert sc.score(pd.DataFrame(columns=["timestamp", *METRICS])).empty


def test_shipped_model_serving_matches_training_formula(monkeypatch):
    """detector/ must reproduce ml.models.base.apply_calibration on the committed artefact."""
    from ml.models.base import apply_calibration

    monkeypatch.delenv("SCORE_THRESHOLD", raising=False)
    s = scorer.Scorer(scorer.MODEL_DIR)
    assert s.calibration and "feature_stats" in s.meta and s.feature_stats
    df = metrics_frame(80)
    df["mem_used_pct"] = 40 + np.linspace(0, 20, 80)  # steady leak -> high score
    df["mem_available_mb"] = 4000 - np.linspace(0, 1500, 80)
    out = s.score(df)
    feats = scorer.make_features(df[["timestamp", *METRICS]], window=s.window)[s.features]
    if isinstance(s.model, dict):  # {group: forest}: Score = max of per-group calibrated scores
        assert set(s.model) == set(s.groups) == {"memory", "cpu", "disk"}
        raw = np.max(
            [
                apply_calibration(
                    -est.score_samples(feats[s.groups[g]["features"]]), s.groups[g]["calibration"]
                )
                for g, est in s.model.items()
            ],
            axis=0,
        )
    else:
        raw = -s.model.score_samples(feats)
    expected = apply_calibration(raw, s.calibration)
    assert np.allclose(out["Score"].to_numpy(), np.round(expected, 6), atol=1e-6)
    assert out["Score"].iloc[-1] > 0.8 and out["IsAnomaly"].iloc[-1]
    assert out["TopFeature"].iloc[-1] in {"mem_used_pct__slope", "mem_available_mb__slope"}
    details = json.loads(out["Details"].iloc[-1])
    assert set(details) >= {"metrics", "contributions"}
    assert max(details["contributions"].values()) >= 0.8
    if isinstance(s.model, dict):
        assert max(details["groups"], key=details["groups"].get) == "memory"
        assert details["groups"]["cpu"] < 0.8 and details["groups"]["disk"] < 0.8


@pytest.mark.parametrize(
    ("column", "ramp", "group", "top"),
    [
        ("cpu_pct", lambda n: np.full(n, 97.0), "cpu", "cpu_pct__min"),
        ("disk_used_pct", lambda n: 40 + np.linspace(0, 30, n), "disk", "disk_used_pct__slope"),
    ],
)
def test_shipped_model_flags_non_memory_anomalies(monkeypatch, column, ramp, group, top):
    """Alerting covers every resource class, not just memory: a pinned CPU and a filling disk."""
    monkeypatch.delenv("SCORE_THRESHOLD", raising=False)
    s = scorer.Scorer(scorer.MODEL_DIR)
    if not isinstance(s.model, dict):
        pytest.skip("single-forest artefact")
    df = metrics_frame(80)
    df.loc[40:, column] = ramp(40)
    out = s.score(df)
    assert not out["IsAnomaly"].iloc[30:40].any()
    assert out["IsAnomaly"].iloc[-1] and out["TopFeature"].iloc[-1] == top
    assert (
        max(
            json.loads(out["Details"].iloc[-1])["groups"],
            key=lambda g: json.loads(out["Details"].iloc[-1])["groups"][g],
        )
        == group
    )


# ----------------------------------------------------------------------------- cycle
ENV = {
    "LAW_WORKSPACE_ID": "ws",
    "DCE_ENDPOINT": "https://dce.example",
    "DCR_IMMUTABLE_ID": "dcr-1",
    "DCR_STREAM": "Custom-VMAnomalyScore_CL",
    "TARGET_COMPUTER": "vm-app-01",
}


def _fake_query_client(perf: pd.DataFrame, last_scored: str | None = None):
    from azure.monitor.query import LogsQueryStatus

    table = SimpleNamespace(rows=perf.values.tolist(), columns=list(perf.columns))
    resp = SimpleNamespace(status=LogsQueryStatus.SUCCESS, tables=[table] if len(perf) else [])
    client = mock.MagicMock()

    def query(_ws, q, timespan=None):
        if q.startswith("VMAnomalyScore_CL"):
            row = [[pd.Timestamp(last_scored)]] if last_scored else [[None]]
            return SimpleNamespace(
                status=LogsQueryStatus.SUCCESS, tables=[SimpleNamespace(rows=row, columns=["Last"])]
            )
        return resp

    client.query_workspace.side_effect = query
    return client


def test_run_cycle_uploads_recent_unsent_bins(model_dir, monkeypatch):
    monkeypatch.setattr(scorer, "_scorer", scorer.Scorer(model_dir))
    monkeypatch.setattr(cycle, "_last_uploaded", {})
    ingest = mock.MagicMock()
    with (
        mock.patch(
            "azure.monitor.query.LogsQueryClient", return_value=_fake_query_client(fake_perf(40))
        ),
        mock.patch("azure.monitor.ingestion.LogsIngestionClient", return_value=ingest),
    ):
        out = cycle.run_cycle(ENV, cred=object())
    assert len(out) == cycle.RECENT_BINS
    ingest.upload.assert_called_once()
    kw = ingest.upload.call_args.kwargs
    assert kw["rule_id"] == "dcr-1" and kw["stream_name"] == "Custom-VMAnomalyScore_CL"
    row = kw["logs"][-1]
    assert set(row) == set(scorer.OUTPUT_COLS)
    assert row["Computer"] == "vm-app-01" and row["TimeGenerated"].startswith("2025-06-01T10:39:00")

    # second cycle with the same data: nothing new -> no upload
    with (
        mock.patch(
            "azure.monitor.query.LogsQueryClient", return_value=_fake_query_client(fake_perf(40))
        ),
        mock.patch("azure.monitor.ingestion.LogsIngestionClient", return_value=ingest),
    ):
        again = cycle.run_cycle(ENV, cred=object())
    assert again.empty and ingest.upload.call_count == 1


def test_run_cycle_cold_start_seeds_cursor_from_law(model_dir, monkeypatch):
    """A recycled worker must not re-upload bins already present in VMAnomalyScore_CL."""
    monkeypatch.setattr(scorer, "_scorer", scorer.Scorer(model_dir))
    monkeypatch.setattr(cycle, "_last_uploaded", {})
    ingest = mock.MagicMock()
    client = _fake_query_client(fake_perf(40), last_scored="2025-06-01T10:37:00Z")
    with (
        mock.patch("azure.monitor.query.LogsQueryClient", return_value=client),
        mock.patch("azure.monitor.ingestion.LogsIngestionClient", return_value=ingest),
    ):
        out = cycle.run_cycle(ENV, cred=object())
    assert list(out["TimeGenerated"].str[:19]) == ["2025-06-01T10:38:00", "2025-06-01T10:39:00"]
    assert cycle._last_uploaded["vm-app-01"].startswith("2025-06-01T10:39:00")


def test_run_cycle_empty_data_and_missing_settings(model_dir, monkeypatch):
    monkeypatch.setattr(scorer, "_scorer", scorer.Scorer(model_dir))
    with mock.patch(
        "azure.monitor.query.LogsQueryClient", return_value=_fake_query_client(fake_perf(0))
    ):
        assert cycle.run_cycle(ENV, cred=object()) is None
    assert cycle.run_cycle({}, cred=object()) is None


def test_function_app_never_raises(monkeypatch):
    from detector import function_app

    monkeypatch.setattr(function_app, "run_cycle", mock.Mock(side_effect=RuntimeError("boom")))
    function_app.score_vm.build().get_user_function()(SimpleNamespace(past_due=False))


def test_pending_rows_holds_back_unsettled_bins(monkeypatch):
    monkeypatch.setattr(cycle, "_last_uploaded", {"vm-app-01": "2025-06-01T10:35:00Z"})
    scored = pd.DataFrame(
        {"TimeGenerated": [f"2025-06-01T10:{m}:00Z" for m in range(30, 40)], "Score": 0.1}
    )
    out = cycle.pending_rows(scored, "vm-app-01", watermark=pd.Timestamp("2025-06-01T10:37:00Z"))
    assert list(out["TimeGenerated"].str[11:16]) == ["10:36", "10:37"]


def test_pending_rows_drains_backlog_oldest_first(monkeypatch):
    cursor = {"vm-app-01": "2025-06-01T10:32:00Z"}
    monkeypatch.setattr(cycle, "_last_uploaded", cursor)
    scored = pd.DataFrame(
        {"TimeGenerated": [f"2025-06-01T10:{m}:00Z" for m in range(30, 45)], "Score": 0.1}
    )
    watermark = pd.Timestamp("2025-06-01T10:44:00Z")
    first = cycle.pending_rows(scored, "vm-app-01", watermark)
    assert list(first["TimeGenerated"].str[11:16]) == [
        "10:33",
        "10:34",
        "10:35",
        "10:36",
        "10:37",
    ]
    cursor["vm-app-01"] = first["TimeGenerated"].iloc[-1]
    next_batch = cycle.pending_rows(scored, "vm-app-01", watermark)
    assert list(next_batch["TimeGenerated"].str[11:16]) == [
        "10:38",
        "10:39",
        "10:40",
        "10:41",
        "10:42",
    ]
