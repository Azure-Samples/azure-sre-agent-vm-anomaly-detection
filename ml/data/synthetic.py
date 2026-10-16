"""Synthetic VM telemetry in the live-metric contract columns (1-min resolution).

Normal behaviour: diurnal load, noise, hourly CPU bursts, healthy restarts/deploys (short
memory drop + CPU spike), batch-job exits (memory step-down, very slow recovery), slow disk
growth with log rotation. Anomalies (``label`` = 1 for their whole duration):

* ``n_leaks`` *memory leaks after deployment* - memory grows by ~``leak_mb_per_min`` (default
  10-20 MB/min on a 4 GB VM) until the leak is fixed or the kernel OOM-kills the process;
* ``n_cpu_saturations`` - a runaway process pins CPU at 85-100 % for 30-120 min;
* ``n_disk_fills`` - a log flood grows the disk by 0.2-1 % per minute for 30-90 min.

The per-series baseline levels and noise scales are randomised so that a model trained on the
shape features (slopes / std / diffs) transfers to a real VM whose absolute levels differ.
"""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

LIVE_COLUMNS = [
    "mem_used_pct",
    "mem_available_mb",
    "swap_used_pct",
    "cpu_pct",
    "disk_used_pct",
    "net_bytes",
]

MINUTES_PER_DAY = 1440


def generate(
    n_minutes: int = 3 * MINUTES_PER_DAY,
    n_leaks: int = 2,
    seed: int = 0,
    n_cpu_saturations: int = 0,
    n_disk_fills: int = 0,
    total_mb: float = 4096.0,
    leak_mb_per_min: tuple[float, float] = (10.0, 20.0),
    leak_minutes: tuple[int, int] = (120, 300),
    start: str = "2026-01-05T00:00:00Z",
) -> pd.DataFrame:
    """One VM time series: ``timestamp`` + :data:`LIVE_COLUMNS` + ``label``."""
    rng = np.random.default_rng(seed)
    t = np.arange(n_minutes)
    phase = rng.uniform(0, 2 * np.pi)
    diurnal = np.sin(2 * np.pi * t / MINUTES_PER_DAY + phase)

    mem_base = rng.uniform(15, 60)
    mem_noise = rng.uniform(0.1, 1.2)
    mem = mem_base + rng.uniform(1, 6) * diurnal + rng.normal(0, mem_noise, n_minutes)
    mem += np.convolve(rng.normal(0, mem_noise * 0.3, n_minutes), np.ones(10) / 10, "same")

    cpu_base = rng.uniform(0.5, 45)  # idle web node ... busy batch node
    cpu = cpu_base + rng.uniform(1, 10) * (diurnal + 1) / 2
    cpu += rng.gamma(2.0, rng.uniform(0.5, 2.5), n_minutes)
    cron = rng.integers(0, 60)
    burst = (t % 60 >= cron) & (t % 60 < cron + rng.integers(1, 4))
    cpu[burst] += rng.uniform(10, 40)

    label = np.zeros(n_minutes, dtype=int)
    mem_offset = np.zeros(n_minutes)

    n_restarts = max(1, n_minutes // (MINUTES_PER_DAY // 2))
    for s in rng.integers(60, max(61, n_minutes - 60), n_restarts):
        drop = rng.uniform(1, 6)
        recover = rng.integers(2, 10)
        mem_offset[s : s + recover] -= drop * np.linspace(1, 0, len(mem_offset[s : s + recover]))
        cpu[s : s + 3] += rng.uniform(20, 50)

    for s in rng.integers(0, n_minutes, max(1, n_minutes // MINUTES_PER_DAY)):
        tau = rng.uniform(600, 2400)
        mem_offset[s:] -= rng.uniform(3, 20) * np.exp(-(t[s:] - s) / tau)

    def starts(n: int, max_len: int) -> list[int]:
        """``n`` anomaly onsets spread over the series, each with ``max_len`` minutes of room."""
        out: list[int] = []
        if n:
            slots = np.linspace(0, n_minutes, n + 1, dtype=int)
            for a, b in itertools.pairwise(slots):
                lo, hi = a + 120, b - max_len - 30
                if hi > lo:
                    out.append(int(rng.integers(lo, hi)))
        return out

    for s in starts(n_leaks, leak_minutes[1]):
        dur = int(rng.integers(*leak_minutes))
        rate_pct = rng.uniform(*leak_mb_per_min) / total_mb * 100
        ramp = rate_pct * np.arange(dur)
        seg = slice(s, s + dur)
        mem_offset[seg] += ramp
        mem_offset[s : s + 5] -= rng.uniform(2, 8) * np.linspace(1, 0, 5)
        cpu[s : s + 3] += rng.uniform(20, 50)
        headroom = 97 - (mem[seg] + mem_offset[seg] - ramp)
        oom = np.nonzero(ramp >= headroom)[0]
        end = s + (int(oom[0]) if len(oom) else dur)
        mem_offset[end : s + dur] -= ramp[end - s :]
        cpu[s:end] += np.linspace(0, rng.uniform(2, 8), end - s)
        label[s:end] = 1
        mem_offset[end : end + 5] -= rng.uniform(1, 6) * np.linspace(
            1, 0, len(mem_offset[end : end + 5])
        )

    mem = np.clip(mem + mem_offset, 1, 99.5)

    has_swap = rng.random() < 0.3
    swap = np.zeros(n_minutes)
    if has_swap:
        swap = np.clip(rng.uniform(0, 3) + rng.normal(0, 0.05, n_minutes), 0, 100)
        swap += np.clip(mem - 85, 0, None) * rng.uniform(1, 3)
    cache_mb = rng.uniform(100, 600)
    avail = np.clip(total_mb * (1 - mem / 100) + cache_mb * (1 - mem / 100), 0, total_mb)
    avail += rng.normal(0, 5, n_minutes)

    disk = rng.uniform(10, 60) + rng.uniform(0, 1e-3) * t
    disk += rng.normal(0, rng.uniform(0.01, 0.08), n_minutes)  # log writes / tmp files jitter
    for s in rng.integers(0, n_minutes, max(1, n_minutes // MINUTES_PER_DAY)):
        disk[s:] -= rng.uniform(0.05, 0.3)

    for s in starts(n_cpu_saturations, 120):
        dur = int(rng.integers(30, 120))
        cpu[s : s + dur] = rng.uniform(85, 100) + rng.normal(0, 1.5, len(cpu[s : s + dur]))
        label[s : s + dur] = 1

    for s in starts(n_disk_fills, 90):
        dur = int(rng.integers(30, 90))
        fill = rng.uniform(0.2, 1.0) * np.arange(dur)
        room = 99 - disk[s]
        fill = np.minimum(fill, room)
        disk[s : s + dur] += fill[: len(disk[s : s + dur])]
        disk[s + dur :] += fill[-1] * 0.2  # log rotation reclaims most of it
        label[s : s + dur] = 1

    net = rng.uniform(2e4, 5e6) * (1 + 0.5 * diurnal) * rng.lognormal(0, 0.3, n_minutes)

    return pd.DataFrame(
        {
            "timestamp": pd.date_range(start, periods=n_minutes, freq="1min"),
            "mem_used_pct": mem,
            "mem_available_mb": np.clip(avail, 0, total_mb),
            "swap_used_pct": np.clip(swap, 0, 100),
            "cpu_pct": np.clip(cpu, 0, 100),
            "disk_used_pct": np.clip(disk, 0, 100),
            "net_bytes": net,
            "label": label,
        }
    )


def load(
    n_series: int = 6,
    n_minutes: int = 3 * MINUTES_PER_DAY,
    n_leaks: int = 2,
    seed: int = 0,
    n_cpu_saturations: int = 0,
    n_disk_fills: int = 0,
):
    """``n_series`` independent VMs as ``{name: DataFrame}``."""
    return {
        f"synthetic-{i}": generate(
            n_minutes=n_minutes,
            n_leaks=n_leaks,
            seed=seed * 1000 + i,
            n_cpu_saturations=n_cpu_saturations,
            n_disk_fills=n_disk_fills,
        )
        for i in range(n_series)
    }
