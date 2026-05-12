"""Core data models for Terminus Watchdog Agent.

All models are frozen dataclasses — immutable value objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Alert:
    """Represents a detected platform condition that may require notification."""

    pattern: str
    severity: str  # "high" | "medium" | "informational"
    resource_name: str
    resource_namespace: str
    duration_seconds: float
    diagnosis: str
    recommended_action: str
    remediation_available: bool
    bypass_cooldown: bool = False
    bypass_quiet_hours: bool = False

    @property
    def suppression_key(self) -> str:
        """Unique key used for deduplication and suppression lookups."""
        return f"{self.pattern}:{self.resource_namespace}/{self.resource_name}"


@dataclass(frozen=True)
class ActiveAlert:
    """Tracks an alert that has been fired and may still be active."""

    alert: Alert
    first_seen: datetime
    last_notified: datetime
    notification_count: int
    discord_message_id: int | None


@dataclass(frozen=True)
class SuppressEntry:
    """Represents a suppression rule for a given alert key."""

    key: str
    expires_at: datetime
    reason: str
