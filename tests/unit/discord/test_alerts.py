"""Unit tests for Discord alert formatter and quiet hours — Story 2.2 (RED phase)."""
from __future__ import annotations

import pytest
from freezegun import freeze_time

from watchdog.discord.alerts import format_alert_embed, is_quiet_hours
from watchdog.models import Alert

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_alert(severity: str = "high") -> Alert:
    return Alert(
        pattern="argocd-live-drift",
        severity=severity,
        resource_name="fourdogs-emailfetcher",
        resource_namespace="fourdogs-emailfetcher-dev",
        duration_seconds=360.0,
        diagnosis="App is OutOfSync — live diff detected.",
        recommended_action="Investigate and sync via ArgoCD.",
        remediation_available=False,
    )


# ---------------------------------------------------------------------------
# Embed colour and emoji tests
# ---------------------------------------------------------------------------


def test_high_alert_embed_color_and_emoji() -> None:
    """High severity must use red colour and 🚨 emoji."""
    embed = format_alert_embed(_make_alert("high"))
    assert embed.color is not None
    assert embed.color.value == 0xFF4444
    assert embed.title is not None
    assert "🚨" in embed.title


def test_medium_alert_embed_color_and_emoji() -> None:
    """Medium severity must use orange colour and ⚠️ emoji."""
    embed = format_alert_embed(_make_alert("medium"))
    assert embed.color is not None
    assert embed.color.value == 0xFF8C00
    assert embed.title is not None
    assert "⚠️" in embed.title


def test_informational_alert_embed_color_and_emoji() -> None:
    """Informational severity must use blue colour and ℹ️ emoji."""
    embed = format_alert_embed(_make_alert("informational"))
    assert embed.color is not None
    assert embed.color.value == 0x4A90E2
    assert embed.title is not None
    assert "ℹ️" in embed.title


def test_embed_footer_contains_pattern_id() -> None:
    """Embed footer must contain the alert pattern identifier."""
    embed = format_alert_embed(_make_alert("high"))
    assert embed.footer is not None
    assert "argocd-live-drift" in embed.footer.text


# ---------------------------------------------------------------------------
# AC7 — Quiet Hours Behavior (acceptance gate)
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
@freeze_time("2026-01-15 04:00:00", tz_offset=0)  # 04:00 UTC = 22:00 CST (UTC-6 in Jan)
def test_ac_7_quiet_hours_is_true_at_2200_ct() -> None:
    """AC7: is_quiet_hours() must return True at 22:00 CT (10 PM Central)."""
    assert is_quiet_hours() is True


@pytest.mark.acceptance
@freeze_time("2026-01-15 18:00:00", tz_offset=0)  # 18:00 UTC = 12:00 CST
def test_ac_7_quiet_hours_is_false_at_1200_ct() -> None:
    """AC7: is_quiet_hours() must return False at 12:00 CT (noon Central)."""
    assert is_quiet_hours() is False


# ---------------------------------------------------------------------------
# AC9 — Alert Content Scannable in 90 Seconds (acceptance gate)
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
def test_ac_9_alert_content_scannable() -> None:
    """AC9: Embed must contain Resource, Duration, Diagnosis, and Recommended Action fields."""
    embed = format_alert_embed(_make_alert("high"))
    field_names = {f.name for f in embed.fields}
    assert "Resource" in field_names
    assert "Duration" in field_names
    assert "Diagnosis" in field_names
    assert "Recommended Action" in field_names
    # All fields must be non-empty
    for f in embed.fields:
        assert f.value, f"Field '{f.name}' must be non-empty"
