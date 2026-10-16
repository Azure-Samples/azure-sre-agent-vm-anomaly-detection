import json
import logging
import threading
import time
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from app import server


@pytest.fixture
def app_server():
    server.VERSION = "abc123"
    http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    yield f"http://127.0.0.1:{http.server_port}"
    http.shutdown()
    http.server_close()
    worker.join()


def test_endpoints(app_server):
    for path, expected in {
        "/": {"service": "demo-app", "version": "abc123"},
        "/health": {"status": "ok"},
        "/version": {"version": "abc123"},
    }.items():
        with urlopen(f"{app_server}{path}") as response:
            assert json.load(response) == expected
    with urlopen(f"{app_server}/report?at=2025-01-01T00:00:00Z") as response:
        body = response.read()
    assert body.startswith(b"2025-01-01T00:00:00Z\n") and len(body) > server.REPORT_BYTES
    with urlopen(f"{app_server}/stats") as response:
        assert json.load(response)["archive_entries"] >= 1
    with pytest.raises(HTTPError) as error:
        urlopen(f"{app_server}/missing")
    assert error.value.code == 404


def test_report_cache_is_bounded():
    cache = server.ReportCache(max_entries=8)
    for i in range(1000):
        cache.put(f"r{i}", b"x")
    assert len(cache) == 8
    assert cache.get("r0") is None and cache.get("r999") == b"x"


def test_warmer_does_not_grow_cache_unbounded(monkeypatch):
    monkeypatch.setattr(server, "cache", server.ReportCache(max_entries=4))
    for t in range(200):
        server.get_report(server.report_id(1_700_000_000 + t))
    assert len(server.cache) <= 4


def test_monitor_logs_level_by_rss(monkeypatch, caplog):
    monkeypatch.setattr(server, "rss_mb", lambda: 10.0)
    assert server.monitor_once() == logging.INFO
    monkeypatch.setattr(server, "rss_mb", lambda: float(server.RSS_WARN_MB))
    assert server.monitor_once() == logging.WARNING
    monkeypatch.setattr(server, "rss_mb", lambda: float(server.RSS_ERROR_MB))
    assert server.monitor_once() == logging.ERROR
    assert "cache_entries=" in caplog.text


def test_historical_reports_are_archived_separately_from_the_warm_cache(monkeypatch):
    monkeypatch.setattr(server, "archive", {})
    monkeypatch.setattr(server, "cache", server.ReportCache(max_entries=4))
    for t in range(50):
        server.get_historical_report(server.report_id(1_600_000_000 + t))
    assert (len(server.archive), len(server.cache)) == (50, 0)


def test_monitor_reports_archive_size(monkeypatch, caplog):
    monkeypatch.setattr(server, "archive", {"r1": b"x", "r2": b"y"})
    monkeypatch.setattr(server, "rss_mb", lambda: 10.0)
    caplog.set_level(logging.INFO)
    server.monitor_once()
    assert "archive_entries=2" in caplog.text


def test_bulk_export_archives_one_report_per_second(app_server, monkeypatch):
    monkeypatch.setattr(server, "archive", {})
    since = server.report_id(time.time() - 5)
    with urlopen(f"{app_server}/reports?since={since}") as response:
        body = response.read()
    assert len(server.archive) >= 5 and len(body) >= 5 * server.REPORT_BYTES


def test_bulk_export_rejects_bad_timestamp(app_server):
    with pytest.raises(HTTPError) as error:
        urlopen(f"{app_server}/reports?since=yesterday")
    assert error.value.code == 400
