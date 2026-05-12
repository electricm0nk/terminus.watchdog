"""Entrypoint for Terminus Watchdog Agent."""

from __future__ import annotations

import asyncio
import logging
import os

from pythonjsonlogger import jsonlogger

from watchdog.clients.argocd import ArgoCDClient
from watchdog.config import HighPriorityWindow, Settings
from watchdog.detectors.argocd import ArgoCDPoller, ArgoCDStuckSyncDetector
from watchdog.detectors.argocd_order_day import ArgoCDOrderDayDetector
from watchdog.discord.bot import WatchdogBot
from watchdog.health import start_health_server
from watchdog.loop import detection_loop
from watchdog.state import WatchdogState


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(  # type: ignore[attr-defined]
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


_ORDER_DAY_WINDOW = HighPriorityWindow(
    name="order-day",
    rrule_str="FREQ=WEEKLY;BYDAY=TU;BYHOUR=11;BYMINUTE=55",
    duration_hours=35.58,
    timezone="America/Chicago",
)


async def main() -> None:
    _configure_logging()
    logger = logging.getLogger(__name__)

    settings = Settings()
    logger.info("terminus-watchdog starting", extra={"config": repr(settings)})

    state = WatchdogState()

    # ArgoCD client
    argocd_client = ArgoCDClient(
        base_url=settings.argocd_url,
        token=settings.argocd_token,
    )

    # Register all E2 detectors
    detectors = [
        ArgoCDPoller(client=argocd_client),
        ArgoCDStuckSyncDetector(
            client=argocd_client,
            threshold_minutes=settings.argocd_stuck_sync_threshold_minutes,
        ),
        ArgoCDOrderDayDetector(client=argocd_client, window=_ORDER_DAY_WINDOW),
    ]

    # Discord bot
    bot = WatchdogBot(
        alerts_channel_id=settings.discord_alerts_channel_id,
        info_channel_id=settings.discord_info_channel_id,
        ops_user_ids=settings.discord_ops_user_ids,
    )

    # Run health server + detection loop concurrently
    health_task = asyncio.create_task(
        start_health_server(state, port=int(os.environ.get("HEALTH_PORT", "8080")))
    )
    loop_task = asyncio.create_task(
        detection_loop(bot=bot, detectors=detectors, state=state, settings=settings)
    )

    try:
        await asyncio.gather(health_task, loop_task)
    finally:
        await argocd_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
