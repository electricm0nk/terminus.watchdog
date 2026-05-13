"""Remediation engine — dispatches automated actions based on alert pattern."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from watchdog.models import Alert

if TYPE_CHECKING:
    from watchdog.clients.argocd import ArgoCDClient
    from watchdog.clients.temporal import TemporalClient

log = logging.getLogger(__name__)

# Patterns that have registered automated remediation handlers.
_REMEDIABLE_PATTERNS = frozenset({
    "temporal-zombie-critical",
    "temporal-seed-secrets-loop",
    "argocd-stuck-sync",
    "argocd-live-drift",
})


class RemediationEngine:
    """Dispatches automated remediation actions for alerts where remediation_available=True.

    Pattern → action mapping:
    - ``temporal-zombie-critical``: terminate the workflow via Temporal SDK
    - ``argocd-stuck-sync``: terminate stuck sync op then re-sync via ArgoCD API
    - ``argocd-live-drift``: sync application to revert to git source of truth
    """

    def __init__(
        self,
        temporal_client: TemporalClient,
        argocd_client: ArgoCDClient,
    ) -> None:
        self._temporal = temporal_client
        self._argocd = argocd_client

    async def remediate(self, alert: Alert) -> bool:
        """Dispatch remediation for the given alert.

        Returns True if remediation succeeded, False if it failed or no handler is registered.
        Only called when alert.remediation_available is True.
        """
        from watchdog.actions import argocd as argocd_actions
        from watchdog.actions import temporal as temporal_actions

        pattern = alert.pattern

        if pattern == "temporal-zombie-critical":
            return await temporal_actions.terminate_zombie_workflow(self._temporal, alert)

        if pattern == "temporal-seed-secrets-loop":
            return await temporal_actions.terminate_seed_secrets_loop(self._temporal, alert)

        if pattern == "argocd-stuck-sync":
            return await argocd_actions.terminate_stuck_sync(self._argocd, alert)

        if pattern == "argocd-live-drift":
            return await argocd_actions.sync_application(self._argocd, alert)

        log.debug("No remediation handler registered for pattern '%s'", pattern)
        return False
