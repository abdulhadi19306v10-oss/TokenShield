"""Benchmark Scenarios 4 to 6: Circular Reasoning Repetition."""

import pytest
from tests.mock_upstream import MockUpstreamClient
from tokenshield.proxy.handler import ProxyHandler
from tokenshield.telemetry.database import TelemetryDatabase
from tokenshield.telemetry.models import SessionStatus


@pytest.mark.asyncio
async def test_scenario_4_repetitive_thought_chain(temp_db: TelemetryDatabase):
    """Scenario 4: Agent trapped in repetitive chain-of-thought phrases."""
    loop_chunks = [
        "Let me think carefully about the plan. I need to verify step 1 before proceeding.\n",
        "Let me think again. I must check step 1 once more.\n",
        "Thinking about step 1 again. I will verify step 1 now.\n",
    ] * 8

    mock_client = MockUpstreamClient(stream_chunks=loop_chunks)
    handler = ProxyHandler(db=temp_db, upstream_client=mock_client)

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Analyze the optimization plan"}],
        "stream": True,
    }

    tokens_received = 0
    tripped = False
    sid = "bench-scenario-4"

    async for chunk in handler.stream_chat_completion(payload, session_id=sid):
        if "data:" in chunk and "[DONE]" not in chunk:
            tokens_received += 1
            if "Runaway loop halted" in chunk:
                tripped = True

    session = await temp_db.get_session(sid)
    assert tripped is True
    assert session is not None
    assert session.status == SessionStatus.TRIPPED
    assert session.tokens_saved >= 2500
    assert tokens_received < 45


@pytest.mark.asyncio
async def test_scenario_5_paraphrased_loop(temp_db: TelemetryDatabase):
    """Scenario 5: Circular reasoning loop with slight paraphrasing."""
    loop_chunks = [
        "The optimal solution might be approach Alpha because of speed.\n",
        "However approach Alpha has high performance benefits.\n",
        "Therefore approach Alpha is the fastest and optimal method.\n",
        "We could also choose approach Alpha for better speed.\n",
        "Approach Alpha provides top speed and is the best solution.\n",
    ] * 6

    mock_client = MockUpstreamClient(stream_chunks=loop_chunks)
    handler = ProxyHandler(db=temp_db, upstream_client=mock_client)

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Compare algorithm Alpha vs Beta"}],
        "stream": True,
    }

    tokens_received = 0
    tripped = False
    sid = "bench-scenario-5"

    async for chunk in handler.stream_chat_completion(payload, session_id=sid):
        if "data:" in chunk and "[DONE]" not in chunk:
            tokens_received += 1
            if "Runaway loop halted" in chunk:
                tripped = True

    session = await temp_db.get_session(sid)
    assert tripped is True
    assert session is not None
    assert session.status == SessionStatus.TRIPPED
    assert session.tokens_saved >= 2500
    assert tokens_received < 45


@pytest.mark.asyncio
async def test_scenario_6_repeating_markdown_bullets(temp_db: TelemetryDatabase):
    """Scenario 6: Model stuck generating endless repetitive markdown bullet items."""
    loop_chunks = [
        "* Item check: verified configuration parameter.\n",
        "* Item check: verified configuration parameter.\n",
    ] * 15

    mock_client = MockUpstreamClient(stream_chunks=loop_chunks)
    handler = ProxyHandler(db=temp_db, upstream_client=mock_client)

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "List all verified checklist items"}],
        "stream": True,
    }

    tokens_received = 0
    tripped = False
    sid = "bench-scenario-6"

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
