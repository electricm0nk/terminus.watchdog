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


async def terminate_seed_secrets_loop(client: TemporalClient, alert: Alert) -> bool:
    """Terminate a ReleaseWorkflow stuck in a SeedSecrets activity failure loop.

    ``SeedSecrets`` calls a Semaphore task template named ``seed-{service}-secrets``.
    If the template is missing, the activity retries indefinitely with retryable errors.
    Terminating clears the workflow and surfaces a clear signal to create the template.

    Returns True on success, False on failure.
    """
    workflow_id = alert.resource_name
    reason = (
        "watchdog-auto-terminate: SeedSecrets activity stuck in failure loop — "
        "Semaphore task template missing. Create the required template and re-trigger the release."
    )
    try:
        await client.terminate_workflow(workflow_id, reason=reason)
        log.info(
            "Remediated: terminated SeedSecrets-loop workflow",
            extra={"workflow_id": workflow_id},
        )
        return True
    except Exception as exc:
        log.error(
            "Remediation failed: could not terminate SeedSecrets-loop workflow",
            extra={"workflow_id": workflow_id, "error": str(exc)},
        )
        return False
