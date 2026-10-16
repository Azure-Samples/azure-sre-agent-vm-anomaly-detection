"""Evaluation metrics + REPORT.md generation.

Metrics: point-wise precision/recall/F1, point-adjusted F1 (Xu et al., WWW 2018: if any point
of a labelled segment is flagged, the whole segment counts as detected), detection delay
(rows from segment start to first flag), and false-alarm events (flagged runs outside labels).

    python -m ml.evaluate --runs outputs/synthetic-iforest outputs/smd-iforest ... \
        --report ml/REPORT.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def segments(labels) -> list[tuple[int, int]]:
    """``[start, end)`` index ranges where ``labels`` is truthy."""
    y = np.asarray(labels).astype(bool).astype(int)
    d = np.diff(np.concatenate([[0], y, [0]]))
    return list(zip(np.nonzero(d == 1)[0].tolist(), np.nonzero(d == -1)[0].tolist()))


def prf(pred, labels) -> tuple[float, float, float]:
    p = np.asarray(pred).astype(bool)
    y = np.asarray(labels).astype(bool)
    tp = int((p & y).sum())
    precision = tp / p.sum() if p.sum() else 0.0
    recall = tp / y.sum() if y.sum() else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return float(precision), float(recall), float(f1)


def point_adjust(pred, labels) -> np.ndarray:
    p = np.asarray(pred).astype(bool).copy()
    for a, b in segments(labels):
        if p[a:b].any():
            p[a:b] = True
    return p


def detection_delays(pred, labels) -> list[int | None]:
    """Per labelled segment: rows until the first flag inside it (``None`` = missed)."""
    p = np.asarray(pred).astype(bool)
    out: list[int | None] = []
    for a, b in segments(labels):
        hits = np.nonzero(p[a:b])[0]
        out.append(int(hits[0]) if len(hits) else None)
    return out


def false_alarm_events(pred, labels) -> int:
    y = np.asarray(labels).astype(bool)
    return sum(1 for a, b in segments(pred) if not y[a:b].any())


def k_of_n(pred, k: int = 3, n: int = 5) -> np.ndarray:
    """Alert-rule smoothing: flag t if >= k of the last n points are flagged."""
    p = np.asarray(pred).astype(float)
    c = np.convolve(p, np.ones(n), mode="full")[: len(p)]
    return c >= k


def evaluate(scores, labels, threshold: float) -> dict:
    scores = np.asarray(scores, dtype=float)
    labels = np.asarray(labels).astype(int)
    pred = scores >= threshold
    p, r, f1 = prf(pred, labels)
    pap, par, paf1 = prf(point_adjust(pred, labels), labels)
    delays = detection_delays(pred, labels)
    found = [d for d in delays if d is not None]
    return {
        "threshold": float(threshold),
        "precision": p,
        "recall": r,
        "f1": f1,
        "pa_precision": pap,
        "pa_recall": par,
        "pa_f1": paf1,
        "segments": len(delays),
        "segments_detected": len(found),
        "mean_delay": float(np.mean(found)) if found else None,
        "false_alarm_events": false_alarm_events(pred, labels),
        "n": len(labels),
        "anomaly_ratio": float(labels.mean()) if len(labels) else 0.0,
    }


def best_threshold(scores, labels, metric: str = "f1", grid: int = 200) -> float:
    scores = np.asarray(scores, dtype=float)
    cands = np.unique(
        np.r_[np.quantile(scores, np.linspace(0.5, 0.9999, grid)), np.linspace(0, 0.99, 100)]
    )
    best, best_t = -1.0, float(cands[-1]) if len(cands) else 0.5
    for t in cands:
        v = evaluate(scores, labels, t)[metric]
        if v > best:
            best, best_t = v, float(t)
    return best_t


def aggregate(results: dict[str, dict]) -> dict:
    """Mean of P/R/F1 over series that contain anomalies; counts are summed over all series."""
    keys = ["precision", "recall", "f1", "pa_precision", "pa_recall", "pa_f1"]
    labelled = [r for r in results.values() if r["segments"]] or list(results.values())
    out = {k: float(np.mean([r[k] for r in labelled])) for k in keys}
    delays = [r["mean_delay"] for r in results.values() if r["mean_delay"] is not None]
    out["mean_delay"] = float(np.mean(delays)) if delays else None
    for k in ("segments", "segments_detected", "false_alarm_events", "n"):
        out[k] = int(sum(r[k] for r in results.values()))
    return out


def _fmt(v, digits: int = 3) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


ROW_HEADER = (
    "| dataset | model | threshold | series | P | R | F1 | PA-F1 | segments detected "
    "| mean delay (rows) | false-alarm events |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|\n"
)


def _row(dataset: str, model: str, thr_label: str, n_series: int, m: dict) -> str:
    return (
        f"| {dataset} | {model} | {thr_label} | {n_series} | {_fmt(m['precision'])} "
        f"| {_fmt(m['recall'])} | {_fmt(m['f1'])} | {_fmt(m['pa_f1'])} "
        f"| {m['segments_detected']}/{m['segments']} | {_fmt(m['mean_delay'], 1)} "
        f"| {m['false_alarm_events']} |\n"
    )


def results_table(runs: list[dict]) -> str:
    """Markdown table from a list of metadata.json dicts written by ml.train."""
    out = ROW_HEADER
    seen: set[tuple[str, str]] = set()
    for md in runs:
        ds, model = md["dataset"], md["model"]
        n_series = len(md["metrics"]["per_series"])
        out += _row(ds, model, f"{md['threshold']:.2f} (fixed)", n_series, md["metrics"]["mean"])
        if "best_f1_mean" in md["metrics"]:
            out += _row(ds, model, "best-F1 (oracle)", n_series, md["metrics"]["best_f1_mean"])
        for name, m in md["metrics"].get("baselines", {}).items():
            if (ds, name) not in seen:
                seen.add((ds, name))
                out += _row(ds, name, m.get("rule", "static"), n_series, m)
    return out


def per_series_table(runs: list[dict], datasets: tuple[str, ...] = ("smd",)) -> str:
    """Fixed-threshold metrics per series (e.g. per SMD machine)."""
    out = ROW_HEADER.replace("| series |", "| series name |").replace("threshold", "thr", 1)
    for md in runs:
        if md["dataset"] not in datasets:
            continue
        for name, m in md["metrics"]["per_series"].items():
            out += _row(md["dataset"], md["model"], f"{md['threshold']:.2f}", name, m)
    return out


def _replace_block(text: str, tag: str, body: str) -> str:
    start, end = f"<!-- {tag} -->", f"<!-- /{tag} -->"
    if start in text and end in text:
        head, rest = text.split(start, 1)
        _, tail = rest.split(end, 1)
        return f"{head}{start}\n{body}{end}{tail}"
    return f"{text}\n{start}\n{body}{end}\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--runs", nargs="+", required=True, help="output dirs of ml.train")
    ap.add_argument("--report", default=None, help="write the results tables into this markdown")
    args = ap.parse_args(argv)
    runs = [json.loads((Path(r) / "metadata.json").read_text()) for r in args.runs]
    table = results_table(runs)
    per_series = per_series_table(runs)
    print(table)
    print(per_series)
    if args.report:
        path = Path(args.report)
        text = path.read_text() if path.exists() else ""
        text = _replace_block(text, "results", table)
        text = _replace_block(text, "per-series", per_series)
        path.write_text(text)


if __name__ == "__main__":
    main()
