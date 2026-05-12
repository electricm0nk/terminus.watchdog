"""Settings — environment-driven configuration for Terminus Watchdog Agent.

Sensitive fields (DISCORD_BOT_TOKEN, ARGOCD_TOKEN) are masked in __repr__.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable '{name}' is not set")
    return value


def _get(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return int(raw)


@dataclass
class Settings:
    """All configuration consumed from environment variables."""

    # Discord
    discord_bot_token: str = field(default_factory=lambda: _require("DISCORD_BOT_TOKEN"))
    discord_alerts_channel_id: int = field(
        default_factory=lambda: int(_require("DISCORD_ALERTS_CHANNEL_ID"))
    )
    discord_info_channel_id: int = field(
        default_factory=lambda: int(_require("DISCORD_INFO_CHANNEL_ID"))
    )
    discord_ops_user_ids: list[str] = field(
        default_factory=lambda: [
            uid.strip()
            for uid in _get("DISCORD_OPS_USER_IDS", "").split(",")
            if uid.strip()
        ]
    )

    # ArgoCD
    argocd_url: str = field(default_factory=lambda: _require("ARGOCD_URL"))
    argocd_token: str = field(default_factory=lambda: _require("ARGOCD_TOKEN"))

    # Temporal
    temporal_host: str = field(default_factory=lambda: _require("TEMPORAL_HOST"))
    temporal_namespace: str = field(
        default_factory=lambda: _get("TEMPORAL_NAMESPACE", "default")
    )
    temporal_cert_pem: str = field(default_factory=lambda: _get("TEMPORAL_CERT_PEM", ""))
    temporal_key_pem: str = field(default_factory=lambda: _get("TEMPORAL_KEY_PEM", ""))

    # Timing
    poll_interval_seconds: int = field(
        default_factory=lambda: _get_int("POLL_INTERVAL_SECONDS", 300)
    )
    heartbeat_interval_seconds: int = field(
        default_factory=lambda: _get_int("HEARTBEAT_INTERVAL_SECONDS", 21600)
    )
    detection_timeout_seconds: int = field(
        default_factory=lambda: _get_int("DETECTION_TIMEOUT_SECONDS", 10)
    )
    argocd_stuck_sync_threshold_minutes: int = field(
        default_factory=lambda: _get_int("ARGOCD_STUCK_SYNC_THRESHOLD_MINUTES", 5)
    )

    def __repr__(self) -> str:
        return (
            f"Settings("
            f"discord_bot_token=<masked>, "
            f"discord_alerts_channel_id={self.discord_alerts_channel_id}, "
            f"discord_info_channel_id={self.discord_info_channel_id}, "
            f"argocd_url={self.argocd_url!r}, "
            f"argocd_token=<masked>, "
            f"temporal_host={self.temporal_host!r}, "
            f"temporal_namespace={self.temporal_namespace!r}, "
            f"poll_interval_seconds={self.poll_interval_seconds}, "
            f"heartbeat_interval_seconds={self.heartbeat_interval_seconds}, "
            f"detection_timeout_seconds={self.detection_timeout_seconds}"
            f")"
        )
