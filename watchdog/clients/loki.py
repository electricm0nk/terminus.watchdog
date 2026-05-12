"""Loki HTTP client for querying log streams."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_QUERY_PATH = "/loki/api/v1/query_range"


class LokiQueryError(Exception):
    """Raised when a Loki query returns a non-2xx HTTP response."""


class LokiClient:
    """HTTP client for the Loki log aggregation API.

    The base_url may contain credentials — it is never logged.
    """

    def __init__(
        self,
        base_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._transport = transport

    async def query_range(
        self,
        logql: str,
        start: datetime,
        end: datetime,
        limit: int = 100,
    ) -> list[str]:
        """Execute a LogQL range query and return matching log line strings.

        Args:
            logql: LogQL query string.
            start: Query window start (UTC).
            end: Query window end (UTC).
            limit: Maximum number of log lines to return.

        Returns:
            List of log line strings from all matching streams.

        Raises:
            LokiQueryError: on non-2xx HTTP response.
        """
        params = {
            "query": logql,
            "start": _to_nanoseconds(start),
            "end": _to_nanoseconds(end),
            "limit": str(limit),
        }
        async with httpx.AsyncClient(base_url=self._base_url, transport=self._transport) as http:
            response = await http.get(_QUERY_PATH, params=params)

        if response.status_code < 200 or response.status_code >= 300:
            raise LokiQueryError(
                f"Loki query failed with HTTP {response.status_code}"
            )

        return _extract_lines(response.json())


def _to_nanoseconds(dt: datetime) -> str:
    """Convert a datetime to a nanosecond epoch string (Loki time format)."""
    epoch_ns = int(dt.timestamp() * 1_000_000_000)
    return str(epoch_ns)


def _extract_lines(body: dict[str, Any]) -> list[str]:
    """Extract log line strings from a Loki query_range response body."""
    lines: list[str] = []
    try:
        for stream in body["data"]["result"]:
            for _ts, line in stream["values"]:
                lines.append(line)
    except (KeyError, TypeError, ValueError):
        logger.warning("Unexpected Loki response structure; could not extract log lines")
    return lines
