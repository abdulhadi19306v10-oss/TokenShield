"""Circuit breaker, anomaly threshold gate, prompt steering injector, and human clearance node."""

import asyncio
from enum import Enum
from typing import Any, Dict, Optional, Tuple
from pydantic import BaseModel

from tokenshield.config import get_config
from tokenshield.engine.stream_monitor import AnomalyScoreResult
from tokenshield.telemetry.models import TripReason


class CircuitDecision(str, Enum):
    """Interception decisions made by the circuit breaker."""
    PASS = "PASS"
    WARN = "WARN"
    TRIP = "TRIP"


class AnomalyThresholdGate:
    """Evaluates computed anomaly scores against configured trip boundaries."""

    def __init__(self, config=None):
        self.config = config or get_config()

    def evaluate(
        self,
        anomaly_result: AnomalyScoreResult,
        threshold: Optional[float] = None,
        min_tokens: Optional[int] = None,
    ) -> CircuitDecision:
        """Decide whether stream passes or trips circuit based on scores and code fence context."""
        min_tok = min_tokens if min_tokens is not None else self.config.MIN_TOKENS_BEFORE_CHECK
        trip_threshold = threshold if threshold is not None else self.config.LOOP_ANOMALY_THRESHOLD

        # If inside code fences, raise threshold to 0.90 to avoid false positives on syntax keywords
        if anomaly_result.in_code_fence:
            trip_threshold = max(trip_threshold, 0.90)

        # Do not trip prematurely during initial warm-up tokens
        if anomaly_result.total_tokens < min_tok:
            return CircuitDecision.PASS

        if anomaly_result.is_loop_detected or anomaly_result.anomaly_score >= trip_threshold:
            return CircuitDecision.TRIP

        if anomaly_result.anomaly_score >= (trip_threshold * 0.75):
            return CircuitDecision.WARN

        return CircuitDecision.PASS


class PromptSteeringNode:
    """Synthesizes targeted system prompt instructions to guide looping agents toward recovery."""

    @staticmethod
    def synthesize_recovery_prompt(
        reason: TripReason = TripReason.TOOL_ERROR_LOOP,
        offending_snippet: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate targeted OpenAI system prompt steering message."""
        base_msg = (
            "[TokenShield Circuit Intercept] Execution loop detected: You have repeated tool calls or circular reasoning "
            "without progress. DO NOT call the same tool with identical arguments. Change your approach or return your "
            "final answer immediately."
        )

        if reason == TripReason.NGRAM_REPETITION:
            msg = (
                "[TokenShield Circuit Intercept] Verbatim repetition loop detected: You are repeating identical phrases or "
                "tokens endlessly. Halt repetition and provide a direct final response."
            )
        elif reason == TripReason.CIRCULAR_REASONING:
            msg = (
                "[TokenShield Circuit Intercept] Circular reasoning detected: You are paraphrasing the same reasoning steps "
                "without making progress. State your conclusion or explore an alternative method."
            )
        elif reason == TripReason.TOOL_ERROR_LOOP:
            msg = (
                "[TokenShield Circuit Intercept] Repeated tool failure loop: The tool call failed or returned unchanged outputs. "
                "Do NOT retry with the same parameters. Handle the failure gracefully."
            )
        else:
            msg = base_msg

        if offending_snippet:
            msg += f" (Detected pattern: '{offending_snippet[:80]}')"

        return {"role": "system", "content": msg}


class HumanCheckpointGate:
    """Async event-based synchronization node for human operator intervention."""

    def __init__(self):
        self._events: Dict[str, asyncio.Event] = {}
        self._decisions: Dict[str, bool] = {}

    async def wait_for_clearance(self, session_id: str, timeout_seconds: float = 30.0) -> bool:
        """Suspend execution until operator clears or rejects on Streamlit dashboard."""
        event = asyncio.Event()
        self._events[session_id] = event
        self._decisions.pop(session_id, None)

        try:
            # Wait for event signal with timeout
            # ponytail: asyncio.wait_for delivers clean async timeout handling
            await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
            return self._decisions.get(session_id, False)
        except asyncio.TimeoutError:
            # Default to abort on timeout for safety
            return False
        finally:
            self._events.pop(session_id, None)
            self._decisions.pop(session_id, None)

    def resolve_clearance(self, session_id: str, approved: bool) -> bool:
        """Signal waiting session with operator decision."""
        if session_id in self._events:
            self._decisions[session_id] = approved
            self._events[session_id].set()
            return True
        return False


class CircuitBreaker:
    """Coordinating circuit breaker engine managing threshold gating, prompt steering, and human checkpointing."""

    def __init__(self, config=None):
        self.config = config or get_config()
        self.gate = AnomalyThresholdGate(self.config)
        self.steering = PromptSteeringNode()
        self.human_gate = HumanCheckpointGate()

    def evaluate_and_decide(
        self,
        anomaly_result: AnomalyScoreResult,
        session_id: str = "default",
    ) -> Tuple[CircuitDecision, Optional[TripReason], Optional[Dict[str, Any]]]:
        """Determine stream action, resolve trip reason, and generate recovery steering if tripped."""
        decision = self.gate.evaluate(anomaly_result)

        if decision == CircuitDecision.TRIP:
            reason = anomaly_result.trigger_reason or TripReason.NGRAM_REPETITION
            steering_prompt = None
            if self.config.AUTO_INJECT_STEERING:
                steering_prompt = self.steering.synthesize_recovery_prompt(reason)
            return CircuitDecision.TRIP, reason, steering_prompt

        return decision, None, None
