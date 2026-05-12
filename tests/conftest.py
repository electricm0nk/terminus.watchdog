"""Shared fixtures for Terminus Watchdog test suite — Story 1.5."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from watchdog.clients.argocd import ArgoCDClient
from watchdog.clients.temporal import TemporalClient
from watchdog.state import WatchdogState


@pytest.fixture
def watchdog_state() -> WatchdogState:
    return WatchdogState()


@pytest.fixture
def mock_argocd_client() -> MagicMock:
    return MagicMock(spec=ArgoCDClient)


@pytest.fixture
def mock_temporal_client() -> MagicMock:
    return MagicMock(spec=TemporalClient)


@pytest.fixture
def mock_k8s_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_loki_client() -> MagicMock:
    return MagicMock()
