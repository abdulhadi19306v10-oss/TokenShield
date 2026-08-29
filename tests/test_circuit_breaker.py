"""Unit tests for AnomalyThresholdGate, PromptSteeringNode, HumanCheckpointGate, and CircuitBreaker."""

import asyncio
import pytest
from tokenshield.config import TokenShieldConfig
from tokenshield.engine.circuit_breaker import (
    AnomalyThresholdGate,
    CircuitBreaker,
    CircuitDecision,
    HumanCheckpointGate,
    PromptSteeringNode,
)
from tokenshield.engine.stream_monitor import AnomalyScoreResult
from tokenshield.telemetry.models import TripReason


def test_anomaly_threshold_gate():
    """Verify threshold evaluation and gating decisions."""
    cfg = TokenShieldConfig(
        LOOP_ANOMALY_THRESHOLD=0.70,
        MIN_TOKENS_BEFORE_CHECK=10,
    )
    gate = AnomalyThresholdGate(cfg)

    # 1. Warm-up tokens (should pass even if score is high)
    res_warmup = AnomalyScoreResult(anomaly_score=0.85, total_tokens=5)
    assert gate.evaluate(res_warmup) == CircuitDecision.PASS

    # 2. Normal score after warmup
    res_normal = AnomalyScoreResult(anomaly_score=0.20, total_tokens=25)
    assert gate.evaluate(res_normal) == CircuitDecision.PASS

    # 3. Warning score (>= 0.75 * 0.70 = 0.525)
    res_warn = AnomalyScoreResult(anomaly_score=0.55, total_tokens=25)
    assert gate.evaluate(res_warn) == CircuitDecision.WARN

    # 4. Trip score
    res_trip = AnomalyScoreResult(anomaly_score=0.75, total_tokens=25, is_loop_detected=True)
    assert gate.evaluate(res_trip) == CircuitDecision.TRIP

    # 5. Inside code fence (threshold raised to 0.90, so 0.75 does not trip)
    res_code = AnomalyScoreResult(anomaly_score=0.75, total_tokens=25, in_code_fence=True)
    assert gate.evaluate(res_code) != CircuitDecision.TRIP
    assert gate.evaluate(res_code) == CircuitDecision.WARN


def test_prompt_steering_synthesis():
    """Verify dynamic recovery steering messages for different trip reasons."""
    steering = PromptSteeringNode()

    p_ngram = steering.synthesize_recovery_prompt(TripReason.NGRAM_REPETITION)
    assert p_ngram["role"] == "system"
    assert "Verbatim repetition loop" in p_ngram["content"]

    p_circular = steering.synthesize_recovery_prompt(TripReason.CIRCULAR_REASONING)
    assert "Circular reasoning detected" in p_circular["content"]

    p_tool = steering.synthesize_recovery_prompt(TripReason.TOOL_ERROR_LOOP)
    assert "Repeated tool failure loop" in p_tool["content"]


@pytest.mark.asyncio
async def test_human_checkpoint_gate_approval():
    """Verify operator clearance approval signal."""
    gate = HumanCheckpointGate()
    session_id = "sess-human-1"

    async def approve_after_delay():
        await asyncio.sleep(0.05)
        gate.resolve_clearance(session_id, approved=True)

    task = asyncio.create_task(approve_after_delay())
    approved = await gate.wait_for_clearance(session_id, timeout_seconds=1.0)
    await task

    assert approved is True


@pytest.mark.asyncio
async def test_human_checkpoint_gate_rejection():
    """Verify operator rejection signal."""
    gate = HumanCheckpointGate()
    session_id = "sess-human-2"

    async def reject_after_delay():
        await asyncio.sleep(0.05)
        gate.resolve_clearance(session_id, approved=False)

    task = asyncio.create_task(reject_after_delay())
    approved = await gate.wait_for_clearance(session_id, timeout_seconds=1.0)
    await task

    assert approved is False


@pytest.mark.asyncio
async def test_human_checkpoint_gate_timeout():
    """Verify gate aborts on timeout if operator does not respond."""
    gate = HumanCheckpointGate()
    session_id = "sess-human-timeout"

    approved = await gate.wait_for_clearance(session_id, timeout_seconds=0.1)
    assert approved is False


def test_circuit_breaker_evaluate_and_decide():
    """Verify coordinating CircuitBreaker evaluation."""
    cb = CircuitBreaker()

    # Pass case
    res_pass = AnomalyScoreResult(anomaly_score=0.10, total_tokens=30)
    decision, reason, steering = cb.evaluate_and_decide(res_pass)
    assert decision == CircuitDecision.PASS
    assert reason is None
    assert steering is None

    # Trip case
    res_trip = AnomalyScoreResult(
        anomaly_score=0.85,
        total_tokens=30,
        is_loop_detected=True,
        trigger_reason=TripReason.CIRCULAR_REASONING,
    )
    decision, reason, steering = cb.evaluate_and_decide(res_trip)
    assert decision == CircuitDecision.TRIP
    assert reason == TripReason.CIRCULAR_REASONING
    assert steering is not None
    assert "[TokenShield Circuit Intercept]" in steering["content"]
