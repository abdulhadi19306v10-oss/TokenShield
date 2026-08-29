"""Benchmark Scenarios 1 to 3: Infinite Tool Execution Loops."""

import pytest
from tests.mock_upstream import MockUpstreamClient
from tokenshield.proxy.handler import ProxyHandler
from tokenshield.telemetry.database import TelemetryDatabase
from tokenshield.telemetry.models import SessionStatus, TripReason


@pytest.mark.asyncio
async def test_scenario_1_web_scraper_403_loop(temp_db: TelemetryDatabase):
    """Scenario 1: Scraper returns 403 Forbidden; agent retries endlessly in loop."""
    # Simulated runaway stream chunks
    loop_chunks = [
        "Web scraper failed with HTTP 403 Forbidden. Retrying https://example.com/api now...\n"
    ] * 25

    mock_client = MockUpstreamClient(stream_chunks=loop_chunks)
    handler = ProxyHandler(db=temp_db, upstream_client=mock_client)

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": "Scrape data from https://example.com/api"},
            {"role": "tool", "content": '{"error": "403 Forbidden"}', "tool_call_id": "call_1"},
        ],
        "stream": True,
    }

    tokens_received = 0
    tripped = False
    sid = "bench-scenario-1"

    async for chunk in handler.stream_chat_completion(payload, session_id=sid):
        if "data:" in chunk and "[DONE]" not in chunk:
            tokens_received += 1
            if "Runaway loop halted" in chunk:
                tripped = True

    session = await temp_db.get_session(sid)
    assert tripped is True
    assert session is not None
    assert session.status == SessionStatus.TRIPPED
    assert session.tokens_saved >= 3000
    assert tokens_received < 40  # Intercepted in < 40 chunks (>95% saved vs 4000 runaway limit)


@pytest.mark.asyncio
async def test_scenario_2_sql_syntax_error_loop(temp_db: TelemetryDatabase):
    """Scenario 2: Database query syntax error; agent endlessly repeats unchanged SQL."""
    loop_chunks = [
        "SQL Error: syntax error near 'WHER'. Executing SELECT * FROM users WHER id = 10 again...\n"
    ] * 25

    mock_client = MockUpstreamClient(stream_chunks=loop_chunks)
    handler = ProxyHandler(db=temp_db, upstream_client=mock_client)

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": "Query user 10 from database"},
            {"role": "tool", "content": '{"error": "syntax error near WHER"}', "tool_call_id": "call_sql"},
        ],
        "stream": True,
    }

    tokens_received = 0
    tripped = False
    sid = "bench-scenario-2"

    async for chunk in handler.stream_chat_completion(payload, session_id=sid):
        if "data:" in chunk and "[DONE]" not in chunk:
            tokens_received += 1
            if "Runaway loop halted" in chunk:
                tripped = True

    session = await temp_db.get_session(sid)
    assert tripped is True
    assert session is not None
    assert session.status == SessionStatus.TRIPPED
    assert session.tokens_saved >= 3000
    assert tokens_received < 40


@pytest.mark.asyncio
async def test_scenario_3_file_search_empty_loop(temp_db: TelemetryDatabase):
    """Scenario 3: File search returns empty list; agent queries same path continuously."""
    loop_chunks = [
        "Search in /var/logs returned 0 files. Let me search /var/logs again to check.\n"
    ] * 25

    mock_client = MockUpstreamClient(stream_chunks=loop_chunks)
    handler = ProxyHandler(db=temp_db, upstream_client=mock_client)

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": "Find crash logs in /var/logs"},
            {"role": "tool", "content": '{"matched_files": []}', "tool_call_id": "call_find"},
        ],
        "stream": True,
    }

    tokens_received = 0
    tripped = False
    sid = "bench-scenario-3"

    async for chunk in handler.stream_chat_completion(payload, session_id=sid):
        if "data:" in chunk and "[DONE]" not in chunk:
            tokens_received += 1
            if "Runaway loop halted" in chunk:
                tripped = True

    session = await temp_db.get_session(sid)
    assert tripped is True
    assert session is not None
    assert session.status == SessionStatus.TRIPPED
    assert session.tokens_saved >= 3000
    assert tokens_received < 40
