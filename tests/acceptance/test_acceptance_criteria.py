"""PRD Acceptance Criteria tests — Terminus Watchdog Agent."""
from __future__ import annotations

import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from watchdog.clients.argocd import ArgoCDClient
from watchdog.detectors.argocd import ArgoCDPoller
from watchdog.loop import run_detection_cycle
from watchdog.state import WatchdogState


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.poll_interval_seconds = 300
    s.detection_timeout_seconds = 10
    s.cooldown_minutes = 30
    s.cold_start_grace_minutes = 30
    return s


@pytest.mark.acceptance
@pytest.mark.asyncio
async def test_ac_1_argocd_outsync_classification() -> None:
    """AC1 — ArgoCD OutOfSync classification end-to-end.

    Mocked OutOfSync app → argocd-live-drift High alert delivered to
    DISCORD_ALERTS_CHANNEL_ID.
    """
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

    bot = MagicMock()
    bot.post_alert = AsyncMock(return_value=99001)

    state = WatchdogState()
    state.startup_time = datetime.datetime.utcnow() - datetime.timedelta(minutes=60)

    await run_detection_cycle(bot=bot, detectors=[poller], state=state, settings=_make_settings())

    bot.post_alert.assert_awaited_once()
    posted_alert = bot.post_alert.call_args.args[0]
    assert posted_alert.pattern == "argocd-live-drift"
    assert posted_alert.severity == "high"
