"""Request pipeline orchestrator for pre-flight optimization, streaming interception, and circuit breaking."""

import json
import time
import uuid
from typing import Any, AsyncGenerator, Dict, Optional

from tokenshield.config import get_config
from tokenshield.engine.circuit_breaker import CircuitBreaker, CircuitDecision
from tokenshield.engine.pre_execution import PreExecutionEngine
from tokenshield.engine.stream_monitor import StreamMonitor
from tokenshield.telemetry.database import TelemetryDatabase
from tokenshield.telemetry.metrics import TokenomicsCalculator
from tokenshield.telemetry.models import (
    CircuitTripCreate,
    EventType,
    SessionCreate,
    SessionStatus,
    SessionUpdate,
    TrajectoryEventCreate,
    TripReason,
)
from tokenshield.proxy.client import UpstreamClient


class ProxyHandler:
    """Orchestrates end-to-end request lifecycle from pre-flight compression to streaming circuit breaking."""

    def __init__(
        self,
        db: Optional[TelemetryDatabase] = None,
        upstream_client: Optional[UpstreamClient] = None,
        pre_exec: Optional[PreExecutionEngine] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        self.config = get_config()
        self.db = db or TelemetryDatabase()
        self.upstream_client = upstream_client or UpstreamClient()
        self.pre_exec = pre_exec or PreExecutionEngine()
        self.circuit_breaker = circuit_breaker or CircuitBreaker(self.config)

    async def stream_chat_completion(
        self,
        payload: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream chat completions with real-time in-flight loop interception and telemetry logging."""
        # 1. Session initialization
        # ponytail: generate clean 8-char hex session if none provided
        sid = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        model = payload.get("model", self.config.DEFAULT_MODEL)
        messages = payload.get("messages", [])

        # 2. Pre-Execution context trimming & tool payload compression
        optimized_messages, pre_metrics = self.pre_exec.process_messages(
            messages,
            model=model,
        )

        optimized_payload = dict(payload)
        optimized_payload["messages"] = optimized_messages
        optimized_payload["stream"] = True

        # 3. Database session start & pre-flight telemetry
        try:
            await self.db.initialize()
            await self.db.create_session(
                SessionCreate(session_id=sid, model=model, status=SessionStatus.ACTIVE)
            )
            if pre_metrics.tokens_saved > 0:
                await self.db.log_trajectory_event(
                    TrajectoryEventCreate(
                        session_id=sid,
                        event_type=EventType.PRE_EXEC_TRIM,
                        tokens_processed=pre_metrics.trimmed_prompt_tokens,
                        details=json.dumps(pre_metrics.model_dump()),
                    )
                )
        except Exception:
            pass  # Telemetry logging failure should not crash proxy routing

        # 4. In-Flight Streaming & Monitoring Loop
        monitor = StreamMonitor(session_id=sid)
        stream_generator = self.upstream_client.stream_chat(optimized_payload)
        is_tripped = False
        completion_tokens_count = 0

        try:
            async for raw_chunk in stream_generator:
                deltas = monitor.inspector.feed_chunk(raw_chunk)

                for chunk_text, finish_reason in deltas:
                    if chunk_text is not None:
                        completion_tokens_count += 1
                        anomaly_res = monitor.evaluate_chunk(chunk_text)

                        decision, trip_reason, steering = self.circuit_breaker.evaluate_and_decide(
                            anomaly_res, session_id=sid
                        )

                        # Log noteworthy anomaly spikes
                        if anomaly_res.anomaly_score >= 0.45 and self.db:
                            try:
                                await self.db.log_trajectory_event(
                                    TrajectoryEventCreate(
                                        session_id=sid,
                                        event_type=EventType.CHUNK_EVAL,
                                        anomaly_score=anomaly_res.anomaly_score,
                                        tokens_processed=anomaly_res.total_tokens,
                                        details=json.dumps({
                                            "ngram_score": anomaly_res.ngram_score,
                                            "similarity_score": anomaly_res.similarity_score,
                                            "in_code_fence": anomaly_res.in_code_fence,
                                        }),
                                    )
                                )
                            except Exception:
                                pass

                        # 5. Circuit Tripped Intervention
                        if decision == CircuitDecision.TRIP:
                            is_tripped = True
                            resolved_reason = trip_reason or TripReason.NGRAM_REPETITION
                            savings = TokenomicsCalculator.calculate_savings(
                                tokens_at_trip=anomaly_res.total_tokens,
                                model=model,
                                pre_exec_tokens_saved=pre_metrics.tokens_saved,
                            )

                            # Persist trip and update session status
                            try:
                                await self.db.log_circuit_trip(
                                    CircuitTripCreate(
                                        session_id=sid,
                                        trigger_reason=resolved_reason,
                                        anomaly_score=anomaly_res.anomaly_score,
                                        tokens_at_trip=anomaly_res.total_tokens,
                                        estimated_tokens_saved=savings.tokens_saved,
                                    )
                                )
                                await self.db.update_session(
                                    sid,
                                    SessionUpdate(
                                        total_prompt_tokens=pre_metrics.trimmed_prompt_tokens,
                                        total_completion_tokens=anomaly_res.total_tokens,
                                        tokens_saved=savings.tokens_saved,
                                        cost_saved_usd=savings.cost_saved_usd,
                                        status=SessionStatus.TRIPPED,
                                    ),
                                )
                            except Exception:
                                pass

                            # Yield synthetic termination chunk to client
                            notice_payload = {
                                "id": f"chatcmpl-trip-{uuid.uuid4().hex[:8]}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {
                                            "content": "\n\n[TokenShield Circuit Intercept: Runaway loop halted to prevent token burn]"
                                        },
                                        "finish_reason": "stop",
                                    }
                                ],
                            }
                            yield f"data: {json.dumps(notice_payload)}\n\n"
                            yield "data: [DONE]\n\n"
                            return

                # Normal chunk forwarding
                if not is_tripped:
                    yield raw_chunk

            # 6. Normal stream completion
            if not is_tripped:
                savings = TokenomicsCalculator.calculate_savings(
                    tokens_at_trip=completion_tokens_count,
                    max_context_limit=completion_tokens_count,
                    model=model,
                    pre_exec_tokens_saved=pre_metrics.tokens_saved,
                )
                try:
                    await self.db.update_session(
                        sid,
                        SessionUpdate(
                            total_prompt_tokens=pre_metrics.trimmed_prompt_tokens,
                            total_completion_tokens=completion_tokens_count,
                            tokens_saved=pre_metrics.tokens_saved,
                            cost_saved_usd=savings.cost_saved_usd,
                            status=SessionStatus.COMPLETED,
                        ),
                    )
                except Exception:
                    pass

        except Exception as exc:
            # Emit graceful JSON error frame if upstream fails
            err_frame = {
                "error": {
                    "message": f"TokenShield Proxy error: {str(exc)}",
                    "type": "tokenshield_proxy_error",
                    "code": 502,
                }
            }
            yield f"data: {json.dumps(err_frame)}\n\n"
            yield "data: [DONE]\n\n"

    async def sync_chat_completion(
        self,
        payload: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute non-streaming completion with pre-flight compression."""
        sid = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        model = payload.get("model", self.config.DEFAULT_MODEL)
        messages = payload.get("messages", [])

        optimized_messages, pre_metrics = self.pre_exec.process_messages(
            messages,
            model=model,
        )
        optimized_payload = dict(payload)
        optimized_payload["messages"] = optimized_messages

        try:
            await self.db.initialize()
            await self.db.create_session(
                SessionCreate(session_id=sid, model=model, status=SessionStatus.ACTIVE)
            )
        except Exception:
            pass

        response = await self.upstream_client.sync_chat(optimized_payload)

        # Record completion metrics
        usage = response.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", pre_metrics.trimmed_prompt_tokens)
        comp_tokens = usage.get("completion_tokens", 0)

        cost_saved = (pre_metrics.tokens_saved / 1_000_000.0) * TokenomicsCalculator.get_model_pricing(model).input_per_million

        try:
            await self.db.update_session(
                sid,
                SessionUpdate(
                    total_prompt_tokens=prompt_tokens,
                    total_completion_tokens=comp_tokens,
                    tokens_saved=pre_metrics.tokens_saved,
                    cost_saved_usd=round(cost_saved, 6),
                    status=SessionStatus.COMPLETED,
                ),
            )
        except Exception:
            pass

        return response
