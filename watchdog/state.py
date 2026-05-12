"""WatchdogState — shared mutable state protected by a single asyncio.Lock."""

from __future__ import annotations

import asyncio

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
