"""Benchmark Scenario 10: Control Case (Complex Multi-Turn Reasoning & Code Generation)."""

import pytest
from tests.mock_upstream import MockUpstreamClient
from tokenshield.proxy.handler import ProxyHandler
from tokenshield.telemetry.database import TelemetryDatabase
from tokenshield.telemetry.models import SessionStatus


@pytest.mark.asyncio
async def test_scenario_10_control_case_no_false_positives(temp_db: TelemetryDatabase):
    """Scenario 10: Complex multi-step algorithm implementation and mathematical proof.
    
    Verifies that complex, non-repeating chain-of-thought and code blocks pass
    through TokenShield with 0% false positives and reach normal completion.
    """
    valid_complex_reasoning_chunks = [
        "To solve the dynamic programming subset sum problem, we first establish the recurrence relation.\n",
        "Let DP[i][w] be true if a subset of elements from index 0 to i sums to exactly w.\n",
        "The base cases are:\n",
        "1. DP[i][0] = true for all i, since an empty subset sums to 0.\n",
        "2. DP[0][w] = (arr[0] == w) for w > 0.\n",
        "For transitions, we consider two choices for each element arr[i]:\n",
        "- Exclude arr[i]: DP[i][w] = DP[i-1][w]\n",
        "- Include arr[i]: DP[i][w] = DP[i-1][w - arr[i]] (valid if w >= arr[i])\n",
        "\nHere is the optimized Python implementation:\n",
        "```python\n",
        "def can_partition(nums: list[int], target: int) -> bool:\n",
        "    dp = [False] * (target + 1)\n",
        "    dp[0] = True\n",
        "    for num in nums:\n",
        "        for w in range(target, num - 1, -1):\n",
        "            dp[w] = dp[w] or dp[w - num]\n",
        "    return dp[target]\n",
        "```\n",
        "The time complexity is O(N * Target) and spatial complexity is O(Target).\n",
        "This completes the comprehensive mathematical proof and implementation.\n",
    ]

    mock_client = MockUpstreamClient(stream_chunks=valid_complex_reasoning_chunks)
    handler = ProxyHandler(db=temp_db, upstream_client=mock_client)

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are an expert algorithms and complexity theorist."},
            {"role": "user", "content": "Explain the 1D space-optimized subset sum algorithm with proof and code."},
        ],
        "stream": True,
    }

    sid = "bench-scenario-10-control"
    tripped = False
    chunks_received = []

    async for chunk in handler.stream_chat_completion(payload, session_id=sid):
        if "data:" in chunk and "[DONE]" not in chunk:
            chunks_received.append(chunk)
            if "Runaway loop halted" in chunk:
                tripped = True

    # 1. Verify 0% false positive: stream was NOT tripped
    assert tripped is False, "Control case should not trip the circuit breaker!"

    # 2. Verify all reasoning and code chunks were delivered
    assert len(chunks_received) >= len(valid_complex_reasoning_chunks)

    # 3. Verify session was recorded as COMPLETED in DB
    session = await temp_db.get_session(sid)
    assert session is not None
    assert session.status == SessionStatus.COMPLETED
