"""Unit tests for KubernetesClient.

Uses MagicMock to simulate kubernetes-asyncio API calls.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from watchdog.clients.k8s import KubernetesApiError, KubernetesClient


def _mock_pod(
    name: str = "pod-1",
    namespace: str = "default",
    crash_loop: bool = False,
    restart_count: int = 0,
) -> MagicMock:
    """Build a mock V1Pod with container status set appropriately."""
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = namespace

    container_status = MagicMock()
    container_status.name = "app"
    container_status.restart_count = restart_count

    if crash_loop:
        container_status.state.waiting.reason = "CrashLoopBackOff"
        container_status.state.running = None
    else:
        container_status.state.waiting = None
        container_status.state.running.started_at = MagicMock()

    pod.status.container_statuses = [container_status]
    pod.status.phase = "Running" if not crash_loop else "Pending"
    return pod


def _mock_deployment(
    name: str = "deploy-1",
    namespace: str = "default",
    available_replicas: int = 1,
    desired_replicas: int = 1,
) -> MagicMock:
    dep = MagicMock()
    dep.metadata.name = name
    dep.metadata.namespace = namespace
    dep.status.available_replicas = available_replicas
    dep.status.replicas = desired_replicas
    return dep


def _mock_node(name: str = "node-1", ready: bool = True) -> MagicMock:
    node = MagicMock()
    node.metadata.name = name
    condition = MagicMock()
    condition.type = "Ready"
    condition.status = "True" if ready else "False"
    node.status.conditions = [condition]
    return node


class TestKubernetesClientPods:
    """Tests for KubernetesClient.list_pods()."""

    async def test_list_pods_returns_pods(self) -> None:
        """list_pods returns all pods from the API."""
        mock_pod = _mock_pod("pod-1")
        with patch("watchdog.clients.k8s.config") as mock_config, \
             patch("watchdog.clients.k8s.CoreV1Api") as mock_core_cls, \
             patch("watchdog.clients.k8s.AppsV1Api"):
            mock_config.load_incluster_config = MagicMock()
            mock_core = AsyncMock()
            mock_core.list_pod_for_all_namespaces = AsyncMock(
                return_value=MagicMock(items=[mock_pod])
            )
            mock_core_cls.return_value = mock_core

            client = KubernetesClient()
            await client.connect()
            pods = await client.list_pods()

        assert len(pods) == 1
        assert pods[0].metadata.name == "pod-1"

    async def test_list_pods_api_error_raises_k8s_api_error(self) -> None:
        """kubernetes_asyncio exception is wrapped in KubernetesApiError."""
        from kubernetes_asyncio.client.exceptions import ApiException

        with patch("watchdog.clients.k8s.config") as mock_config, \
             patch("watchdog.clients.k8s.CoreV1Api") as mock_core_cls, \
             patch("watchdog.clients.k8s.AppsV1Api"):
            mock_config.load_incluster_config = MagicMock()
            mock_core = AsyncMock()
            mock_core.list_pod_for_all_namespaces = AsyncMock(
                side_effect=ApiException(status=403, reason="Forbidden")
            )
            mock_core_cls.return_value = mock_core

            client = KubernetesClient()
            await client.connect()
            with pytest.raises(KubernetesApiError):
                await client.list_pods()


class TestKubernetesClientDeployments:
    """Tests for KubernetesClient.list_deployments()."""

    async def test_list_deployments_returns_deployments(self) -> None:
        """list_deployments returns all deployments from the API."""
        mock_dep = _mock_deployment("deploy-1")
        with patch("watchdog.clients.k8s.config") as mock_config, \
             patch("watchdog.clients.k8s.CoreV1Api"), \
             patch("watchdog.clients.k8s.AppsV1Api") as mock_apps_cls:
            mock_config.load_incluster_config = MagicMock()
            mock_apps = AsyncMock()
            mock_apps.list_deployment_for_all_namespaces = AsyncMock(
                return_value=MagicMock(items=[mock_dep])
            )
            mock_apps_cls.return_value = mock_apps

            client = KubernetesClient()
            await client.connect()
            deployments = await client.list_deployments()

        assert len(deployments) == 1


class TestKubernetesClientNodes:
    """Tests for KubernetesClient.list_nodes()."""

    async def test_list_nodes_returns_nodes(self) -> None:
        """list_nodes returns all nodes from the API."""
        mock_node = _mock_node("node-1")
        with patch("watchdog.clients.k8s.config") as mock_config, \
             patch("watchdog.clients.k8s.CoreV1Api") as mock_core_cls, \
             patch("watchdog.clients.k8s.AppsV1Api"):
            mock_config.load_incluster_config = MagicMock()
            mock_core = AsyncMock()
            mock_core.list_pod_for_all_namespaces = AsyncMock(return_value=MagicMock(items=[]))
            mock_core.list_node = AsyncMock(return_value=MagicMock(items=[mock_node]))
            mock_core_cls.return_value = mock_core

            client = KubernetesClient()
            await client.connect()
            nodes = await client.list_nodes()

        assert len(nodes) == 1
        assert nodes[0].metadata.name == "node-1"


class TestKubernetesClientConnect:
    """Regression tests for in-cluster config loading semantics."""

    async def test_connect_uses_sync_incluster_loader(self) -> None:
        with patch("watchdog.clients.k8s.config") as mock_config, \
             patch("watchdog.clients.k8s.CoreV1Api") as mock_core_cls, \
             patch("watchdog.clients.k8s.AppsV1Api") as mock_apps_cls:
            mock_config.load_incluster_config = MagicMock()

            client = KubernetesClient()
            await client.connect()

        mock_config.load_incluster_config.assert_called_once_with()
        mock_core_cls.assert_called_once_with()
        mock_apps_cls.assert_called_once_with()
