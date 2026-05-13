"""Temporal workflow remediation actions."""
from __future__ import annotations

import logging

from watchdog.clients.temporal import TemporalClient
from watchdog.models import Alert

log = logging.getLogger(__name__)


async def terminate_zombie_workflow(client: TemporalClient, alert: Alert) -> bool:
    """Terminate a zombie Temporal workflow identified by alert.resource_name.

    Only called for ``temporal-zombie-critical`` alerts (>24h threshold).
    Uses the workflow_id (latest run) since run_id is not stored on Alert.

    Returns True on success, False on failure.
    """
    workflow_id = alert.resource_name
    duration_hours = alert.duration_seconds / 3600
    reason = (
        f"watchdog-auto-terminate: workflow exceeded zombie-critical threshold "
        f"({duration_hours:.1f}h running)"
    )
    try:
        await client.terminate_workflow(workflow_id, reason=reason)
        log.info(
            "Remediated: terminated Temporal zombie workflow",
            extra={"workflow_id": workflow_id, "duration_hours": f"{duration_hours:.1f}"},
        )
        return True
    except Exception as exc:
        log.error(
            "Remediation failed: could not terminate Temporal workflow",
            extra={"workflow_id": workflow_id, "error": str(exc)},
        )
        return False
