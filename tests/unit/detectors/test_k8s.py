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
