"""Health and metrics HTTP server for Terminus Watchdog Agent."""
from __future__ import annotations

import logging

from aiohttp import web

from watchdog.state import WatchdogState

logger = logging.getLogger(__name__)

_heartbeat_ts: float = 0.0

_METRICS_HEADER = (
    "# HELP watchdog_last_heartbeat_timestamp_seconds "
    "Unix timestamp of last watchdog heartbeat\n"
    "# TYPE watchdog_last_heartbeat_timestamp_seconds gauge\n"
)


def update_heartbeat_timestamp(ts: float) -> None:
    global _heartbeat_ts
    _heartbeat_ts = ts


async def _handle_healthz(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def _handle_metrics(request: web.Request) -> web.Response:
    body = f"{_METRICS_HEADER}watchdog_last_heartbeat_timestamp_seconds {_heartbeat_ts}\n"
    resp = web.Response(body=body.encode("utf-8"))
    resp.headers["Content-Type"] = "text/plain; version=0.0.4"
    return resp


def _create_app(state: WatchdogState) -> web.Application:
    app = web.Application()
    app["state"] = state
    app.router.add_get("/healthz", _handle_healthz)
    app.router.add_get("/metrics", _handle_metrics)
    return app


async def start_health_server(state: WatchdogState, port: int = 9090) -> None:
    app = _create_app(state)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("health server started", extra={"port": port})
