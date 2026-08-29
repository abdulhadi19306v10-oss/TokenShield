"""Complex Real-World Benchmarks & Challenging False-Positive Edge Cases."""

import pytest
from tests.mock_upstream import MockUpstreamClient
from tokenshield.proxy.handler import ProxyHandler
from tokenshield.telemetry.database import TelemetryDatabase
from tokenshield.telemetry.models import SessionStatus


# ==============================================================================
# 3 COMPLEX RUNAWAY REAL-WORLD BENCHMARKS
# ==============================================================================

@pytest.mark.asyncio
async def test_complex_scenario_11_ping_pong_tool_oscillation(temp_db: TelemetryDatabase):
    """Scenario 11: Ping-Pong Tool Oscillation Loop (Tool A <-> Tool B).
    
    Real-world pattern: Agent alternates between 'format_code' and 'run_linter',
    where fixing formatting causes a lint error, and fixing linting breaks formatting.
    """
    oscillating_stream_chunks = [
        "Running tool format_code to fix indentation.\n",
        "Tool format_code returned 0 errors. Now running run_linter.\n",
        "Linter reported line length violation. Running format_code again.\n",
        "Tool format_code returned 0 errors. Now running run_linter.\n",
        "Linter reported line length violation. Running format_code again.\n",
        "Tool format_code returned 0 errors. Now running run_linter.\n",
    ] * 5

    mock_client = MockUpstreamClient(stream_chunks=oscillating_stream_chunks)
    handler = ProxyHandler(db=temp_db, upstream_client=mock_client)

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": "Fix code formatting and pass linter checks"},
            {"role": "tool", "content": '{"linter_status": "failed", "error": "E501 line too long"}', "tool_call_id": "c1"},
        ],
        "stream": True,
    }

    sid = "bench-scenario-11-ping-pong"
    tripped = False
    tokens_received = 0

    async for chunk in handler.stream_chat_completion(payload, session_id=sid):
        if "data:" in chunk and "[DONE]" not in chunk:
            tokens_received += 1
            if "Runaway loop halted" in chunk:
                tripped = True

    assert tripped is True
    session = await temp_db.get_session(sid)
    assert session is not None
    assert session.status == SessionStatus.TRIPPED
    assert session.tokens_saved >= 3000
    assert tokens_received < 30


@pytest.mark.asyncio
async def test_complex_scenario_12_mutating_parameter_exhaustion_loop(temp_db: TelemetryDatabase):
    """Scenario 12: Mutating Parameter Exhaustion Loop (Brute-force query pagination).
    
    Real-world pattern: Agent queries an API with slightly mutating offsets (offset=0, 10, 20...),
    all returning empty results, generating repetitive reasoning phrases.
    """
    mutating_chunks = [
        "Query at offset 0 returned 0 records. Trying offset 10 now.\n",
        "Query at offset 10 returned 0 records. Trying offset 20 now.\n",
        "Query at offset 20 returned 0 records. Trying offset 30 now.\n",
        "Query at offset 30 returned 0 records. Trying offset 40 now.\n",
        "Query at offset 40 returned 0 records. Trying offset 50 now.\n",
    ] * 6

    mock_client = MockUpstreamClient(stream_chunks=mutating_chunks)
    handler = ProxyHandler(db=temp_db, upstream_client=mock_client)

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "user", "content": "Search pagination records until found"},
        ],
        "stream": True,
    }

    sid = "bench-scenario-12-pagination-exhaustion"
    tripped = False
    tokens_received = 0

    async for chunk in handler.stream_chat_completion(payload, session_id=sid):
        if "data:" in chunk and "[DONE]" not in chunk:
            tokens_received += 1
            if "Runaway loop halted" in chunk:
                tripped = True

    assert tripped is True
    session = await temp_db.get_session(sid)
    assert session is not None
    assert session.status == SessionStatus.TRIPPED
    assert session.tokens_saved >= 3000
    assert tokens_received < 30


@pytest.mark.asyncio
async def test_complex_scenario_13_meta_reflection_stall_loop(temp_db: TelemetryDatabase):
    """Scenario 13: Meta-Reasoning & Self-Critique Stall Loop.
    
    Real-world pattern: Deep thinking model gets trapped in self-doubt recursion:
    'Wait, is my critique correct? Let me re-evaluate my reasoning...'.
    """
    stall_chunks = [
        "Wait, is my initial evaluation correct? Let me re-evaluate my critique.\n",
        "Looking at my critique again, I should reconsider my previous thought.\n",
        "Wait, is my initial evaluation correct? Let me re-evaluate my critique.\n",
        "Looking at my critique again, I should reconsider my previous thought.\n",
    ] * 8

    mock_client = MockUpstreamClient(stream_chunks=stall_chunks)
    handler = ProxyHandler(db=temp_db, upstream_client=mock_client)

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Deeply verify your solution logic"}],
        "stream": True,
    }

    sid = "bench-scenario-13-reflection-stall"
    tripped = False
    tokens_received = 0

    async for chunk in handler.stream_chat_completion(payload, session_id=sid):
        if "data:" in chunk and "[DONE]" not in chunk:
            tokens_received += 1
            if "Runaway loop halted" in chunk:
                tripped = True

    assert tripped is True
    session = await temp_db.get_session(sid)
    assert session is not None
    assert session.status == SessionStatus.TRIPPED
    assert session.tokens_saved >= 2500
    assert tokens_received < 25


# ==============================================================================
# 3 CHALLENGING REAL-WORLD FALSE POSITIVE CASES (MUST PASS WITH 0% FALSE POSITIVES)
# ==============================================================================

@pytest.mark.asyncio
async def test_false_positive_challenge_1_repetitive_test_suite_generation(temp_db: TelemetryDatabase):
    """False Positive Challenge 1: Repetitive Pytest Test Suite Generation.
    
    Real-world pattern: Prompt asks to write 10 unit tests with identical assertion syntax.
    Must NOT trip the circuit breaker.
    """
    code_test_chunks = [
        "Here are the comprehensive pytest edge cases for calculate_tax:\n\n",
        "```python\n",
        "import pytest\n",
        "from tax import calculate_tax\n\n",
        "def test_zero_income():\n",
        "    assert calculate_tax(0, 'CA') == 0.0\n\n",
        "def test_low_bracket():\n",
        "    assert calculate_tax(10000, 'CA') == 1000.0\n\n",
        "def test_middle_bracket():\n",
        "    assert calculate_tax(50000, 'CA') == 7500.0\n\n",
        "def test_high_bracket():\n",
        "    assert calculate_tax(200000, 'CA') == 45000.0\n\n",
        "def test_ny_bracket():\n",
        "    assert calculate_tax(10000, 'NY') == 900.0\n\n",
        "def test_tx_zero_bracket():\n",
        "    assert calculate_tax(50000, 'TX') == 0.0\n\n",
        "```\n",
        "All test fixtures verify edge conditions across state tax boundaries.\n",
    ]

    mock_client = MockUpstreamClient(stream_chunks=code_test_chunks)
    handler = ProxyHandler(db=temp_db, upstream_client=mock_client)

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Write 6 unit tests with assert calculate_tax"}],
        "stream": True,
    }

    sid = "fp-challenge-1-unit-tests"
    tripped = False
    chunks_received = 0

    async for chunk in handler.stream_chat_completion(payload, session_id=sid):
        if "data:" in chunk and "[DONE]" not in chunk:
            chunks_received += 1
            if "Runaway loop halted" in chunk:
                tripped = True

    # 0% False Positive Verification
    assert tripped is False, "Repetitive code unit tests must not trip TokenShield!"
    assert chunks_received >= len(code_test_chunks)
    session = await temp_db.get_session(sid)
    assert session.status == SessionStatus.COMPLETED


@pytest.mark.asyncio
async def test_false_positive_challenge_2_legal_contract_boilerplate_anaphora(temp_db: TelemetryDatabase):
    """False Positive Challenge 2: Legal Contract Boilerplate with Repetitive Clause Openings.
    
    Real-world pattern: NDA or Contract where every clause starts with identical legal phrasing:
    'Section X: The Receiving Party covenants and agrees that...'.
    Must NOT trip the circuit breaker.
    """
    legal_nda_chunks = [
        "# CONFIDENTIALITY AND NON-DISCLOSURE AGREEMENT\n\n",
        "Section 1: The Receiving Party covenants and agrees that it shall not disclose proprietary source code.\n\n",
        "Section 2: The Receiving Party covenants and agrees that customer transaction histories remain strictly private.\n\n",
        "Section 3: The Receiving Party covenants and agrees that internal pricing algorithms are confidential trade secrets.\n\n",
        "Section 4: The Receiving Party covenants and agrees that employee compensation details shall be kept confidential.\n\n",
        "Section 5: The Receiving Party covenants and agrees that unreleased patent disclosures shall not be published.\n\n",
        "In witness whereof, the parties have executed this agreement as of the effective date.\n",
    ]

    mock_client = MockUpstreamClient(stream_chunks=legal_nda_chunks)
    handler = ProxyHandler(db=temp_db, upstream_client=mock_client)

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Draft a 5-clause NDA with standard covenant clauses"}],
        "stream": True,
    }

    sid = "fp-challenge-2-legal-nda"
    tripped = False
    chunks_received = 0

    async for chunk in handler.stream_chat_completion(payload, session_id=sid):
        if "data:" in chunk and "[DONE]" not in chunk:
            chunks_received += 1
            if "Runaway loop halted" in chunk:
                tripped = True

    # 0% False Positive Verification
    assert tripped is False, "Legal contract clause boilerplate must not trip TokenShield!"
    assert chunks_received >= len(legal_nda_chunks)
    session = await temp_db.get_session(sid)
    assert session.status == SessionStatus.COMPLETED


@pytest.mark.asyncio
async def test_false_positive_challenge_3_breadth_first_search_simulation_trace(temp_db: TelemetryDatabase):
    """False Positive Challenge 3: Step-by-Step Algorithm State Machine Trace.
    
    Real-world pattern: Prompt explicitly commands a strict repeated output template:
    'Queue state: [...], Current node: X, Visited set: {...}'.
    Must NOT trip the circuit breaker.
    """
    algorithm_trace_chunks = [
        "Starting BFS Traversal from Root Node A on directed graph:\n\n",
        "Step 1: Queue state: ['A'], Current node: A, Visited set: {'A'}, Exploring neighbors: ['B', 'C']\n",
        "Step 2: Queue state: ['B', 'C'], Current node: B, Visited set: {'A', 'B'}, Exploring neighbors: ['D']\n",
        "Step 3: Queue state: ['C', 'D'], Current node: C, Visited set: {'A', 'B', 'C'}, Exploring neighbors: ['E', 'F']\n",
        "Step 4: Queue state: ['D', 'E', 'F'], Current node: D, Visited set: {'A', 'B', 'C', 'D'}, Exploring neighbors: []\n",
        "Step 5: Queue state: ['E', 'F'], Current node: E, Visited set: {'A', 'B', 'C', 'D', 'E'}, Exploring neighbors: []\n",
        "Step 6: Queue state: ['F'], Current node: F, Visited set: {'A', 'B', 'C', 'D', 'E', 'F'}, Exploring neighbors: []\n\n",
        "Queue is now empty. The final BFS traversal order is [A, B, C, D, E, F].\n",
    ]

    mock_client = MockUpstreamClient(stream_chunks=algorithm_trace_chunks)
    handler = ProxyHandler(db=temp_db, upstream_client=mock_client)

    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Trace BFS step-by-step with Queue state and Visited set"}],
        "stream": True,
    }

    sid = "fp-challenge-3-bfs-trace"
    tripped = False
    chunks_received = 0

    async for chunk in handler.stream_chat_completion(payload, session_id=sid):
        if "data:" in chunk and "[DONE]" not in chunk:
            chunks_received += 1
            if "Runaway loop halted" in chunk:
                tripped = True

    # 0% False Positive Verification
    assert tripped is False, "Algorithm state machine trace must not trip TokenShield!"
    assert chunks_received >= len(algorithm_trace_chunks)
    session = await temp_db.get_session(sid)
    assert session.status == SessionStatus.COMPLETED
