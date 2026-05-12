"""WatchdogState — shared mutable state protected by a single asyncio.Lock."""

from __future__ import annotations

import asyncio
import datetime

from watchdog.models import ActiveAlert, SuppressEntry


class WatchdogState:
    """Central state container for the watchdog agent.

    All mutations must be performed while holding ``_lock``.
    """

    def __init__(self) -> None:
        self._lock: asyncio.Lock = asyncio.Lock()
        self.active_alerts: dict[str, ActiveAlert] = {}
        self.suppressed: dict[str, SuppressEntry] = {}
        self.quiet_hours_active: bool = False
        self._cooldowns: dict[str, datetime.datetime] = {}
        # Set at startup; used by detection loop for cold-start grace suppression.
        self.startup_time: datetime.datetime = datetime.datetime.utcnow()
        # FR35 — Source degradation tracking
        self.detector_failure_counts: dict[str, int] = {}
        self.detector_degradation_warned: set[str] = set()

    # ------------------------------------------------------------------
    # Suppression helpers
    # ------------------------------------------------------------------

    def is_suppressed(self, key: str) -> bool:
        """Return True if the given suppression key is currently active."""
        entry = self.suppressed.get(key)
        if entry is None:
            return False
        return entry.expires_at > datetime.datetime.utcnow()

    def add_suppression(self, key: str, reason: str, duration_minutes: float) -> None:
        """Suppress alerts for ``key`` for ``duration_minutes`` minutes."""
        expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=duration_minutes)
        self.suppressed[key] = SuppressEntry(key=key, expires_at=expires_at, reason=reason)

    # ------------------------------------------------------------------
    # Cooldown helpers
    # ------------------------------------------------------------------

    def is_in_cooldown(self, key: str) -> bool:
        """Return True if the given key is still within its cooldown period."""
        expiry = self._cooldowns.get(key)
        if expiry is None:
            return False
        return expiry > datetime.datetime.utcnow()

    def start_cooldown(self, key: str, minutes: float) -> None:
        """Start a cooldown timer for ``key``."""
        self._cooldowns[key] = datetime.datetime.utcnow() + datetime.timedelta(minutes=minutes)

    # ------------------------------------------------------------------
    # Active alert tracking
    # ------------------------------------------------------------------

    def add_active_alert(self, alert: ActiveAlert, message_id: int | None) -> None:
        """Record or update an active alert entry."""
        now = datetime.datetime.utcnow()
        existing = self.active_alerts.get(alert.alert.suppression_key)
        if existing is None:
            self.active_alerts[alert.alert.suppression_key] = ActiveAlert(
                alert=alert.alert,
                first_seen=now,
                last_notified=now,
                notification_count=1,
                discord_message_id=message_id,
            )
        else:
            self.active_alerts[alert.alert.suppression_key] = ActiveAlert(
                alert=alert.alert,
                first_seen=existing.first_seen,
                last_notified=now,
                notification_count=existing.notification_count + 1,
                discord_message_id=message_id,
            )

