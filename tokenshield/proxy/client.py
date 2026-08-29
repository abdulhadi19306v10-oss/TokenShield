"""Asynchronous HTTP client interface communicating with upstream LLM APIs."""

from typing import Any, AsyncGenerator, Dict, Optional
import httpx

from tokenshield.config import get_config


class UpstreamClient:
    """Handles upstream HTTP requests and Server-Sent Events (SSE) streaming connections."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 60.0,
    ):
        config = get_config()
        self.base_url = (base_url or config.UPSTREAM_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else config.UPSTREAM_API_KEY
        self.timeout = timeout

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def stream_chat(
        self,
        payload: Dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        """Stream SSE chunks directly from the upstream provider."""
        endpoint = f"{self.base_url}/chat/completions"
        request_body = dict(payload)
        request_body["stream"] = True

        # ponytail: async client context ensures prompt socket disposal
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                endpoint,
                json=request_body,
                headers=self._get_headers(),
            ) as response:
                if response.status_code >= 400:
                    error_text = await response.aread()
                    raise httpx.HTTPStatusError(
                        f"Upstream provider returned HTTP {response.status_code}: {error_text.decode('utf-8', errors='replace')}",
                        request=response.request,
                        response=response,
                    )

                async for chunk in response.aiter_text():
                    if chunk:
                        yield chunk

    async def sync_chat(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Send non-streaming request to upstream provider."""
        endpoint = f"{self.base_url}/chat/completions"
        request_body = dict(payload)
        request_body["stream"] = False

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                endpoint,
                json=request_body,
                headers=self._get_headers(),
            )
            response.raise_for_status()
            return response.json()
