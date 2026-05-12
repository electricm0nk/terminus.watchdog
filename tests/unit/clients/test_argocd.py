"""Unit tests for ArgoCDClient — Story 2.1 (RED phase)."""
from __future__ import annotations

import pytest
import httpx

from watchdog.clients.argocd import ArgoCDClient, ArgoCDAuthError, ArgoCDTimeoutError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(transport: httpx.MockTransport) -> ArgoCDClient:
    """Construct a client with a fixed base URL and injected mock transport."""
    return ArgoCDClient(
        base_url="https://argocd.test",
        token="test-token",
        timeout=5.0,
        transport=transport,
    )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_applications_returns_list() -> None:
    """list_applications() must return a list of dicts from the items key."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/applications"
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json={"items": [{"metadata": {"name": "app-a"}}, {"metadata": {"name": "app-b"}}]})

    client = _make_client(httpx.MockTransport(handler))
    result = await client.list_applications()
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["metadata"]["name"] == "app-a"


@pytest.mark.asyncio
async def test_get_application_returns_dict() -> None:
    """get_application(name) must return the application dict."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/applications/my-app"
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json={"metadata": {"name": "my-app"}, "status": {"sync": {"status": "OutOfSync"}}})

    client = _make_client(httpx.MockTransport(handler))
    result = await client.get_application("my-app")
    assert isinstance(result, dict)
    assert result["metadata"]["name"] == "my-app"
    assert result["status"]["sync"]["status"] == "OutOfSync"


@pytest.mark.asyncio
async def test_http_401_raises_argocd_auth_error() -> None:
    """A 401 response must raise ArgoCDAuthError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthorized"})

    client = _make_client(httpx.MockTransport(handler))
    with pytest.raises(ArgoCDAuthError):
        await client.list_applications()


@pytest.mark.asyncio
async def test_http_403_raises_argocd_auth_error() -> None:
    """A 403 response must also raise ArgoCDAuthError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Forbidden"})

    client = _make_client(httpx.MockTransport(handler))
    with pytest.raises(ArgoCDAuthError):
        await client.get_application("some-app")


@pytest.mark.asyncio
async def test_timeout_raises_argocd_timeout_error() -> None:
    """A network timeout must raise ArgoCDTimeoutError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    client = _make_client(httpx.MockTransport(handler))
    with pytest.raises(ArgoCDTimeoutError):
        await client.list_applications()


@pytest.mark.asyncio
async def test_token_not_in_list_url() -> None:
    """The ARGOCD_TOKEN must never appear in the request URL."""

    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, json={"items": []})

    client = _make_client(httpx.MockTransport(handler))
    await client.list_applications()
    for url in seen_urls:
        assert "test-token" not in url
