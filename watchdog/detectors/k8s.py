"""Kubernetes-based detectors for Terminus Watchdog Agent.

Detectors:
- K8sCrashLoopDetector: CrashLoopBackOff detection (Story 3.4)
- DeploymentUnavailableDetector: zero-available-replicas detection (Story 3.5)
- NodeNotReadyDetector: NotReady node detection (Story 3.5)
"""
from __future__ import annotations

import datetime
import logging
from typing import Any

from watchdog.detectors.base import BaseDetector
from watchdog.models import Alert

logger = logging.getLogger(__name__)

_RESTART_WINDOW_MINUTES = 10
_HIGH_RESTART_THRESHOLD = 5  # >5 restarts in window → High + bypass_cooldown


# ---------------------------------------------------------------------------
# Story 3.4 — CrashLoopBackOff
# ---------------------------------------------------------------------------


class K8sCrashLoopDetector(BaseDetector):
    """Detect pods stuck in CrashLoopBackOff.

    - First poll: records first_seen timestamp, no alert.
    - Beyond ``recovery_seconds`` with no recovery → ``k8s-crashloopbackoff`` Medium.
    - >5 restarts in 10-min window → High, ``bypass_cooldown=True``.
    - Pod recovers: tracking cleared.
    """

    pattern_id = "k8s-crashloopbackoff"

    def __init__(self, k8s_client: Any, recovery_seconds: int = 120) -> None:
        self._client = k8s_client
        self._recovery_seconds = recovery_seconds
        # pod_key → first-seen datetime
        self._first_seen: dict[str, datetime.datetime] = {}
        # pod_key → list of recent restart event datetimes
        self._restart_log: dict[str, list[datetime.datetime]] = {}

    async def detect(self) -> list[Alert]:
        """Scan all pods for CrashLoopBackOff state and return alerts."""
        pods = await self._client.list_pods()
        now = datetime.datetime.now(datetime.UTC)
        alerts: list[Alert] = []
        active_keys: set[str] = set()

        for pod in pods:
            meta = pod.metadata
            ns = meta.namespace or "default"
            pod_name = meta.name or "unknown"

            container_statuses = (pod.status.container_statuses or []) if pod.status else []

            for cs in container_statuses:
                if not _is_crashloop(cs):
                    continue

                container_name = cs.name or "unknown"
                pod_key = f"{ns}/{pod_name}/{container_name}"
                active_keys.add(pod_key)

                # Record first-seen
                if pod_key not in self._first_seen:
                    self._first_seen[pod_key] = now
                    self._restart_log[pod_key] = []

                # Track restart events
                restart_log = self._restart_log[pod_key]
                restart_count: int = cs.restart_count or 0
                _sync_restart_events(restart_log, restart_count, now, _RESTART_WINDOW_MINUTES)

                elapsed = now - self._first_seen[pod_key]
                if elapsed.total_seconds() < self._recovery_seconds:
                    continue  # still in grace period

                # Check for high-escalation (>5 restarts in window)
                recent_restarts = len(restart_log)
                if recent_restarts > _HIGH_RESTART_THRESHOLD:
                    alerts.append(
                        Alert(
                            pattern=self.pattern_id,
                            severity="high",
                            resource_name=pod_name,
                            resource_namespace=ns,
                            duration_seconds=elapsed.total_seconds(),
                            bypass_cooldown=True,
                            diagnosis=(
                                f"Pod {ns}/{pod_name} container '{container_name}' is in CrashLoopBackOff "
                                f"with {recent_restarts} restarts in the last {_RESTART_WINDOW_MINUTES} minutes."
                            ),
                            recommended_action=(
                                f"kubectl logs -n {ns} {pod_name} -c {container_name} --previous; "
                                f"kubectl describe pod -n {ns} {pod_name}"
                            ),
                            remediation_available=False,
                        )
                    )
                else:
                    alerts.append(
                        Alert(
                            pattern=self.pattern_id,
                            severity="medium",
                            resource_name=pod_name,
                            resource_namespace=ns,
                            duration_seconds=elapsed.total_seconds(),
                            bypass_cooldown=False,
                            diagnosis=(
                                f"Pod {ns}/{pod_name} container '{container_name}' is in CrashLoopBackOff "
                                f"for {int(elapsed.total_seconds())}s."
                            ),
                            recommended_action=(
                                f"kubectl logs -n {ns} {pod_name} -c {container_name} --previous; "
                                f"kubectl describe pod -n {ns} {pod_name}"
                            ),
                            remediation_available=False,
                        )
                    )

        # Clear tracking for recovered pods
        recovered = set(self._first_seen.keys()) - active_keys
        for key in recovered:
            self._first_seen.pop(key, None)
            self._restart_log.pop(key, None)

        return alerts


def _is_crashloop(container_status: Any) -> bool:
    """Return True if the container status indicates CrashLoopBackOff."""
    try:
        return (
            container_status.state is not None
            and container_status.state.waiting is not None
            and container_status.state.waiting.reason == "CrashLoopBackOff"
        )
    except AttributeError:
        return False


def _sync_restart_events(
    log: list[datetime.datetime],
    current_count: int,
    now: datetime.datetime,
    window_minutes: int,
) -> None:
    """Maintain a sliding-window list of restart event timestamps.

    We infer a restart happened if the restart_count increases. This function
    adds timestamps for newly detected restarts and prunes old ones.
    """
    # Prune events outside the window
    cutoff = now - datetime.timedelta(minutes=window_minutes)
    while log and log[0] < cutoff:
        log.pop(0)

    # If the restart count exceeds the log size, infer new restarts
    while len(log) < current_count:
        log.append(now)


# ---------------------------------------------------------------------------
# Story 3.5 — DeploymentUnavailable
# ---------------------------------------------------------------------------


class DeploymentUnavailableDetector(BaseDetector):
    """Detect deployments with zero available replicas for longer than a threshold.

    Fires ``k8s-deployment-unavailable`` Medium alert.
    """

    pattern_id = "k8s-deployment-unavailable"

    def __init__(self, k8s_client: Any, unavailable_minutes: int = 5) -> None:
        self._client = k8s_client
        self._unavailable_minutes = unavailable_minutes
        self._first_seen: dict[str, datetime.datetime] = {}

    async def detect(self) -> list[Alert]:
        """Scan deployments for zero-available-replicas beyond threshold."""
        deployments = await self._client.list_deployments()
        now = datetime.datetime.now(datetime.UTC)
        alerts: list[Alert] = []
        active_keys: set[str] = set()

        for dep in deployments:
            ns = dep.metadata.namespace or "default"
            name = dep.metadata.name or "unknown"
            dep_key = f"{ns}/{name}"

            available = dep.status.available_replicas or 0
            desired = dep.status.replicas or 0

            if available == 0 and desired > 0:
                active_keys.add(dep_key)
                if dep_key not in self._first_seen:
                    self._first_seen[dep_key] = now
                    continue

                elapsed = now - self._first_seen[dep_key]
                if elapsed.total_seconds() < self._unavailable_minutes * 60:
                    continue

                alerts.append(
                    Alert(
                        pattern=self.pattern_id,
                        severity="medium",
                        resource_name=name,
                        resource_namespace=ns,
                        duration_seconds=elapsed.total_seconds(),
                        bypass_cooldown=False,
                        diagnosis=(
                            f"Deployment {ns}/{name} has 0/{desired} replicas available "
                            f"for {int(elapsed.total_seconds() / 60)} minutes."
                        ),
                        recommended_action=(
                            f"kubectl describe deployment -n {ns} {name}; "
                            f"kubectl get pods -n {ns} -l app={name}"
                        ),
                        remediation_available=False,
                    )
                )

        recovered = set(self._first_seen.keys()) - active_keys
        for key in recovered:
            self._first_seen.pop(key, None)

        return alerts


# ---------------------------------------------------------------------------
# Story 3.5 — NodeNotReady
# ---------------------------------------------------------------------------


class NodeNotReadyDetector(BaseDetector):
    """Detect cluster nodes in NotReady state for longer than a threshold.

    Fires ``k8s-node-notready`` High alert.
    """

    pattern_id = "k8s-node-notready"

    def __init__(self, k8s_client: Any, notready_minutes: int = 2) -> None:
        self._client = k8s_client
        self._notready_minutes = notready_minutes
        self._first_seen: dict[str, datetime.datetime] = {}

    async def detect(self) -> list[Alert]:
        """Scan nodes for NotReady condition beyond threshold."""
        nodes = await self._client.list_nodes()
        now = datetime.datetime.now(datetime.UTC)
        alerts: list[Alert] = []
        active_keys: set[str] = set()

        for node in nodes:
            name = node.metadata.name or "unknown"
            if not _node_is_not_ready(node):
                continue

            active_keys.add(name)
            if name not in self._first_seen:
                self._first_seen[name] = now
                continue

            elapsed = now - self._first_seen[name]
            if elapsed.total_seconds() < self._notready_minutes * 60:
                continue

            alerts.append(
                Alert(
                    pattern=self.pattern_id,
                    severity="high",
                    resource_name=name,
                    resource_namespace="",
                    duration_seconds=elapsed.total_seconds(),
                    bypass_cooldown=False,
                    diagnosis=(
                        f"Node {name} is NotReady for {int(elapsed.total_seconds() / 60)} minutes."
                    ),
                    recommended_action=(
                        f"kubectl describe node {name}; "
                        "kubectl get events --field-selector source.host={name}"
                    ),
                    remediation_available=False,
                )
            )

        recovered = set(self._first_seen.keys()) - active_keys
        for key in recovered:
            self._first_seen.pop(key, None)

        return alerts


def _node_is_not_ready(node: Any) -> bool:
    """Return True if the node's Ready condition is False or Unknown."""
    try:
        for condition in node.status.conditions or []:
            if condition.type == "Ready":
                return bool(condition.status != "True")
        return True  # No Ready condition found → treat as NotReady
    except AttributeError:
        return False
