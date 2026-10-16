"""Tiny cached HTTP downloader for the public datasets (files land in ml/data/raw/, git-ignored)."""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path

RAW_DIR = Path(os.environ.get("ML_DATA_RAW", Path(__file__).resolve().parent / "raw"))


def fetch(url: str, dest: Path, retries: int = 3) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as fh:
                fh.write(resp.read())
            tmp.replace(dest)
            return dest
        except OSError:
            if attempt == retries - 1:
                raise
    return dest
