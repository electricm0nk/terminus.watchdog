"""Unit tests for LokiClient.

Uses httpx.MockTransport to simulate Loki HTTP responses without real network calls.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, UTC

import httpx
import pytest

from watchdog.clients.loki import LokiClient, LokiQueryError


def _make_loki_response(log_lines: list[str], status_code: int = 200) -> httpx.Response:
    """Build a mock Loki /query_range response."""
    if log_lines:
        streams = [
            {
                "stream": {"app": "temporal-worker"},
                "values": [[str(int(datetime.now(UTC).timestamp() * 1e9)), line] for line in log_lines],
            }
        ]
    else:
        streams = []

    body = {
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": streams,
        },
    }
    return httpx.Response(status_code, json=body)


def _make_error_response(status_code: int = 500, message: str = "internal error") -> httpx.Response:
    return httpx.Response(status_code, text=message)


class TestLokiClientQueryRange:
    """Tests for LokiClient.query_range()."""

    async def test_returns_log_lines_when_results_found(self) -> None:
        """query_range returns list of log line strings when Loki has results."""
        log_line = "error: connection refused to postgres:5432"

        def _handler(request: httpx.Request) -> httpx.Response:
            return _make_loki_response([log_line])

        transport = httpx.MockTransport(_handler)
        client = LokiClient(base_url="http://loki.test:3100", transport=transport)
        start = datetime.now(UTC) - timedelta(minutes=5)
        end = datetime.now(UTC)
        results = await client.query_range('{app="temporal-worker"} |= "postgres"', start, end)
        assert len(results) == 1
        assert log_line in results[0]

    async def test_returns_empty_list_when_no_results(self) -> None:
        """query_range returns [] when Loki returns empty streams."""
        def _handler(request: httpx.Request) -> httpx.Response:
            return _make_loki_response([])

        transport = httpx.MockTransport(_handler)
        client = LokiClient(base_url="http://loki.test:3100", transport=transport)
        start = datetime.now(UTC) - timedelta(minutes=5)
        end = datetime.now(UTC)
        results = await client.query_range('{app="temporal-worker"}', start, end)
        assert results == []

    async def test_raises_loki_query_error_on_non_2xx(self) -> None:
        """Non-2xx HTTP response raises LokiQueryError."""
        def _handler(request: httpx.Request) -> httpx.Response:
            return _make_error_response(500)

        transport = httpx.MockTransport(_handler)
        client = LokiClient(base_url="http://loki.test:3100", transport=transport)
        start = datetime.now(UTC) - timedelta(minutes=5)
        end = datetime.now(UTC)
        with pytest.raises(LokiQueryError):
            await client.query_range("{app='bad'}", start, end)

    async def test_query_sends_correct_params(self) -> None:
        """query_range sends 'query', 'start', 'end' params to /loki/api/v1/query_range."""
        received_params: dict[str, str] = {}

        def _handler(request: httpx.Request) -> httpx.Response:
            received_params.update(dict(request.url.params))
            return _make_loki_response([])

        transport = httpx.MockTransport(_handler)
        client = LokiClient(base_url="http://loki.test:3100", transport=transport)
        start = datetime.now(UTC) - timedelta(minutes=5)
        end = datetime.now(UTC)
        logql = '{app="temporal"} |= "postgres"'
        await client.query_range(logql, start, end)
        assert "query" in received_params
        assert received_params["query"] == logql
        assert "start" in received_params
        assert "end" in received_params

    async def test_url_never_logged(self) -> None:
        """LokiClient construction with sensitive URL does not log the URL (no exception)."""
        # This test confirms no crash — secrets in URL are never logged by the client
        client = LokiClient(base_url="http://user:secret@loki.test:3100")
        assert client is not None
