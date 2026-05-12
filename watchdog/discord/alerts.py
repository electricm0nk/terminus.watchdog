"""Alert embed formatter and quiet-hours helper — Story 2.2."""
from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import discord

from watchdog.models import Alert

_CT = ZoneInfo("America/Chicago")

_COLORS: dict[str, int] = {
    "high": 0xFF4444,
    "medium": 0xFF8C00,
    "informational": 0x4A90E2,
}

_EMOJIS: dict[str, str] = {
    "high": "🚨",
    "medium": "⚠️",
    "informational": "ℹ️",
}

_PATTERN_DISPLAY: dict[str, str] = {
    "argocd-live-drift": "ArgoCD Live Drift",
    "argocd-image-promotion": "ArgoCD Image Promotion",
    "argocd-stuck-sync": "ArgoCD Stuck Sync",
    "argocd-order-day-unsync": "ArgoCD Order-Day Out-of-Sync",
}


def _format_duration(seconds: float) -> str:
    """Format duration_seconds into a human-readable string."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def format_alert_embed(alert: Alert) -> discord.Embed:
    """Convert an Alert into a Discord Embed with standardised fields and footer.

    Embed structure (per PRD §5.3 / UX §4.1–5.2):
    - Color and emoji determined by severity
    - Title: {emoji} {pattern display name}
    - Fields: Resource, Duration, Diagnosis, Recommended Action
    - Footer: "{pattern} · Detected {HH:MM CT} ({HH:MM UTC})"
    """
    color = _COLORS.get(alert.severity, 0x808080)
    emoji = _EMOJIS.get(alert.severity, "❓")
    display_name = _PATTERN_DISPLAY.get(alert.pattern, alert.pattern)

    now_utc = datetime.datetime.now(tz=datetime.UTC)
    now_ct = now_utc.astimezone(_CT)

    footer_text = (
        f"{alert.pattern} · Detected {now_ct:%H:%M} CT ({now_utc:%H:%M} UTC)"
    )

    embed = discord.Embed(
        title=f"{emoji} {display_name}",
        color=discord.Color(color),
    )
    embed.add_field(
        name="Resource",
        value=f"`{alert.resource_namespace}/{alert.resource_name}`",
        inline=False,
    )
    embed.add_field(
        name="Duration",
        value=_format_duration(alert.duration_seconds),
        inline=True,
    )
    embed.add_field(
        name="Diagnosis",
        value=alert.diagnosis,
        inline=False,
    )
    embed.add_field(
        name="Recommended Action",
        value=alert.recommended_action,
        inline=False,
    )
    embed.set_footer(text=footer_text)
    return embed


def is_quiet_hours() -> bool:
    """Return True when current America/Chicago time is between 22:00 and 07:00.

    Quiet hours suppress @mention pings for non-bypass High severity alerts (AC7).
    """
    now_ct = datetime.datetime.now(tz=_CT)
    hour = now_ct.hour
    return hour >= 22 or hour < 7
