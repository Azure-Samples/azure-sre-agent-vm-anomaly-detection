"""Azure Functions (Python v2) timer: query LAW Perf -> features -> score -> Logs Ingestion."""

from __future__ import annotations

import logging
import os

import azure.functions as func

try:
    from .cycle import run_cycle
except ImportError:  # host imports this file as a top-level module
    from cycle import run_cycle  # type: ignore[no-redef]

app = func.FunctionApp()
log = logging.getLogger("detector")


@app.timer_trigger(schedule="0 * * * * *", arg_name="timer", run_on_startup=False)
def score_vm(timer: func.TimerRequest) -> None:
    if timer.past_due:
        log.warning("timer is past due")
    try:
        result = run_cycle(os.environ)
        if result is None or result.empty:
            log.info("nothing scored this cycle")
        else:
            r = result.iloc[-1]
            log.info(
                "scored %s @ %s score=%.3f anomaly=%s top=%s",
                r["Computer"],
                r["TimeGenerated"],
                r["Score"],
                r["IsAnomaly"],
                r["TopFeature"],
            )
    except Exception:  # never let one bad cycle kill the timer
        log.exception("scoring cycle failed")
