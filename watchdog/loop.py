"""Detection loop — orchestrates all detectors, suppression, cooldown, and Discord routing.

Story 2.6: Detection Loop, Channel Routing, and Quiet-Hours Integration.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
from typing import TYPE_CHECKING

from watchdog.detectors.base import BaseDetector
from watchdog.models import ActiveAlert, Alert
from watchdog.state import WatchdogState

if TYPE_CHECKING:
    from watchdog.config import Settings
    from watchdog.discord.bot import WatchdogBot

log = logging.getLogger(__name__)

_DEGRADATION_THRESHOLD = 3


async def _run_detector(detector: BaseDetector, timeout_seconds: int) -> list[Alert] | None:
    """Run a single detector with a timeout guard.

    Returns None on failure (timeout or exception), list[Alert] on success.
    """
    try:
        return await asyncio.wait_for(detector.detect(), timeout=timeout_seconds)
    except TimeoutError:
        log.warning("Detector '%s' timed out after %ds", detector.pattern_id, timeout_seconds)
        return None
    except Exception as exc:
        log.error("Detector '%s' raised an unexpected error: %s", detector.pattern_id, exc)
        return None


def _cold_start_active(state: WatchdogState, grace_minutes: int) -> bool:
    """Return True if the cold-start grace period is still active."""
    elapsed = (datetime.datetime.utcnow() - state.startup_time).total_seconds()
    return elapsed < grace_minutes * 60


async def run_detection_cycle(
    bot: WatchdogBot,
    detectors: list[BaseDetector],
    state: WatchdogState,
    settings: Settings,
) -> None:
    """Run one full poll cycle over all registered detectors.

    For each alert returned by a detector:
    - Skip if suppressed
    - Skip if in cooldown
    - Skip during cold-start grace unless bypass_quiet_hours=True
    - Post to Discord via bot.post_alert
    - Record in state + start cooldown
    """
    grace_active = _cold_start_active(state, settings.cold_start_grace_minutes)
    if grace_active:
        log.debug("Cold-start grace period active — suppressing non-bypass alerts")

    for detector in detectors:
        result = await _run_detector(detector, settings.detection_timeout_seconds)

        # FR35 — Source degradation tracking
        pid = detector.pattern_id
        if result is None:
            state.detector_failure_counts[pid] = state.detector_failure_counts.get(pid, 0) + 1
            fail_count = state.detector_failure_counts[pid]
            if fail_count >= _DEGRADATION_THRESHOLD and pid not in state.detector_degradation_warned:
                state.detector_degradation_warned.add(pid)
                log.warning(
                    "Source degradation: detector '%s' failed %d times consecutively",
                    pid, fail_count,
                )
                try:
                    await bot.post_info(
                        f":warning: **Source degradation** — detector `{pid}` has failed "
                        f"{fail_count} times consecutively. Alerts may be missed."
                    )
                except Exception as exc:
                    log.error("Failed to post source degradation warning for '%s': %s", pid, exc)
            alerts: list[Alert] = []
        else:
            if state.detector_failure_counts.get(pid, 0) > 0:
                state.detector_failure_counts[pid] = 0
                state.detector_degradation_warned.discard(pid)
            alerts = result

        for alert in alerts:
            key = alert.suppression_key

            if state.is_suppressed(key):
                log.debug("Alert '%s' suppressed — skipping", key)
                continue

            if state.is_in_cooldown(key):
                log.debug("Alert '%s' in cooldown — skipping", key)
                continue

            if grace_active and not alert.bypass_quiet_hours:
                log.debug("Alert '%s' suppressed during cold-start grace", key)
                continue

            try:
                message_id = await bot.post_alert(alert, state)
            except Exception as exc:
                log.error("Failed to post alert '%s' to Discord: %s", key, exc)
                message_id = None

            now = datetime.datetime.utcnow()
            active = ActiveAlert(
                alert=alert,
                first_seen=now,
                last_notified=now,
                notification_count=1,
                discord_message_id=message_id,
            )
            state.add_active_alert(active, message_id)
            state.start_cooldown(key, minutes=float(settings.cooldown_minutes))

    if grace_active and not _cold_start_active(state, settings.cold_start_grace_minutes):
        log.info("Cold-start grace period expired — normal alert delivery resumed")


async def detection_loop(
    bot: WatchdogBot,
    detectors: list[BaseDetector],
    state: WatchdogState,
    settings: Settings,
) -> None:
    """Infinite detection loop.

    Runs run_detection_cycle on each poll interval until cancelled.
    """
    log.info(
        "Detection loop started — %d detector(s), poll=%ds, cold-start-grace=%dmin",
        len(detectors),
        settings.poll_interval_seconds,
        settings.cold_start_grace_minutes,
    )
    while True:
        await run_detection_cycle(bot=bot, detectors=detectors, state=state, settings=settings)
        await asyncio.sleep(settings.poll_interval_seconds)
