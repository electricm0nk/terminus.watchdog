"""Unit tests for ArgoCDPoller — Story 2.3 (RED phase)."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from watchdog.clients.argocd import ArgoCDAuthError, ArgoCDTimeoutError
from watchdog.detectors.argocd import ArgoCDPoller


# ---------------------------------------------------------------------------
# Helpers — build minimal ArgoCD app dicts
# ---------------------------------------------------------------------------


def _make_app(
    name: str,
    namespace: str = "argocd",
    sync_status: str = "Synced",
    images: list[str] | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    app: dict[str, Any] = {
        "metadata": {"name": name, "namespace": namespace},
        "status": {
            "sync": {"status": sync_status},
            "summary": {"images": images or []},
            "operationState": {},
        },
    }
    if started_at:
        app["status"]["operationState"]["startedAt"] = started_at
    return app


def _make_client(apps: list[dict[str, Any]]) -> MagicMock:
    client = MagicMock()
    client.list_applications = AsyncMock(return_value=apps)
    return client


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_sync_app_produces_no_alerts() -> None:
    """A Synced app must not produce any alert."""
    client = _make_client([_make_app("my-app", sync_status="Synced")])
    poller = ArgoCDPoller(client=client)
    alerts = await poller.detect()
    assert alerts == []


@pytest.mark.asyncio
async def test_outsync_no_image_change_produces_live_drift_high() -> None:
    """OutOfSync app with no SHA-pinned image must produce argocd-live-drift High."""
    client = _make_client([_make_app("my-app", sync_status="OutOfSync", images=[])])
    poller = ArgoCDPoller(client=client)
    alerts = await poller.detect()
    assert len(alerts) == 1
    assert alerts[0].pattern == "argocd-live-drift"
    assert alerts[0].severity == "high"
    assert alerts[0].remediation_available is True


@pytest.mark.asyncio
async def test_outsync_with_sha_image_mvp0_enabled_produces_image_promotion_medium() -> None:
    """OutOfSync app with SHA-tagged image must produce argocd-image-promotion Medium."""
    sha_image = "ghcr.io/electricm0nk/fourdogs-emailfetcher:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
    client = _make_client([
        _make_app("my-app", sync_status="OutOfSync", images=[sha_image])
    ])
    poller = ArgoCDPoller(client=client, mvp0_enabled=True)
    alerts = await poller.detect()
    assert len(alerts) == 1
    assert alerts[0].pattern == "argocd-image-promotion"
    assert alerts[0].severity == "medium"
    assert alerts[0].remediation_available is False


@pytest.mark.asyncio
async def test_outsync_with_sha_image_mvp0_fallback_produces_live_drift_high() -> None:
    """When MVP0 is disabled, SHA-tagged image OutOfSync still produces argocd-live-drift High."""
    sha_image = "ghcr.io/electricm0nk/fourdogs-emailfetcher:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
    client = _make_client([
        _make_app("my-app", sync_status="OutOfSync", images=[sha_image])
    ])
    poller = ArgoCDPoller(client=client, mvp0_enabled=False)
    alerts = await poller.detect()
    assert len(alerts) == 1
    assert alerts[0].pattern == "argocd-live-drift"
    assert alerts[0].severity == "high"


@pytest.mark.asyncio
async def test_argocd_auth_error_returns_empty_list(caplog: pytest.LogCaptureFixture) -> None:
    """ArgoCDAuthError must be caught; empty list returned and error logged."""
    import logging

    client = MagicMock()
    client.list_applications = AsyncMock(side_effect=ArgoCDAuthError("401"))
    poller = ArgoCDPoller(client=client)
    with caplog.at_level(logging.ERROR):
        alerts = await poller.detect()
    assert alerts == []
    assert any("ArgoCDAuthError" in r.message or "401" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_argocd_timeout_returns_empty_list(caplog: pytest.LogCaptureFixture) -> None:
    """ArgoCDTimeoutError must be caught; empty list returned and warning logged."""
    import logging

    client = MagicMock()
    client.list_applications = AsyncMock(side_effect=ArgoCDTimeoutError("timeout"))
    poller = ArgoCDPoller(client=client)
    with caplog.at_level(logging.WARNING):
        alerts = await poller.detect()
    assert alerts == []
    assert any("timeout" in r.message.lower() or "Timeout" in r.message for r in caplog.records)
