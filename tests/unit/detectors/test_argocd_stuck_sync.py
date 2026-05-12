"""Unit tests for ArgoCDStuckSyncDetector — Story 2.4 (RED phase)."""
from __future__ import annotations

from datetime import UTC
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun import freeze_time

from watchdog.detectors.argocd import ArgoCDStuckSyncDetector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FROZEN_NOW = "2026-01-15 12:00:00"  # UTC


def _make_syncing_app(
    name: str = "my-app",
    namespace: str = "argocd",
    started_seconds_ago: int = 0,
    op_phase: str = "Running",
) -> dict[str, Any]:
    """Build an app dict that is actively syncing."""
    from datetime import datetime, timedelta

    started_at = (
        datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
        - timedelta(seconds=started_seconds_ago)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "metadata": {"name": name, "namespace": namespace},
        "status": {
            "sync": {"status": "Syncing"},
            "operationState": {
                "phase": op_phase,
                "startedAt": started_at,
            },
        },
    }


def _make_synced_app(name: str = "my-app") -> dict[str, Any]:
    return {
        "metadata": {"name": name, "namespace": "argocd"},
        "status": {
            "sync": {"status": "Synced"},
            "operationState": {},
        },
    }


def _make_outsync_not_syncing_app(name: str = "my-app") -> dict[str, Any]:
    return {
        "metadata": {"name": name, "namespace": "argocd"},
        "status": {
            "sync": {"status": "OutOfSync"},
            "operationState": {},
        },
    }


def _make_client(apps: list[dict[str, Any]]) -> MagicMock:
    client = MagicMock()
    client.list_applications = AsyncMock(return_value=apps)
    return client


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@freeze_time(_FROZEN_NOW)
@pytest.mark.asyncio
async def test_app_syncing_3_minutes_no_alert() -> None:
    """An app syncing for 3 min (< 5 min threshold) must NOT produce an alert."""
    app = _make_syncing_app(started_seconds_ago=180)  # 3 minutes
    client = _make_client([app])
    detector = ArgoCDStuckSyncDetector(client=client, threshold_minutes=5)
    alerts = await detector.detect()
    assert alerts == []


@freeze_time(_FROZEN_NOW)
@pytest.mark.asyncio
async def test_app_syncing_6_minutes_produces_stuck_sync_high() -> None:
    """An app syncing for 6 min (> 5 min threshold) must produce argocd-stuck-sync High."""
    app = _make_syncing_app(name="my-app", started_seconds_ago=360)  # 6 minutes
    client = _make_client([app])
    detector = ArgoCDStuckSyncDetector(client=client, threshold_minutes=5)
    alerts = await detector.detect()
    assert len(alerts) == 1
    assert alerts[0].pattern == "argocd-stuck-sync"
    assert alerts[0].severity == "high"
    assert alerts[0].remediation_available is True
    assert alerts[0].duration_seconds >= 360


@freeze_time(_FROZEN_NOW)
@pytest.mark.asyncio
async def test_app_synced_no_alert() -> None:
    """A Synced app must not produce an alert from the stuck-sync detector."""
    app = _make_synced_app()
    client = _make_client([app])
    detector = ArgoCDStuckSyncDetector(client=client, threshold_minutes=5)
    alerts = await detector.detect()
    assert alerts == []


@freeze_time(_FROZEN_NOW)
@pytest.mark.asyncio
async def test_app_outsync_not_syncing_no_alert() -> None:
    """An OutOfSync app that is not actively syncing must not trigger stuck-sync."""
    app = _make_outsync_not_syncing_app()
    client = _make_client([app])
    detector = ArgoCDStuckSyncDetector(client=client, threshold_minutes=5)
    alerts = await detector.detect()
    assert alerts == []
