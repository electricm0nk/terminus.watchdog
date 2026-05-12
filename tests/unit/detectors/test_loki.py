"""Unit tests for TemporalPostgresConnectivityDetector.

Tests verify detection logic with mocked LokiClient.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from watchdog.detectors.loki import TemporalPostgresConnectivityDetector


def _make_loki_client(return_lines: list[str] | None = None, raises: Exception | None = None) -> AsyncMock:
    mock = AsyncMock()
    if raises is not None:
        mock.query_range = AsyncMock(side_effect=raises)
    else:
        mock.query_range = AsyncMock(return_value=return_lines or [])
    return mock


class TestTemporalPostgresConnectivityDetector:
    """Tests for TemporalPostgresConnectivityDetector.detect()."""

    async def test_disabled_when_loki_url_empty(self) -> None:
        """Returns [] and no exception when loki_url is empty (detector disabled)."""
        detector = TemporalPostgresConnectivityDetector(loki_client=None, loki_url="")
        alerts = await detector.detect()
        assert alerts == []

    async def test_alert_when_log_lines_found(self) -> None:
        """Returns temporal-postgres-connectivity High alert when Loki returns error lines."""
        mock_client = _make_loki_client(return_lines=["error: connection refused postgres:5432"])
        detector = TemporalPostgresConnectivityDetector(loki_client=mock_client, loki_url="http://loki.test")
        alerts = await detector.detect()
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.pattern == "temporal-postgres-connectivity"
        assert alert.severity == "high"

    async def test_no_alert_when_no_log_lines(self) -> None:
        """Returns [] when Loki returns no matching log lines."""
        mock_client = _make_loki_client(return_lines=[])
        detector = TemporalPostgresConnectivityDetector(loki_client=mock_client, loki_url="http://loki.test")
        alerts = await detector.detect()
        assert alerts == []

    async def test_no_crash_on_loki_query_error(self) -> None:
        """LokiQueryError is caught; returns [] without re-raising."""
        from watchdog.clients.loki import LokiQueryError

        mock_client = _make_loki_client(raises=LokiQueryError("unreachable"))
        detector = TemporalPostgresConnectivityDetector(loki_client=mock_client, loki_url="http://loki.test")
        alerts = await detector.detect()
        assert alerts == []

    async def test_alert_resource_fields(self) -> None:
        """Alert resource_namespace and resource_name are set correctly."""
        mock_client = _make_loki_client(return_lines=["error: connection refused"])
        detector = TemporalPostgresConnectivityDetector(loki_client=mock_client, loki_url="http://loki.test")
        alerts = await detector.detect()
        alert = alerts[0]
        assert alert.resource_namespace == "temporal"
        assert alert.resource_name == "temporal-worker"
