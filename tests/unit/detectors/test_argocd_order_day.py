"""Unit tests for ArgoCD order-day unsync detector — Story 2.5 (RED phase)."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun import freeze_time

from watchdog.config import HighPriorityWindow
from watchdog.detectors.argocd_order_day import (
    ArgoCDOrderDayDetector,
    is_high_priority_window_active,
)

# ---------------------------------------------------------------------------
# Test window config (matches PRD §8.2: Tue 11:55 AM → Wed 11:30 PM CT)
# ---------------------------------------------------------------------------
_ORDER_DAY_WINDOW = HighPriorityWindow(
    name="order-day",
    rrule_str="FREQ=WEEKLY;BYDAY=TU;BYHOUR=11;BYMINUTE=55",
    duration_hours=35.58,
    timezone="America/Chicago",
)

# All frozen times are UTC.  CST (January) = UTC − 6.
#   Tuesday  2026-01-13 12:00 PM CT → 2026-01-13 18:00 UTC
#   Wednesday 2026-01-14 8:00 PM CT → 2026-01-15 02:00 UTC
#   Thursday  2026-01-15 9:00 AM CT → 2026-01-15 15:00 UTC
#   Monday    2026-01-12 11:00 AM CT → 2026-01-12 17:00 UTC


# ---------------------------------------------------------------------------
# is_high_priority_window_active tests
# ---------------------------------------------------------------------------


@freeze_time("2026-01-13 18:00:00")  # Tuesday 12:00 PM CT — inside window
def test_inside_window_tuesday_noon_returns_true() -> None:
    assert is_high_priority_window_active(_ORDER_DAY_WINDOW) is True


@freeze_time("2026-01-15 02:00:00")  # Wednesday 8:00 PM CT — inside window
def test_inside_window_wednesday_8pm_returns_true() -> None:
    assert is_high_priority_window_active(_ORDER_DAY_WINDOW) is True


@freeze_time("2026-01-15 15:00:00")  # Thursday 9:00 AM CT — outside window
def test_outside_window_thursday_9am_returns_false() -> None:
    assert is_high_priority_window_active(_ORDER_DAY_WINDOW) is False


@freeze_time("2026-01-12 17:00:00")  # Monday 11:00 AM CT — outside window
def test_outside_window_monday_11am_returns_false() -> None:
    assert is_high_priority_window_active(_ORDER_DAY_WINDOW) is False


# ---------------------------------------------------------------------------
# ArgoCDOrderDayDetector tests
# ---------------------------------------------------------------------------


def _make_outsync_app(name: str, namespace: str = "argocd") -> dict[str, Any]:
    return {
        "metadata": {"name": name, "namespace": namespace},
        "status": {
            "sync": {"status": "OutOfSync"},
            "operationState": {},
        },
    }


def _make_client(apps: list[dict[str, Any]]) -> MagicMock:
    client = MagicMock()
    client.list_applications = AsyncMock(return_value=apps)
    return client


@freeze_time("2026-01-13 18:00:00")  # Inside window
@pytest.mark.asyncio
async def test_non_etailpet_app_produces_no_alert() -> None:
    """Non etailpet-* apps must never produce order-day alerts."""
    app = _make_outsync_app("fourdogs-central")
    client = _make_client([app])
    detector = ArgoCDOrderDayDetector(client=client, window=_ORDER_DAY_WINDOW)
    alerts = await detector.detect()
    assert alerts == []


@freeze_time("2026-01-13 18:00:00")  # Inside window
@pytest.mark.asyncio
async def test_etailpet_outsync_inside_window_produces_high_bypass_quiet_hours() -> None:
    """etailpet-* OutOfSync app inside window → argocd-order-day-unsync High + bypass."""
    app = _make_outsync_app("etailpet-order-service")
    client = _make_client([app])
    detector = ArgoCDOrderDayDetector(client=client, window=_ORDER_DAY_WINDOW)
    alerts = await detector.detect()
    assert len(alerts) == 1
    assert alerts[0].pattern == "argocd-order-day-unsync"
    assert alerts[0].severity == "high"
    assert alerts[0].bypass_quiet_hours is True
    assert alerts[0].remediation_available is True
