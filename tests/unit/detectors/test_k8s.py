"""Unit tests for k8s detectors: CrashLoopBackOff, DeploymentUnavailable, NodeNotReady.

Uses mocked KubernetesClient.
"""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

from watchdog.detectors.k8s import K8sCrashLoopDetector


def _make_pod(
    name: str = "pod-1",
    namespace: str = "default",
    container_name: str = "app",
    crash_loop: bool = False,
    restart_count: int = 0,
) -> MagicMock:
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = namespace

    cs = MagicMock()
    cs.name = container_name
    cs.restart_count = restart_count

    if crash_loop:
        cs.state.waiting.reason = "CrashLoopBackOff"
        cs.state.running = None
    else:
        cs.state.waiting = None
        cs.state.running = MagicMock()

    pod.status.container_statuses = [cs]
    return pod


def _make_k8s_client(pods: list[MagicMock]) -> AsyncMock:
    mock = AsyncMock()
    mock.list_pods = AsyncMock(return_value=pods)
    mock.list_deployments = AsyncMock(return_value=[])
    mock.list_nodes = AsyncMock(return_value=[])
    return mock


class TestK8sCrashLoopDetectorNoAlert:
    """Cases that should not produce alerts."""

    async def test_no_pods_no_alert(self) -> None:
        """Empty pod list → no alert."""
        client = _make_k8s_client([])
        detector = K8sCrashLoopDetector(k8s_client=client, recovery_seconds=120)
        alerts = await detector.detect()
        assert alerts == []

    async def test_healthy_pod_no_alert(self) -> None:
        """Running pod → no alert."""
        pod = _make_pod("pod-ok", crash_loop=False)
        client = _make_k8s_client([pod])
        detector = K8sCrashLoopDetector(k8s_client=client, recovery_seconds=120)
        alerts = await detector.detect()
        assert alerts == []

    async def test_crash_loop_pod_within_grace_period_no_alert(self) -> None:
        """CrashLoopBackOff pod within grace period → no alert."""
        pod = _make_pod("pod-new", crash_loop=True, restart_count=1)
        client = _make_k8s_client([pod])
        detector = K8sCrashLoopDetector(k8s_client=client, recovery_seconds=120)
        # First poll: first_seen = now → 0 seconds elapsed → no alert
        alerts = await detector.detect()
        assert alerts == []


class TestK8sCrashLoopDetectorMediumAlert:
    """CrashLoopBackOff beyond grace period → Medium alert."""

    async def test_crash_loop_beyond_grace_fires_medium_alert(self) -> None:
        """Pod first seen > recovery_seconds ago → Medium alert."""
        pod = _make_pod("pod-crash", namespace="app-ns", crash_loop=True, restart_count=2)
        client = _make_k8s_client([pod])
        detector = K8sCrashLoopDetector(k8s_client=client, recovery_seconds=120)

        # First poll
        await detector.detect()

        # Backdate first_seen
        pod_key = "app-ns/pod-crash/app"
        past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=180)
        detector._first_seen[pod_key] = past  # type: ignore[attr-defined]

        # Second poll
        alerts = await detector.detect()
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.pattern == "k8s-crashloopbackoff"
        assert alert.severity == "medium"
        assert alert.resource_name == "pod-crash"
        assert alert.resource_namespace == "app-ns"

    async def test_crash_loop_alert_suppression_key(self) -> None:
        """suppression_key = k8s-crashloopbackoff:{namespace}/{pod_name}."""
        pod = _make_pod("pod-c", namespace="ns1", crash_loop=True, restart_count=2)
        client = _make_k8s_client([pod])
        detector = K8sCrashLoopDetector(k8s_client=client, recovery_seconds=120)
        await detector.detect()
        pod_key = "ns1/pod-c/app"
        past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=180)
        detector._first_seen[pod_key] = past  # type: ignore[attr-defined]
        alerts = await detector.detect()
        assert alerts[0].suppression_key == "k8s-crashloopbackoff:ns1/pod-c"


class TestK8sCrashLoopDetectorHighEscalation:
    """CrashLoopBackOff with >5 restarts in 10-min window → High alert, bypass_cooldown."""

    async def test_high_restart_count_triggers_high_alert(self) -> None:
        """Pod with 6 restarts in 10min → High alert with bypass_cooldown=True."""
        pod = _make_pod("pod-esc", namespace="prod", crash_loop=True, restart_count=6)
        client = _make_k8s_client([pod])
        detector = K8sCrashLoopDetector(k8s_client=client, recovery_seconds=120)

        # Prime first_seen as past the grace period
        await detector.detect()
        pod_key = "prod/pod-esc/app"
        past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=180)
        detector._first_seen[pod_key] = past  # type: ignore[attr-defined]

        # Inject 6 restart events in the last 5 minutes
        now = datetime.datetime.now(datetime.UTC)
        detector._restart_log[pod_key] = [  # type: ignore[attr-defined]
            now - datetime.timedelta(minutes=i) for i in range(6)
        ]

        alerts = await detector.detect()
        high_alerts = [a for a in alerts if a.severity == "high"]
        assert len(high_alerts) == 1
        assert high_alerts[0].bypass_cooldown is True

    async def test_recovery_clears_tracking(self) -> None:
        """Pod no longer in CrashLoopBackOff → tracking cleared."""
        pod_crash = _make_pod("pod-r", crash_loop=True, restart_count=3)
        client = _make_k8s_client([pod_crash])
        detector = K8sCrashLoopDetector(k8s_client=client, recovery_seconds=120)

        await detector.detect()
        pod_key = "default/pod-r/app"
        assert pod_key in detector._first_seen  # type: ignore[attr-defined]

        # Pod recovers
        pod_ok = _make_pod("pod-r", crash_loop=False)
        client.list_pods = AsyncMock(return_value=[pod_ok])
        await detector.detect()
        assert pod_key not in detector._first_seen  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Story 3.5 — DeploymentUnavailableDetector
# ---------------------------------------------------------------------------

from watchdog.detectors.k8s import DeploymentUnavailableDetector, NodeNotReadyDetector  # noqa: E402


def _make_deployment(
    name: str = "deploy-1",
    namespace: str = "default",
    available: int = 1,
    desired: int = 1,
) -> MagicMock:
    dep = MagicMock()
    dep.metadata.name = name
    dep.metadata.namespace = namespace
    dep.status.available_replicas = available
    dep.status.replicas = desired
    return dep


def _make_node(name: str = "node-1", ready: bool = True) -> MagicMock:
    node = MagicMock()
    node.metadata.name = name
    cond = MagicMock()
    cond.type = "Ready"
    cond.status = "True" if ready else "False"
    node.status.conditions = [cond]
    return node


def _k8s_client_dep(deployments: list[MagicMock]) -> AsyncMock:
    mock = AsyncMock()
    mock.list_pods = AsyncMock(return_value=[])
    mock.list_deployments = AsyncMock(return_value=deployments)
    mock.list_nodes = AsyncMock(return_value=[])
    return mock


def _k8s_client_node(nodes: list[MagicMock]) -> AsyncMock:
    mock = AsyncMock()
    mock.list_pods = AsyncMock(return_value=[])
    mock.list_deployments = AsyncMock(return_value=[])
    mock.list_nodes = AsyncMock(return_value=nodes)
    return mock


class TestDeploymentUnavailableDetector:
    """Tests for DeploymentUnavailableDetector."""

    async def test_healthy_deployment_no_alert(self) -> None:
        """Deployment with available replicas → no alert."""
        dep = _make_deployment("dep-ok", available=1, desired=1)
        client = _k8s_client_dep([dep])
        detector = DeploymentUnavailableDetector(k8s_client=client, unavailable_minutes=5)
        alerts = await detector.detect()
        assert alerts == []

    async def test_unavailable_within_grace_no_alert(self) -> None:
        """Zero replicas first seen → no alert (grace period)."""
        dep = _make_deployment("dep-down", available=0, desired=2)
        client = _k8s_client_dep([dep])
        detector = DeploymentUnavailableDetector(k8s_client=client, unavailable_minutes=5)
        alerts = await detector.detect()
        assert alerts == []

    async def test_unavailable_beyond_threshold_fires_medium(self) -> None:
        """Zero replicas beyond threshold → Medium alert."""
        dep = _make_deployment("dep-down", namespace="prod", available=0, desired=2)
        client = _k8s_client_dep([dep])
        detector = DeploymentUnavailableDetector(k8s_client=client, unavailable_minutes=5)

        await detector.detect()  # first poll
        dep_key = "prod/dep-down"
        past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=6)
        detector._first_seen[dep_key] = past  # type: ignore[attr-defined]

        alerts = await detector.detect()
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.pattern == "k8s-deployment-unavailable"
        assert alert.severity == "medium"
        assert alert.resource_name == "dep-down"
        assert alert.resource_namespace == "prod"

    async def test_recovery_clears_tracking(self) -> None:
        """Deployment recovers (replicas > 0) → tracking cleared."""
        dep_down = _make_deployment("dep-r", available=0, desired=2)
        client = _k8s_client_dep([dep_down])
        detector = DeploymentUnavailableDetector(k8s_client=client, unavailable_minutes=5)
        await detector.detect()
        assert "default/dep-r" in detector._first_seen  # type: ignore[attr-defined]

        dep_ok = _make_deployment("dep-r", available=2, desired=2)
        client.list_deployments = AsyncMock(return_value=[dep_ok])
        await detector.detect()
        assert "default/dep-r" not in detector._first_seen  # type: ignore[attr-defined]


class TestNodeNotReadyDetector:
    """Tests for NodeNotReadyDetector."""

    async def test_ready_node_no_alert(self) -> None:
        """Ready node → no alert."""
        node = _make_node("node-ok", ready=True)
        client = _k8s_client_node([node])
        detector = NodeNotReadyDetector(k8s_client=client, notready_minutes=2)
        alerts = await detector.detect()
        assert alerts == []

    async def test_notready_within_grace_no_alert(self) -> None:
        """NotReady first seen → no alert (grace period)."""
        node = _make_node("node-bad", ready=False)
        client = _k8s_client_node([node])
        detector = NodeNotReadyDetector(k8s_client=client, notready_minutes=2)
        alerts = await detector.detect()
        assert alerts == []

    async def test_notready_beyond_threshold_fires_high(self) -> None:
        """NotReady beyond threshold → High alert."""
        node = _make_node("node-bad", ready=False)
        client = _k8s_client_node([node])
        detector = NodeNotReadyDetector(k8s_client=client, notready_minutes=2)

        await detector.detect()  # first poll
        past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=3)
        detector._first_seen["node-bad"] = past  # type: ignore[attr-defined]

        alerts = await detector.detect()
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.pattern == "k8s-node-notready"
        assert alert.severity == "high"
        assert alert.resource_name == "node-bad"

    async def test_recovery_clears_tracking(self) -> None:
        """Node recovers → tracking cleared."""
        node_bad = _make_node("node-r", ready=False)
        client = _k8s_client_node([node_bad])
        detector = NodeNotReadyDetector(k8s_client=client, notready_minutes=2)
        await detector.detect()
        assert "node-r" in detector._first_seen  # type: ignore[attr-defined]

        node_ok = _make_node("node-r", ready=True)
        client.list_nodes = AsyncMock(return_value=[node_ok])
        await detector.detect()
        assert "node-r" not in detector._first_seen  # type: ignore[attr-defined]
