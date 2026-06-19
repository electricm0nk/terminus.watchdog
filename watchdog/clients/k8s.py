"""Kubernetes async client wrapper for Terminus Watchdog Agent."""
from __future__ import annotations

import logging
from typing import Any

from kubernetes_asyncio import config
from kubernetes_asyncio.client.api import AppsV1Api, CoreV1Api
from kubernetes_asyncio.client.exceptions import ApiException

logger = logging.getLogger(__name__)


class KubernetesApiError(Exception):
    """Raised when a Kubernetes API call fails."""


class KubernetesClient:
    """Async Kubernetes client using in-cluster config.

    Wraps kubernetes-asyncio CoreV1Api and AppsV1Api.
    """

    def __init__(self) -> None:
        self._core: CoreV1Api | None = None
        self._apps: AppsV1Api | None = None

    async def connect(self) -> None:
        """Load in-cluster config and initialise API clients."""
        config.load_incluster_config()  # type: ignore[no-untyped-call]
        self._core = CoreV1Api()
        self._apps = AppsV1Api()

    async def list_pods(self, namespace: str = "") -> list[Any]:
        """Return all pods (all namespaces by default).

        Raises:
            KubernetesApiError: on API failure.
        """
        core = self._require_core()
        try:
            if namespace:
                resp = await core.list_namespaced_pod(namespace)
            else:
                resp = await core.list_pod_for_all_namespaces()
            return list(resp.items)
        except ApiException as exc:
            raise KubernetesApiError(f"list_pods failed: {exc.status} {exc.reason}") from exc

    async def list_deployments(self, namespace: str = "") -> list[Any]:
        """Return all deployments (all namespaces by default).

        Raises:
            KubernetesApiError: on API failure.
        """
        apps = self._require_apps()
        try:
            if namespace:
                resp = await apps.list_namespaced_deployment(namespace)
            else:
                resp = await apps.list_deployment_for_all_namespaces()
            return list(resp.items)
        except ApiException as exc:
            raise KubernetesApiError(f"list_deployments failed: {exc.status} {exc.reason}") from exc

    async def list_nodes(self) -> list[Any]:
        """Return all cluster nodes.

        Raises:
            KubernetesApiError: on API failure.
        """
        core = self._require_core()
        try:
            resp = await core.list_node()
            return list(resp.items)
        except ApiException as exc:
            raise KubernetesApiError(f"list_nodes failed: {exc.status} {exc.reason}") from exc

    def _require_core(self) -> CoreV1Api:
        if self._core is None:
            raise KubernetesApiError("KubernetesClient not connected — call connect() first")
        return self._core

    def _require_apps(self) -> AppsV1Api:
        if self._apps is None:
            raise KubernetesApiError("KubernetesClient not connected — call connect() first")
        return self._apps
