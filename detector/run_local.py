"""Run the detector from a laptop.

    python -m detector.run_local --once            # LAW -> score -> upload (env or local.settings.json)
    python -m detector.run_local --once --dry-run  # no upload
    python -m detector.run_local --csv metrics.csv # score an offline CSV, print all rows

CSV columns: timestamp, mem_used_pct, mem_available_mb, swap_used_pct, cpu_pct,
disk_used_pct, net_bytes (or raw Perf export: TimeGenerated, Computer, ObjectName,
CounterName, InstanceName, CounterValue -> pivoted automatically).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import pandas as pd

from .cycle import run_cycle, score_frame
from .law import pivot_perf

HERE = Path(__file__).parent


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    for name in ("local.settings.json", "local.settings.json.example"):
        p = HERE / name
        if p.exists():
            values = json.loads(p.read_text()).get("Values", {})
            for k, v in values.items():
                env.setdefault(k, str(v))
            break
    return env


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--once", action="store_true", help="run one cycle against Log Analytics")
    ap.add_argument("--csv", help="score this CSV offline instead of querying LAW")
    ap.add_argument("--dry-run", action="store_true", help="do not upload to the DCE")
    ap.add_argument("--all", action="store_true", help="print every row, not just the last")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    env = load_env()

    if args.csv:
        df = pd.read_csv(args.csv)
        if "CounterName" in df.columns:
            df = pivot_perf(df)
        else:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        computer = env.get("TARGET_COMPUTER", "vm-app-01")
        out = score_frame(df, computer, last_only=not args.all)
        print(out.to_string(index=False))
        return 0

    if args.once:
        out = run_cycle(env, dry_run=args.dry_run)
        if out is None:
            print("no data scored (see log)")
            return 1
        print(out.to_string(index=False))
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
