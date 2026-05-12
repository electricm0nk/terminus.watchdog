"""Unit tests for TemporalClient.

Tests use mocked temporalio.client.Client to avoid real gRPC connections.
"""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from watchdog.clients.temporal import TemporalClient, TemporalConnectError, TemporalTimeoutError


async def _async_gen(items: list[object]):  # type: ignore[type-arg]
    """Helper to create an async iterator from a list, for mocking list_workflows."""
    for item in items:
        yield item


def _make_mock_workflow(
    workflow_id: str = "wf-123",
    run_id: str = "run-123",
    task_queue: str = "test-queue",
    start_time: datetime.datetime | None = None,
) -> MagicMock:
    """Create a mock WorkflowExecution with the fields used by detectors."""
    from temporalio.client import WorkflowExecutionStatus

    mock_wf = MagicMock()
    mock_wf.id = workflow_id
    mock_wf.run_id = run_id
    mock_wf.task_queue = task_queue
    mock_wf.status = WorkflowExecutionStatus.RUNNING
    mock_wf.start_time = start_time or datetime.datetime.now(datetime.UTC)
    mock_wf.history_length = 10
    return mock_wf


class TestTemporalClientConnect:
    """Tests for TemporalClient.connect() method."""

    async def test_connect_without_tls(self) -> None:
        """Connect with no cert/key — TLS disabled."""
        with patch("watchdog.clients.temporal.Client") as mock_client_cls:
            mock_client_cls.connect = AsyncMock(return_value=MagicMock())
            client = TemporalClient(host="temporal.internal:7233", namespace="default")
            await client.connect()
            mock_client_cls.connect.assert_called_once()
            call_kwargs = mock_client_cls.connect.call_args.kwargs
            assert call_kwargs.get("tls") is False or call_kwargs.get("tls") is None or call_kwargs.get("tls") == False  # noqa: E712

    async def test_connect_with_tls(self) -> None:
        """Connect with cert/key — TLS config created."""
        with patch("watchdog.clients.temporal.Client") as mock_client_cls:
            mock_client_cls.connect = AsyncMock(return_value=MagicMock())
            client = TemporalClient(
                host="temporal.internal:7233",
                namespace="default",
                cert_pem="CERT",
                key_pem="KEY",
            )
            await client.connect()
            mock_client_cls.connect.assert_called_once()

    async def test_connect_failure_raises_temporal_connect_error(self) -> None:
        """SDK connect exception is wrapped in TemporalConnectError."""
        with patch("watchdog.clients.temporal.Client") as mock_client_cls:
            mock_client_cls.connect = AsyncMock(side_effect=RuntimeError("connection refused"))
            client = TemporalClient(host="temporal.internal:7233", namespace="default")
            with pytest.raises(TemporalConnectError):
                await client.connect()

    async def test_list_running_workflows_before_connect_raises(self) -> None:
        """Calling list_running_workflows before connect raises TemporalConnectError."""
        client = TemporalClient(host="temporal.internal:7233", namespace="default")
        with pytest.raises(TemporalConnectError):
            await client.list_running_workflows()


class TestTemporalClientListWorkflows:
    """Tests for TemporalClient.list_running_workflows()."""

    async def _connected_client(self, mock_workflows: list[MagicMock]) -> TemporalClient:
        """Return a TemporalClient that is 'connected' with a mocked internal client."""
        client = TemporalClient(host="temporal.internal:7233", namespace="default")
        mock_inner = MagicMock()
        mock_inner.list_workflows = MagicMock(return_value=_async_gen(mock_workflows))
        client._client = mock_inner  # type: ignore[attr-defined]
        return client

    async def test_list_returns_empty_when_no_workflows(self) -> None:
        """Returns empty list when no running workflows."""
        client = await self._connected_client([])
        result = await client.list_running_workflows()
        assert result == []

    async def test_list_returns_workflow_objects(self) -> None:
        """Returns all workflows provided by the async iterator."""
        mock_wf1 = _make_mock_workflow("wf-1")
        mock_wf2 = _make_mock_workflow("wf-2")
        client = await self._connected_client([mock_wf1, mock_wf2])
        result = await client.list_running_workflows()
        assert len(result) == 2
        assert result[0].id == "wf-1"
        assert result[1].id == "wf-2"

    async def test_list_uses_running_status_query(self) -> None:
        """list_workflows is called with a query filtering for Running workflows."""
        client = await self._connected_client([])
        await client.list_running_workflows()
        call_args = client._client.list_workflows.call_args  # type: ignore[attr-defined]
        # The query should filter for ExecutionStatus=Running
        query_str = str(call_args)
        assert "Running" in query_str

    async def test_list_timeout_raises_temporal_timeout_error(self) -> None:
        """asyncio.TimeoutError raised during iteration is wrapped in TemporalTimeoutError."""

        client = TemporalClient(host="temporal.internal:7233", namespace="default")
        mock_inner = MagicMock()

        async def _timeout_gen() -> object:
            raise TimeoutError
            yield  # pragma: no cover  # noqa: unreachable

        mock_inner.list_workflows = MagicMock(return_value=_timeout_gen())
        client._client = mock_inner  # type: ignore[attr-defined]

        with pytest.raises(TemporalTimeoutError):
            await client.list_running_workflows()
