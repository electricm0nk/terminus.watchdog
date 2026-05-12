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


@pytest.mark.acceptance
@pytest.mark.asyncio
async def test_ac_2_temporal_zombie_detection() -> None:
    """AC2 — Temporal zombie workflow detection end-to-end.

    Mocked TemporalClient returning a workflow running >3h →
    temporal-zombie-activity Medium alert delivered via bot.post_alert.
    """
    from unittest.mock import AsyncMock, MagicMock

    from watchdog.clients.temporal import TemporalClient
    from watchdog.detectors.temporal import TemporalZombieDetector

    # Build a mock workflow running for 3 hours
    wf = MagicMock()
    wf.id = "workflow-123"
    wf.run_id = "run-abc"
    wf.task_queue = "temporal-namespace"
    wf.start_time = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=3)

    temporal_client = MagicMock(spec=TemporalClient)
    temporal_client.list_running_workflows = AsyncMock(return_value=[wf])

    detector = TemporalZombieDetector(
        temporal_client=temporal_client,
        zombie_activity_hours=2,
        zombie_critical_hours=24,
    )

    bot = MagicMock()
    bot.post_alert = AsyncMock(return_value=99002)

    state = WatchdogState()
    state.startup_time = datetime.datetime.utcnow() - datetime.timedelta(minutes=60)

    await run_detection_cycle(bot=bot, detectors=[detector], state=state, settings=_make_settings())

    bot.post_alert.assert_awaited_once()
    posted_alert = bot.post_alert.call_args.args[0]
    assert posted_alert.pattern == "temporal-zombie-activity"
    assert posted_alert.severity == "medium"
