import numpy as np
import pytest

from ml import evaluate as ev
from ml.train import alert_predictions

LABELS = np.array([0, 0, 1, 1, 1, 0, 0, 1, 1, 0])


def test_segments():
    assert ev.segments(LABELS) == [(2, 5), (7, 9)]
    assert ev.segments([0, 0]) == []
    assert ev.segments([1, 1]) == [(0, 2)]


def test_pointwise_prf():
    pred = np.array([0, 1, 0, 1, 0, 0, 0, 0, 0, 0])
    p, r, f1 = ev.prf(pred, LABELS)
    assert p == pytest.approx(0.5)
    assert r == pytest.approx(0.2)
    assert f1 == pytest.approx(2 * 0.5 * 0.2 / 0.7)
    assert ev.prf(np.zeros(10), LABELS) == (0.0, 0.0, 0.0)


def test_point_adjust():
    pred = np.array([0, 1, 0, 1, 0, 0, 0, 0, 0, 0])
    adj = ev.point_adjust(pred, LABELS)
    np.testing.assert_array_equal(adj, [0, 1, 1, 1, 1, 0, 0, 0, 0, 0])
    p, r, _ = ev.prf(adj, LABELS)
    assert p == pytest.approx(0.75) and r == pytest.approx(0.6)


def test_delay_and_false_alarms():
    pred = np.array([1, 0, 0, 0, 1, 0, 1, 0, 1, 0])
    assert ev.detection_delays(pred, LABELS) == [2, 1]
    assert ev.detection_delays(np.zeros(10), LABELS) == [None, None]
    assert ev.false_alarm_events(pred, LABELS) == 2


def test_k_of_n():
    pred = np.array([1, 1, 0, 1, 0, 0, 1, 0, 0, 0])
    np.testing.assert_array_equal(ev.k_of_n(pred, 3, 5), [0, 0, 0, 1, 1, 0, 0, 0, 0, 0])


def test_evaluate_and_best_threshold():
    scores = np.where(LABELS == 1, 0.9, 0.1)
    m = ev.evaluate(scores, LABELS, 0.8)
    assert m["f1"] == 1.0 and m["pa_f1"] == 1.0
    assert m["segments_detected"] == 2 and m["mean_delay"] == 0.0
    assert m["false_alarm_events"] == 0
    assert 0.1 <= ev.best_threshold(scores, LABELS) < 0.9


def test_evaluate_includes_threshold_score():
    m = ev.evaluate([0.8, 0.79], [1, 0], 0.8)
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0


def test_alert_predictions_include_threshold_score():
    np.testing.assert_array_equal(
        alert_predictions(np.array([0.8, 0.8, 0.79, 0.8]), 0.8), [0, 0, 0, 1]
    )


def test_results_table():
    m = ev.evaluate(np.where(LABELS == 1, 0.9, 0.1), LABELS, 0.8)
    md = {
        "dataset": "toy",
        "model": "iforest",
        "threshold": 0.8,
        "metrics": {"per_series": {"a": m}, "mean": ev.aggregate({"a": m})},
    }
    table = ev.results_table([md])
    assert table.startswith("| dataset |")
    assert "| toy | iforest | 0.80 (fixed) | 1 | 1.000 |" in table
