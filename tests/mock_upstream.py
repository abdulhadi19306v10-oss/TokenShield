"""Deterministic Mock Upstream Provider for isolated testing and benchmark simulation."""

import asyncio
import json
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional
from tokenshield.proxy.client import UpstreamClient


class MockUpstreamClient(UpstreamClient):
    """Simulates various upstream LLM behaviors: normal completions, infinite loops, and large payloads."""

    def __init__(
        self,
        mode: str = "normal",  # 'normal', 'verbatim_loop', 'circular_reasoning', 'error_loop'
        stream_chunks: Optional[List[str]] = None,
        sync_response_text: str = "Hello! I am a helpful AI assistant.",
    ):
        super().__init__(base_url="http://mock-upstream/v1", api_key="mock-key")
        self.mode = mode
        self.custom_chunks = stream_chunks
        self.sync_response_text = sync_response_text

    async def stream_chat(
        self,
        payload: Dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        """Yield deterministic SSE frames based on simulated mode."""
        model = payload.get("model", "gpt-4o-mini")

        if self.custom_chunks is not None:
            chunks = self.custom_chunks
        elif self.mode == "verbatim_loop":
            # Repetitive phrase loop
            chunks = ["Let me think about step one. "] * 30
        elif self.mode == "circular_reasoning":
            # Paraphrased circular reasoning loop
            chunks = [
                "I should inspect the database tables first.\n",
                "Let me now check the database tables once again.\n",
                "I will inspect the database tables to verify.\n",
                "Checking the database tables now.\n",
                "Let me verify the database tables again.\n",
            ] * 6
        elif self.mode == "error_loop":
            # Tool failure retry loop
            chunks = [
                "Tool returned 403 Forbidden. Retrying scraper now...\n",
                "Tool returned 403 Forbidden. Retrying scraper now...\n",
                "Tool returned 403 Forbidden. Retrying scraper now...\n",
            ] * 10
        else:
            # Normal diverse text
            chunks = [
                "TokenShield is an intelligent middleware proxy. ",
                "It inspects LLM streaming responses in real time. ",
                "This ensures runaway loops are intercepted immediately. ",
                "Furthermore, context payloads are compressed to save costs. ",
            ]

        for chunk_text in chunks:
            frame = {
                "id": f"mockcmpl-{uuid.uuid4().hex[:8]}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": chunk_text},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(frame)}\n\n"
            # Small yield pause simulating token streaming
            await asyncio.sleep(0.001)

        # End of stream
        yield "data: [DONE]\n\n"

    async def sync_chat(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Return non-streaming OpenAI chat completion structure."""
        model = payload.get("model", "gpt-4o-mini")
        return {
            "id": f"mockcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": self.sync_response_text,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 15,
                "total_tokens": 65,
            },
        }
