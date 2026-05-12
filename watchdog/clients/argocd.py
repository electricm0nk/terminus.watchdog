"""ArgoCD REST client — implemented in Story 2.1."""
from __future__ import annotations

from typing import Any

import httpx


class ArgoCDAuthError(Exception):
    """Raised when the ArgoCD API returns HTTP 401 or 403."""


class ArgoCDTimeoutError(Exception):
    """Raised when the ArgoCD API call exceeds the configured timeout."""


class ArgoCDClient:
    """Async HTTP client for the ArgoCD REST API.

    The token is set in the Authorization header only — it is never logged
    or embedded in request URLs.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {
            "base_url": base_url,
            "headers": {"Authorization": f"Bearer {token}"},
            "timeout": timeout,
            "verify": False,  # cluster-internal; Vault PKI self-signed
        }
        if transport is not None:
            kwargs["transport"] = transport
        self._client: httpx.AsyncClient = httpx.AsyncClient(**kwargs)

    async def list_applications(self) -> list[dict[str, Any]]:
        """Return all ArgoCD applications as raw dicts."""
        try:
            resp = await self._client.get("/api/v1/applications")
        except httpx.TimeoutException as exc:
            raise ArgoCDTimeoutError(str(exc)) from exc
        if resp.status_code in (401, 403):
            raise ArgoCDAuthError(f"HTTP {resp.status_code} from ArgoCD")
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return list(data.get("items") or [])

    async def get_application(self, name: str) -> dict[str, Any]:
        """Return a single ArgoCD application by name."""
        try:
            resp = await self._client.get(f"/api/v1/applications/{name}")
        except httpx.TimeoutException as exc:
            raise ArgoCDTimeoutError(str(exc)) from exc
        if resp.status_code in (401, 403):
            raise ArgoCDAuthError(f"HTTP {resp.status_code} from ArgoCD")
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

