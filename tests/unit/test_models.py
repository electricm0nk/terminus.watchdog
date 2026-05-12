"""[RED] Tests for watchdog.models — Alert, ActiveAlert, SuppressEntry dataclasses."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from watchdog.models import ActiveAlert, Alert, SuppressEntry


class TestAlert:
    def test_alert_fields(self) -> None:
        alert = Alert(
            pattern="argocd-degraded",
            severity="high",
            resource_name="my-app",
            resource_namespace="production",
            duration_seconds=120.0,
            diagnosis="App is OutOfSync",
            recommended_action="Check recent deployment",
            remediation_available=True,
        )
        assert alert.pattern == "argocd-degraded"
        assert alert.severity == "high"
        assert alert.resource_name == "my-app"
        assert alert.resource_namespace == "production"
        assert alert.duration_seconds == 120.0
        assert alert.diagnosis == "App is OutOfSync"
        assert alert.recommended_action == "Check recent deployment"
        assert alert.remediation_available is True
        assert alert.bypass_cooldown is False
        assert alert.bypass_quiet_hours is False

    def test_alert_bypass_flags_settable(self) -> None:
        alert = Alert(
            pattern="temporal-degraded",
            severity="medium",
            resource_name="temporal-server",
            resource_namespace="temporal",
            duration_seconds=30.0,
            diagnosis="Temporal frontend unreachable",
            recommended_action="Check Temporal namespace",
            remediation_available=False,
            bypass_cooldown=True,
            bypass_quiet_hours=True,
        )
        assert alert.bypass_cooldown is True
        assert alert.bypass_quiet_hours is True

    def test_alert_is_frozen(self) -> None:
        alert = Alert(
            pattern="test",
            severity="low",
            resource_name="r",
            resource_namespace="ns",
            duration_seconds=1.0,
            diagnosis="d",
            recommended_action="a",
            remediation_available=False,
        )
        with pytest.raises(Exception):
            alert.severity = "high"  # type: ignore[misc]

    def test_suppression_key(self) -> None:
        alert = Alert(
            pattern="argocd-degraded",
            severity="high",
            resource_name="my-app",
            resource_namespace="production",
            duration_seconds=60.0,
            diagnosis="OutOfSync",
            recommended_action="Sync",
            remediation_available=True,
        )
        assert alert.suppression_key == "argocd-degraded:production/my-app"

    def test_suppression_key_format(self) -> None:
        alert = Alert(
            pattern="pod-crashloop",
            severity="high",
            resource_name="worker-0",
            resource_namespace="terminus-watchdog",
            duration_seconds=300.0,
            diagnosis="CrashLoopBackOff",
            recommended_action="Inspect logs",
            remediation_available=False,
        )
        expected = "pod-crashloop:terminus-watchdog/worker-0"
        assert alert.suppression_key == expected


class TestActiveAlert:
    def test_active_alert_fields(self) -> None:
        alert = Alert(
            pattern="argocd-degraded",
            severity="high",
            resource_name="app",
            resource_namespace="ns",
            duration_seconds=60.0,
            diagnosis="d",
            recommended_action="a",
            remediation_available=True,
        )
        first_seen = datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)
        last_notified = datetime(2026, 5, 11, 10, 5, 0, tzinfo=UTC)
        active = ActiveAlert(
            alert=alert,
            first_seen=first_seen,
            last_notified=last_notified,
            notification_count=2,
            discord_message_id=12345678,
        )
        assert active.alert is alert
        assert active.first_seen == first_seen
        assert active.last_notified == last_notified
        assert active.notification_count == 2
        assert active.discord_message_id == 12345678

    def test_active_alert_is_frozen(self) -> None:
        alert = Alert(
            pattern="x",
            severity="low",
            resource_name="r",
            resource_namespace="ns",
            duration_seconds=1.0,
            diagnosis="d",
            recommended_action="a",
            remediation_available=False,
        )
        ts = datetime.now(tz=UTC)
        active = ActiveAlert(
            alert=alert,
            first_seen=ts,
            last_notified=ts,
            notification_count=0,
            discord_message_id=None,
        )
        with pytest.raises(Exception):
            active.notification_count = 5  # type: ignore[misc]


class TestSuppressEntry:
    def test_suppress_entry_fields(self) -> None:
        expires = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)
        entry = SuppressEntry(
            key="argocd-degraded:production/my-app",
            expires_at=expires,
            reason="maintenance window",
        )
        assert entry.key == "argocd-degraded:production/my-app"
        assert entry.expires_at == expires
        assert entry.reason == "maintenance window"

    def test_suppress_entry_is_frozen(self) -> None:
        expires = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)
        entry = SuppressEntry(
            key="k",
            expires_at=expires,
            reason="r",
        )
        with pytest.raises(Exception):
            entry.reason = "other"  # type: ignore[misc]
