"""ArgoCD remediation actions."""
from __future__ import annotations

import logging

from watchdog.clients.argocd import ArgoCDAuthError, ArgoCDClient, ArgoCDTimeoutError
from watchdog.models import Alert

log = logging.getLogger(__name__)


async def sync_application(client: ArgoCDClient, alert: Alert) -> bool:
    """Trigger an ArgoCD sync for an OutOfSync or drifted application.

    Used for ``argocd-live-drift`` — reverts live state to git source of truth.

    Returns True on success, False on failure.
    """
    name = alert.resource_name
    try:
        await client.sync_application(name)
        log.info("Remediated: triggered ArgoCD sync", extra={"app": name})
        return True
    except (ArgoCDAuthError, ArgoCDTimeoutError) as exc:
        log.error(
            "Remediation failed: ArgoCD sync error",
            extra={"app": name, "error": str(exc)},
        )
        return False
    except Exception as exc:
        log.error(
            "Remediation failed: unexpected error syncing app",
            extra={"app": name, "error": str(exc)},
        )
        return False


async def terminate_stuck_sync(client: ArgoCDClient, alert: Alert) -> bool:
    """Terminate a stuck ArgoCD sync operation then re-trigger sync.

    Used for ``argocd-stuck-sync`` — kills the hung operation then issues a fresh sync.

    Returns True if both terminate and re-sync succeed, False otherwise.
    """
    name = alert.resource_name
    try:
        await client.terminate_stuck_sync(name)
        log.info("Remediated: terminated stuck sync operation", extra={"app": name})
    except (ArgoCDAuthError, ArgoCDTimeoutError, Exception) as exc:
        log.error(
            "Remediation failed: could not terminate stuck sync",
            extra={"app": name, "error": str(exc)},
        )
        return False

    try:
        await client.sync_application(name)
        log.info("Remediated: re-triggered sync after termination", extra={"app": name})
        return True
    except (ArgoCDAuthError, ArgoCDTimeoutError, Exception) as exc:
        log.error(
            "Remediation partial failure: terminated stuck sync but re-sync failed",
            extra={"app": name, "error": str(exc)},
        )
        return False
