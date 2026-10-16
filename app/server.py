"""demo-app: a small "reporting" service running on vm-app-01.

Endpoints
    GET /                 service info
    GET /health           liveness
    GET /version          deployed git ref (from /opt/demo-app/version.env, see deploy.sh)
    GET /report           latest generated report (~256 KB), served from ReportCache
    GET /report?at=<ts>   a historical report, generated on demand and archived
    GET /reports?since=<ts>  bulk export of every per-second report since <ts>
    GET /stats            cache size / hit ratio (what an SRE looks at first)

A background "warmer" pre-generates the current report every second so /report is always hot.
Reports are cached in ReportCache; the cache is bounded (MAX_ENTRIES) and evicts the oldest
entry, so steady-state memory is flat. Historical reports requested with ?at= are kept in the
report archive so repeated lookups of the same timestamp are instant.

A monitor thread logs cache size and process RSS once a minute to stderr (journald -> syslog,
facility daemon, identifier demo-app) and escalates to WARNING/ERROR when RSS exceeds
RSS_WARN_MB / RSS_ERROR_MB, so the failing process can be identified from Syslog alone.
"""

from __future__ import annotations

import calendar
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

VERSION = os.environ.get("DEMO_APP_VERSION", "dev")
REPORT_BYTES = 256 * 1024
MAX_ENTRIES = 64  # ~16 MB of reports kept hot
WARM_INTERVAL_S = 1.0
MONITOR_INTERVAL_S = float(os.environ.get("DEMO_APP_MONITOR_INTERVAL_S", "60"))
RSS_WARN_MB = int(os.environ.get("DEMO_APP_RSS_WARN_MB", "256"))
RSS_ERROR_MB = int(os.environ.get("DEMO_APP_RSS_ERROR_MB", "1024"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("demo-app")


class ReportCache:
    """LRU cache of rendered reports keyed by report id."""

    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self.max_entries = max_entries
        self._data: OrderedDict[str, bytes] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> bytes | None:
        with self._lock:
            val = self._data.get(key)
            if val is None:
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return val

    def put(self, key: str, val: bytes) -> None:
        with self._lock:
            self._data[key] = val
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)


cache = ReportCache()
archive: dict[str, bytes] = {}
_archive_lock = threading.Lock()


def report_id(ts: float | None = None) -> str:
    """Reports are generated per second and identified by their timestamp."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts or time.time()))


def render_report(rid: str) -> bytes:
    body = os.urandom(REPORT_BYTES)  # stands in for an expensive aggregation
    return rid.encode() + b"\n" + body


def get_report(rid: str) -> bytes:
    data = cache.get(rid)
    if data is None:
        data = render_report(rid)
        cache.put(rid, data)
    return data


def get_historical_report(rid: str) -> bytes:
    with _archive_lock:
        data = archive.get(rid)
    if data is None:
        data = render_report(rid)
        with _archive_lock:
            archive[rid] = data
    return data


def parse_report_id(rid: str) -> float:
    return float(calendar.timegm(time.strptime(rid, "%Y-%m-%dT%H:%M:%SZ")))


def export_reports(since: float, until: float) -> Iterator[bytes]:
    t = since
    while t < until:
        yield get_historical_report(report_id(t))
        t += 1


def warm_cache() -> None:
    while True:
        get_report(report_id())
        time.sleep(WARM_INTERVAL_S)


def rss_mb() -> float:
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    return 0.0


def monitor_once() -> int:
    """Log one resource sample; returns the level used."""
    rss = rss_mb()
    msg = "health rss_mb=%.0f cache_entries=%d cache_bytes_approx=%d archive_entries=%d version=%s"
    args = (rss, len(cache), len(cache) * REPORT_BYTES, len(archive), VERSION)
    if rss >= RSS_ERROR_MB:
        log.error("memory budget exceeded (limit %d MB) " + msg, RSS_ERROR_MB, *args)
        return logging.ERROR
    if rss >= RSS_WARN_MB:
        log.warning("memory above warning level (%d MB) " + msg, RSS_WARN_MB, *args)
        return logging.WARNING
    log.info(msg, *args)
    return logging.INFO


def monitor() -> None:
    while True:
        monitor_once()
        time.sleep(MONITOR_INTERVAL_S)


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, data: bytes, ctype: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj: object, status: int = 200) -> None:
        self._send(status, json.dumps(obj).encode())

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/":
            self._json({"service": "demo-app", "version": VERSION})
        elif url.path == "/health":
            self._json({"status": "ok"})
        elif url.path == "/version":
            self._json({"version": VERSION})
        elif url.path == "/stats":
            total = cache.hits + cache.misses
            self._json(
                {
                    "cache_entries": len(cache),
                    "cache_bytes_approx": len(cache) * REPORT_BYTES,
                    "hit_ratio": round(cache.hits / total, 3) if total else None,
                    "archive_entries": len(archive),
                }
            )
        elif url.path == "/reports":
            try:
                since = parse_report_id(parse_qs(url.query)["since"][0])
            except (KeyError, ValueError):
                self.send_error(400, "since=<YYYY-MM-DDTHH:MM:SSZ> required")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            for chunk in export_reports(since, time.time()):
                self.wfile.write(chunk)
        elif url.path == "/report":
            at = parse_qs(url.query).get("at")
            data = get_historical_report(at[0]) if at else get_report(report_id())
            self._send(200, data, "application/octet-stream")
        else:
            self.send_error(404)

    def log_message(self, fmt: str, *args: object) -> None:  # keep journald quiet
        pass


if __name__ == "__main__":
    threading.Thread(target=warm_cache, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
