"""Unit tests for detection loop — Story 2.6 (RED phase)."""
from __future__ import annotations

import asyncio
import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from watchdog.loop import run_detection_cycle
from watchdog.models import Alert
from watchdog.state import WatchdogState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_POLL_SECONDS = 300
_DEFAULT_COOLDOWN_MINUTES = 30
_COLD_START_GRACE_MINUTES = 30


def _make_settings(
    poll_interval_seconds: int = _DEFAULT_POLL_SECONDS,
    detection_timeout_seconds: int = 10,
    cooldown_minutes: int = _DEFAULT_COOLDOWN_MINUTES,
    cold_start_grace_minutes: int = _COLD_START_GRACE_MINUTES,
) -> MagicMock:
    s = MagicMock()
    s.poll_interval_seconds = poll_interval_seconds
    s.detection_timeout_seconds = detection_timeout_seconds
    s.cooldown_minutes = cooldown_minutes
    s.cold_start_grace_minutes = cold_start_grace_minutes
    return s


def _make_alert(
    pattern: str = "argocd-live-drift",
    severity: str = "high",
    bypass_quiet_hours: bool = False,
) -> Alert:
    return Alert(
        pattern=pattern,
        severity=severity,
        resource_name="my-app",
        resource_namespace="argocd",
        duration_seconds=120.0,
        diagnosis="OutOfSync",
        recommended_action="Sync it",
        remediation_available=True,
        bypass_quiet_hours=bypass_quiet_hours,
    )


def _make_bot(message_id: int = 42) -> MagicMock:
    bot = MagicMock()
    bot.post_alert = AsyncMock(return_value=message_id)
    return bot


def _make_detector(alerts: list[Alert], pattern_id: str = "argocd-live-drift") -> MagicMock:
    d = MagicMock()
    d.pattern_id = pattern_id
    d.detect = AsyncMock(return_value=alerts)
    return d


# ---------------------------------------------------------------------------
# Core loop tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_alert_not_suppressed_calls_post_alert() -> None:
    """An unsuppressed, non-cooldown alert must cause bot.post_alert to be called."""
    alert = _make_alert()
    detector = _make_detector([alert])
    bot = _make_bot()
    state = WatchdogState()
    settings = _make_settings()
    # Cold-start grace already expired
    state.startup_time = datetime.datetime.utcnow() - datetime.timedelta(minutes=60)

    await run_detection_cycle(bot=bot, detectors=[detector], state=state, settings=settings)

    bot.post_alert.assert_awaited_once_with(alert, state)


@pytest.mark.asyncio
async def test_suppressed_alert_skips_post_alert() -> None:
    """A suppressed alert must not trigger bot.post_alert."""
    alert = _make_alert()
    detector = _make_detector([alert])
    bot = _make_bot()
    state = WatchdogState()
    state.startup_time = datetime.datetime.utcnow() - datetime.timedelta(minutes=60)
    settings = _make_settings()
    # Manually suppress the key
    state.add_suppression(
        key=alert.suppression_key,
        reason="manual test suppression",
        duration_minutes=60,
    )

    await run_detection_cycle(bot=bot, detectors=[detector], state=state, settings=settings)

    bot.post_alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_cooldown_alert_skips_post_alert() -> None:
    """An alert still in cooldown must not trigger bot.post_alert."""
    alert = _make_alert()
    detector = _make_detector([alert])
    bot = _make_bot()
    state = WatchdogState()
    state.startup_time = datetime.datetime.utcnow() - datetime.timedelta(minutes=60)
    settings = _make_settings()
    # Start cooldown for this key
    state.start_cooldown(key=alert.suppression_key, minutes=30)

    await run_detection_cycle(bot=bot, detectors=[detector], state=state, settings=settings)

    bot.post_alert.assert_not_awaited()


@pytest.mark.asyncio
async def test_detector_timeout_logs_warning_other_detectors_still_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Detector timeout must log a WARNING and not stop other detectors from running."""
    import logging

    alert = _make_alert()
    good_detector = _make_detector([alert])

    # Slow detector that will time out
    slow_detector = MagicMock()
    slow_detector.pattern_id = "slow"

    async def _slow() -> list[Alert]:
        await asyncio.sleep(100)
        return []

    slow_detector.detect = _slow

    bot = _make_bot()
    state = WatchdogState()
    state.startup_time = datetime.datetime.utcnow() - datetime.timedelta(minutes=60)
    settings = _make_settings(detection_timeout_seconds=1)

    with caplog.at_level(logging.WARNING):
        await run_detection_cycle(bot=bot, detectors=[slow_detector, good_detector], state=state, settings=settings)

    # Good detector still fired
    bot.post_alert.assert_awaited_once()
    # Warning about timeout was logged
    assert any("slow" in r.message.lower() or "timed out" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# AC1 — ArgoCD OutOfSync Classification (acceptance)
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
@pytest.mark.asyncio
async def test_ac_1_argocd_outsync_classification() -> None:
    """AC1 — end-to-end: mocked OutOfSync app → argocd-live-drift High → alerts channel."""
    from watchdog.clients.argocd import ArgoCDClient
    from watchdog.detectors.argocd import ArgoCDPoller

    # Build a mocked ArgoCD client returning one OutOfSync app with no SHA image
    app: dict[str, Any] = {
        "metadata": {"name": "fourdogs-central", "namespace": "argocd"},
        "status": {
            "sync": {"status": "OutOfSync"},
            "summary": {"images": []},
            "operationState": {},
        },
    }
    argocd_client = MagicMock(spec=ArgoCDClient)
    argocd_client.list_applications = AsyncMock(return_value=[app])

    poller = ArgoCDPoller(client=argocd_client)

    bot = _make_bot(message_id=99001)
    state = WatchdogState()
    state.startup_time = datetime.datetime.utcnow() - datetime.timedelta(minutes=60)
    settings = _make_settings()

    await run_detection_cycle(bot=bot, detectors=[poller], state=state, settings=settings)

    # Assert alert was posted exactly once
    bot.post_alert.assert_awaited_once()
    call_args = bot.post_alert.call_args
    posted_alert: Alert = call_args.args[0]
    assert posted_alert.pattern == "argocd-live-drift"
    assert posted_alert.severity == "high"


# ---------------------------------------------------------------------------
# AC8 — Cold-Start Suppression (acceptance)
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
@pytest.mark.asyncio
async def test_ac_8_cold_start_suppression(caplog: pytest.LogCaptureFixture) -> None:
    """AC8 — non-bypass alerts suppressed during grace; bypass alerts delivered; grace expires."""
    import logging

    normal_alert = _make_alert(bypass_quiet_hours=False)
    bypass_alert = _make_alert(pattern="argocd-order-day-unsync", bypass_quiet_hours=True)

    normal_detector = _make_detector([normal_alert])
    bypass_detector = _make_detector([bypass_alert], pattern_id="argocd-order-day-unsync")

    bot = _make_bot()
    state = WatchdogState()
    # Cold-start still active (just started)
    state.startup_time = datetime.datetime.utcnow()

    settings = _make_settings(cold_start_grace_minutes=30)

    with caplog.at_level(logging.INFO):
        await run_detection_cycle(
            bot=bot,
            detectors=[normal_detector, bypass_detector],
            state=state,
            settings=settings,
        )

    # Normal alert was suppressed during cold-start
    # Bypass alert was delivered
    calls = bot.post_alert.call_args_list
    delivered_patterns = [c.args[0].pattern for c in calls]
    assert normal_alert.pattern not in delivered_patterns or all(
        c.args[0].bypass_quiet_hours for c in calls if c.args[0].pattern == normal_alert.pattern
    ), "non-bypass alert should be suppressed during cold-start"
    assert bypass_alert.pattern in delivered_patterns, "bypass alert must fire during cold-start"
