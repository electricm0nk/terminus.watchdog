"""Entrypoint for Terminus Watchdog Agent."""

from __future__ import annotations

import asyncio
import logging
import os

from pythonjsonlogger import jsonlogger

from watchdog.actions import RemediationEngine
from watchdog.clients.argocd import ArgoCDClient
from watchdog.clients.k8s import KubernetesClient
from watchdog.clients.loki import LokiClient
from watchdog.clients.temporal import TemporalClient
from watchdog.config import HighPriorityWindow, Settings
from watchdog.detectors.argocd import ArgoCDPoller, ArgoCDStuckSyncDetector
from watchdog.detectors.argocd_order_day import ArgoCDOrderDayDetector
from watchdog.detectors.k8s import DeploymentUnavailableDetector, K8sCrashLoopDetector, NodeNotReadyDetector
from watchdog.detectors.loki import TemporalPostgresConnectivityDetector
from watchdog.detectors.temporal import TemporalStaleDetector, TemporalZombieDetector, TemporalSeedSecretsDetector
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

    # Temporal client
    temporal_client = TemporalClient(
        host=settings.temporal_host,
        namespace=settings.temporal_namespace,
        cert_pem=settings.temporal_cert_pem,
        key_pem=settings.temporal_key_pem,
    )
    await temporal_client.connect()

    # Loki client (optional — only created if LOKI_URL is set)
    loki_client: LokiClient | None = None
    if settings.loki_url:
        loki_client = LokiClient(base_url=settings.loki_url)

    # Kubernetes client
    k8s_client = KubernetesClient()
    try:
        await k8s_client.connect()
        k8s_connected = True
    except Exception:
        logger.warning("KubernetesClient: in-cluster config unavailable — k8s detectors disabled")
        k8s_connected = False

    # Register all detectors
    detectors = [
        # E2 — ArgoCD
        ArgoCDPoller(client=argocd_client),
        ArgoCDStuckSyncDetector(
            client=argocd_client,
            threshold_minutes=settings.argocd_stuck_sync_threshold_minutes,
        ),
        ArgoCDOrderDayDetector(client=argocd_client, window=_ORDER_DAY_WINDOW),
        # E3 — Temporal
        TemporalZombieDetector(
            temporal_client=temporal_client,
            zombie_activity_hours=settings.zombie_activity_hours,
            zombie_critical_hours=settings.zombie_critical_hours,
        ),
        TemporalStaleDetector(
            temporal_client=temporal_client,
            stale_minutes=settings.stale_workflow_minutes,
        ),
        TemporalSeedSecretsDetector(
            temporal_client=temporal_client,
        ),
        # E3 — Loki
        TemporalPostgresConnectivityDetector(
            loki_client=loki_client,
            loki_url=settings.loki_url,
        ),
    ]

    # E3 — k8s detectors (only if in-cluster config succeeded)
    if k8s_connected:
        detectors += [
            K8sCrashLoopDetector(
                k8s_client=k8s_client,
                recovery_seconds=settings.crashloop_recovery_seconds,
            ),
            DeploymentUnavailableDetector(
                k8s_client=k8s_client,
                unavailable_minutes=settings.deployment_unavailable_minutes,
            ),
            NodeNotReadyDetector(
                k8s_client=k8s_client,
                notready_minutes=settings.node_notready_minutes,
            ),
        ]

    # Discord bot
    bot = WatchdogBot(
        alerts_channel_id=settings.discord_alerts_channel_id,
        info_channel_id=settings.discord_info_channel_id,
        ops_user_ids=settings.discord_ops_user_ids,
    )

    # Remediation engine
    remediation_engine = RemediationEngine(
        temporal_client=temporal_client,
        argocd_client=argocd_client,
    )

    async def _run_bot_then_loop() -> None:
        """Start the Discord bot and wait for it to be ready before launching the detection loop."""
        bot_task = asyncio.create_task(bot.start(settings.discord_bot_token))
        await asyncio.wait_for(bot.ready_event.wait(), timeout=60)
        loop_task = asyncio.create_task(
            detection_loop(
                bot=bot,
                detectors=detectors,
                state=state,
                settings=settings,
                remediation_engine=remediation_engine,
            )
        )
        await asyncio.gather(bot_task, loop_task)

    # Run health server + bot+detection concurrently
    health_task = asyncio.create_task(
        start_health_server(state, port=int(os.environ.get("HEALTH_PORT", "8080")))
    )
    bot_loop_task = asyncio.create_task(_run_bot_then_loop())

    try:
        await asyncio.gather(health_task, bot_loop_task)
    finally:
        await argocd_client.aclose()
        await temporal_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
