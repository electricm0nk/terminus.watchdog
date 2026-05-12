"""[RED] Tests for watchdog.state — WatchdogState."""

from __future__ import annotations

import asyncio

import pytest

from watchdog.state import WatchdogState


class TestWatchdogState:
    def test_state_has_lock(self) -> None:
        state = WatchdogState()
        assert hasattr(state, "_lock")
        assert isinstance(state._lock, asyncio.Lock)

    def test_state_active_alerts_initially_empty(self) -> None:
        state = WatchdogState()
        assert state.active_alerts == {}

    def test_state_suppressed_initially_empty(self) -> None:
        state = WatchdogState()
        assert state.suppressed == {}

    def test_state_quiet_hours_initially_false(self) -> None:
        state = WatchdogState()
        assert state.quiet_hours_active is False

    @pytest.mark.asyncio
    async def test_lock_is_acquirable(self) -> None:
        state = WatchdogState()
        async with state._lock:
            assert state._lock.locked()
