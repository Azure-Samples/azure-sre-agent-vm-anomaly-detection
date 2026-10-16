"""Status dashboard: local aggregator and static web server.

uv run --extra dashboard python -m dashboard.server --demo
GITHUB_TOKEN=... uv run --extra dashboard python -m dashboard.server
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import re
import sys
import threading
from collections.abc import Callable
from dataclasses import replace
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dashboard.actions import ActionRunner, live_actions
from dashboard.config import Config
from dashboard.demo import DemoClock, DemoSource, demo_actions
from dashboard.sources import Poller, Source
from dashboard.store import StatusStore, utcnow

log = logging.getLogger("dashboard")
WEB_DIR = Path(__file__).parent / "web"
IMPORT_MAP = re.compile(r'<script type="importmap">(.*?)</script>', re.DOTALL)
Provider = Callable[[], dict[str, object]]


def content_security_policy(index: Path) -> str:
    """Allow only same-origin resources plus the inline import map, pinned by hash."""
    match = IMPORT_MAP.search(index.read_text(encoding="utf-8"))
    hashes = ""
    if match:
        digest = base64.b64encode(hashlib.sha256(match[1].encode()).digest()).decode()
        hashes = f" 'sha256-{digest}'"
    return (
        f"default-src 'self'; script-src 'self'{hashes}; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    )


def create_server(
    provider: Provider, host: str, port: int, actions: ActionRunner | None = None
) -> ThreadingHTTPServer:
    csp = content_security_policy(WEB_DIR / "index.html")
    # Rejecting foreign Host headers blocks DNS rebinding from reading the snapshot.
    allowed_hosts = {host, "localhost", "127.0.0.1", "[::1]"}

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, directory=str(WEB_DIR), **kwargs)

        def end_headers(self) -> None:
            self.send_header("Content-Security-Policy", csp)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            super().end_headers()

        def _host_allowed(self) -> bool:
            return self.headers.get("Host", "").rsplit(":", 1)[0] in allowed_hosts

        def _json(self, status: int, payload: object) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            """Presenter actions. Same-origin Origin plus a custom header defeat CSRF from
            other pages: browsers only send the header cross-origin after a CORS preflight,
            which this server never answers."""
            name = self.path.split("?", 1)[0].removeprefix("/api/actions/")
            if not self._host_allowed():
                self.send_error(403)
                return
            if actions is None or name == self.path or "/" in name:
                self.send_error(404)
                return
            origin = self.headers.get("Origin")
            if (
                self.headers.get("X-Dashboard-Action") != "1"
                or origin != f"http://{self.headers['Host']}"
            ):
                self.send_error(403)
                return
            try:
                started = actions.start(name)
            except KeyError:
                self.send_error(404)
                return
            self._json(202 if started else 409, {"started": started})

        def do_GET(self) -> None:
            if not self._host_allowed():
                self.send_error(403)
                return
            if self.path.split("?", 1)[0] != "/api/snapshot":
                super().do_GET()
                return
            self._json(200, provider())

        def list_directory(self, path):  # no directory listings
            self.send_error(404)

        def log_message(self, fmt: str, *args: object) -> None:
            log.debug("%s " + fmt, self.address_string(), *args)

    return ThreadingHTTPServer((host, port), Handler)


def live_sources(config: Config) -> list[Source]:
    from azure.identity import DefaultAzureCredential
    from azure.monitor.query import LogsQueryClient

    from dashboard.sources.arm import ArmSource
    from dashboard.sources.github import GitHubSource
    from dashboard.sources.http import AzureRest, GitHubRest
    from dashboard.sources.law import LawSource, logs_runner
    from dashboard.sources.sre_agent import SreAgentSource

    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    rest = AzureRest(lambda scope: credential.get_token(scope).token)
    sources: list[Source] = [
        LawSource(config, logs_runner(LogsQueryClient(credential), config.workspace_id)),
        ArmSource(config, rest.get),
        SreAgentSource(config, rest.get, utcnow),
    ]
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        sources.append(GitHubSource(config, GitHubRest(token).get, utcnow))
    else:
        log.warning("GITHUB_TOKEN is not set; issue, PR and workflow status are disabled")
    return sources


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Single-view status dashboard")
    parser.add_argument("--demo", action="store_true", help="play the scripted incident")
    parser.add_argument("--speed", type=float, default=20.0, help="demo speed (scenario s per s)")
    parser.add_argument("--start", type=float, default=0.0, help="demo start (scenario minute)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s"
    )
    if not args.verbose:
        logging.getLogger("azure").setLevel(logging.WARNING)
    config = Config.from_env(os.environ)
    if args.demo:
        config = replace(
            config,
            tenant_id=config.tenant_id or "00000000-0000-0000-0000-000000000000",
            subscription_id=config.subscription_id or "00000000-0000-0000-0000-000000000000",
            repo=config.repo or "example/vm-anomaly-demo",
        )
        clock = DemoClock(args.speed, args.start)
        store = StatusStore(config, "demo", clock.now, refresh_ms=1000)
        sources: list[Source] = [DemoSource(clock)]
        runner = ActionRunner(demo_actions(clock))
    else:
        missing = [
            "DASHBOARD_" + name.upper()
            for name in ("tenant_id", "subscription_id", "repo")
            if not getattr(config, name).strip()
        ]
        if missing:
            log.error("Set required live settings: %s", ", ".join(missing))
            return 2
        store = StatusStore(config, "live")
        sources = live_sources(config)
        runner = ActionRunner(live_actions())
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("listening on %s exposes incident details to the network", args.host)
    stop = threading.Event()
    for source in sources:
        Poller(source, store, stop).start()
    server = create_server(
        lambda: {**store.snapshot().to_dict(), "actions": runner.describe()},
        args.host,
        args.port,
        runner,
    )
    log.info(
        "dashboard on http://%s:%d (%s)",
        args.host,
        server.server_port,
        "demo" if args.demo else "live",
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        stop.set()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
