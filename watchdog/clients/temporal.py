"""Temporal gRPC client for querying workflow state."""
from __future__ import annotations

import logging

from temporalio.client import Client, WorkflowExecution
from temporalio.service import TLSConfig

logger = logging.getLogger(__name__)

_RUNNING_QUERY = "ExecutionStatus='Running'"


class TemporalConnectError(Exception):
    """Raised when connecting to the Temporal server fails."""


class TemporalTimeoutError(Exception):
    """Raised when a Temporal API call exceeds the timeout."""


class TemporalClient:
    """Client for querying Temporal workflow state via gRPC."""

    def __init__(
        self,
        host: str,
        namespace: str,
        cert_pem: str = "",
        key_pem: str = "",
    ) -> None:
        self._host = host
        self._namespace = namespace
        self._cert_pem = cert_pem
        self._key_pem = key_pem
        self._client: Client | None = None

    async def connect(self) -> None:
        """Open the gRPC connection to the Temporal server.

        Uses mTLS when cert_pem and key_pem are both provided.
        TEMPORAL_CERT_PEM and TEMPORAL_KEY_PEM values are never logged.
        """
        tls: TLSConfig | bool = False
        if self._cert_pem and self._key_pem:
            tls = TLSConfig(
                client_cert=self._cert_pem.encode(),
                client_private_key=self._key_pem.encode(),
            )
        try:
            self._client = await Client.connect(
                self._host,
                namespace=self._namespace,
                tls=tls,
            )
        except Exception as exc:
            raise TemporalConnectError(f"Failed to connect to Temporal at {self._host}: {exc}") from exc

    async def list_running_workflows(self) -> list[WorkflowExecution]:
        """Return all currently-running workflows in the configured namespace.

        Raises:
            TemporalConnectError: if connect() was not called or failed.
            TemporalTimeoutError: if the listing call times out.
        """
        if self._client is None:
            raise TemporalConnectError("Temporal client is not connected — call connect() first")

        results: list[WorkflowExecution] = []
        try:
            async for wf in self._client.list_workflows(query=_RUNNING_QUERY):
                results.append(wf)
        except TimeoutError as exc:
            raise TemporalTimeoutError("Timed out listing Temporal workflows") from exc
        return results

    async def aclose(self) -> None:
        """Release client resources (no-op for temporalio)."""
        self._client = None
