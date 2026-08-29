"""Integration tests for FastAPI Proxy Server and end-to-end request pipelines."""

import json
import pytest
from httpx import ASGITransport, AsyncClient

from tests.mock_upstream import MockUpstreamClient
from tokenshield.proxy.handler import ProxyHandler
from tokenshield.proxy.server import create_app
from tokenshield.telemetry.database import TelemetryDatabase
from tokenshield.telemetry.models import SessionStatus, TripReason


@pytest.mark.asyncio
async def test_proxy_normal_streaming_completion(temp_db: TelemetryDatabase):
    """Verify normal streaming request passes without tripping and completes cleanly."""
    mock_client = MockUpstreamClient(mode="normal")
    handler = ProxyHandler(db=temp_db, upstream_client=mock_client)
    app = create_app(db=temp_db, handler=handler)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Explain TokenShield"}],
                "stream": True,
            },
            headers={"x-session-id": "sess-test-normal"},
        )

        assert response.status_code == 200
        text = response.text
        assert "data:" in text
        assert "[DONE]" in text
        assert "TokenShield is an intelligent middleware proxy" in text
        assert "Runaway loop halted" not in text

    # Verify database session state
    session = await temp_db.get_session("sess-test-normal")
    assert session is not None
    assert session.status == SessionStatus.COMPLETED
    assert session.total_completion_tokens > 0


@pytest.mark.asyncio
async def test_proxy_loop_interception(temp_db: TelemetryDatabase):
    """Verify proxy detects in-flight repetition loop, trips circuit, and persists savings."""
    mock_client = MockUpstreamClient(mode="verbatim_loop")
    handler = ProxyHandler(db=temp_db, upstream_client=mock_client)
    app = create_app(db=temp_db, handler=handler)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Keep thinking"}],
                "stream": True,
            },
            headers={"x-session-id": "sess-test-loop"},
        )

        assert response.status_code == 200
        text = response.text
        assert "data:" in text
        assert "[TokenShield Circuit Intercept: Runaway loop halted" in text
        assert "[DONE]" in text

    # Verify session was recorded as TRIPPED with saved tokens
    session = await temp_db.get_session("sess-test-loop")
    assert session is not None
    assert session.status == SessionStatus.TRIPPED
    assert session.tokens_saved > 0
    assert session.cost_saved_usd > 0

    # Verify trip record
    trips = await temp_db.get_all_trips()
    assert len(trips) == 1
    assert trips[0].session_id == "sess-test-loop"
    assert trips[0].estimated_tokens_saved > 0


@pytest.mark.asyncio
async def test_proxy_sync_completion(temp_db: TelemetryDatabase):
    """Verify non-streaming request execution."""
    mock_client = MockUpstreamClient(sync_response_text="Direct answer from assistant.")
    handler = ProxyHandler(db=temp_db, upstream_client=mock_client)
    app = create_app(db=temp_db, handler=handler)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "What is 2+2?"}],
                "stream": False,
            },
            headers={"x-session-id": "sess-test-sync"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["choices"][0]["message"]["content"] == "Direct answer from assistant."

    session = await temp_db.get_session("sess-test-sync")
    assert session is not None
    assert session.status == SessionStatus.COMPLETED


@pytest.mark.asyncio
async def test_health_and_models_endpoints(temp_db: TelemetryDatabase):
    """Verify health check and model listing endpoints."""
    app = create_app(db=temp_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Health check
        res_h = await ac.get("/health")
        assert res_h.status_code == 200
        assert res_h.json()["status"] == "healthy"

        # Models
        res_m = await ac.get("/v1/models")
        assert res_m.status_code == 200
        assert len(res_m.json()["data"]) >= 2


@pytest.mark.asyncio
async def test_telemetry_query_endpoints(temp_db: TelemetryDatabase):
    """Verify telemetry query endpoints for dashboard consumption."""
    app = create_app(db=temp_db)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res_metrics = await ac.get("/v1/telemetry/metrics")
        assert res_metrics.status_code == 200
        assert "total_tokens_saved" in res_metrics.json()

        res_sessions = await ac.get("/v1/telemetry/sessions")
        assert res_sessions.status_code == 200
        assert isinstance(res_sessions.json(), list)
