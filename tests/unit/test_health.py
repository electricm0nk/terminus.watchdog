"""Tests for health and metrics HTTP server — Story 1.2."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

import watchdog.health as health_module
from watchdog.health import _create_app, update_heartbeat_timestamp
from watchdog.state import WatchdogState


async def test_healthz_returns_200_ok() -> None:
    state = WatchdogState()
    app = _create_app(state)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/healthz")
        assert resp.status == 200
        data = await resp.json()
        assert data == {"status": "ok"}


async def test_metrics_contains_heartbeat_gauge() -> None:
    health_module._heartbeat_ts = 0.0
    state = WatchdogState()
    app = _create_app(state)
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/metrics")
        assert resp.status == 200
        text = await resp.text()
        assert "watchdog_last_heartbeat_timestamp_seconds" in text
        assert "watchdog_last_heartbeat_timestamp_seconds 0.0" in text


async def test_server_starts_on_configured_port() -> None:
    """Verify the app can be served (port binding via TestServer)."""
    state = WatchdogState()
    app = _create_app(state)
    async with TestClient(TestServer(app)) as client:
        # Both routes respond — server is up on the bound port
        healthz = await client.get("/healthz")
        metrics = await client.get("/metrics")
        assert healthz.status == 200
        assert metrics.status == 200
