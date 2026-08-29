"""Unit tests for configuration, SQLite database, and tokenomics telemetry."""

import pytest
from tokenshield.config import TokenShieldConfig, get_config
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


def test_config_defaults():
    """Verify default configuration parameters."""
    cfg = get_config()
    assert cfg.PORT == 8000
    assert cfg.LOOP_ANOMALY_THRESHOLD == 0.70
    assert cfg.SIMILARITY_THRESHOLD == 0.85
    assert cfg.SLIDING_WINDOW_TURNS == 10
    assert cfg.NGRAM_N == 3


@pytest.mark.asyncio
async def test_session_lifecycle(temp_db: TelemetryDatabase):
    """Test session creation, retrieval, and updating."""
    session_id = "test-session-1"
    created = await temp_db.create_session(
        SessionCreate(session_id=session_id, model="gpt-4o-mini", status=SessionStatus.ACTIVE)
    )
    assert created.session_id == session_id
    assert created.model == "gpt-4o-mini"
    assert created.status == SessionStatus.ACTIVE
    assert created.total_prompt_tokens == 0

    # Fetch session
    fetched = await temp_db.get_session(session_id)
    assert fetched is not None
    assert fetched.session_id == session_id

    # Update session
    updated = await temp_db.update_session(
        session_id,
        SessionUpdate(
            total_prompt_tokens=150,
            total_completion_tokens=25,
            tokens_saved=3900,
            cost_saved_usd=0.00234,
            status=SessionStatus.TRIPPED,
        ),
    )
    assert updated is not None
    assert updated.total_prompt_tokens == 150
    assert updated.total_completion_tokens == 25
    assert updated.tokens_saved == 3900
    assert updated.status == SessionStatus.TRIPPED


@pytest.mark.asyncio
async def test_trajectory_events(temp_db: TelemetryDatabase):
    """Test recording and retrieving trajectory events."""
    session_id = "test-session-events"
    await temp_db.create_session(
        SessionCreate(session_id=session_id, model="gpt-4o", status=SessionStatus.ACTIVE)
    )

    ev1_id = await temp_db.log_trajectory_event(
        TrajectoryEventCreate(
            session_id=session_id,
            event_type=EventType.CHUNK_EVAL,
            anomaly_score=0.35,
            tokens_processed=15,
            details='{"chunk": "Let me think"}',
        )
    )
    assert ev1_id > 0

    ev2_id = await temp_db.log_trajectory_event(
        TrajectoryEventCreate(
            session_id=session_id,
            event_type=EventType.CIRCUIT_TRIP,
            anomaly_score=0.85,
            tokens_processed=30,
            details='{"reason": "NGRAM_REPETITION"}',
        )
    )
    assert ev2_id > ev1_id

    events = await temp_db.get_session_events(session_id)
    assert len(events) == 2
    assert events[0].event_type == EventType.CHUNK_EVAL
    assert events[1].event_type == EventType.CIRCUIT_TRIP
    assert events[1].anomaly_score == 0.85


@pytest.mark.asyncio
async def test_circuit_trips_and_aggregate_metrics(temp_db: TelemetryDatabase):
    """Test recording circuit trips and aggregate system metrics."""
    s1 = "session-trip-1"
    s2 = "session-trip-2"
    await temp_db.create_session(SessionCreate(session_id=s1, model="gpt-4o-mini", status=SessionStatus.TRIPPED))
    await temp_db.create_session(SessionCreate(session_id=s2, model="gpt-4o", status=SessionStatus.ACTIVE))

    await temp_db.update_session(
        s1,
        SessionUpdate(
            total_prompt_tokens=100,
            total_completion_tokens=20,
            tokens_saved=3800,
            cost_saved_usd=0.038,
            status=SessionStatus.TRIPPED,
        ),
    )
    await temp_db.update_session(
        s2,
        SessionUpdate(
            total_prompt_tokens=200,
            total_completion_tokens=50,
            tokens_saved=0,
            cost_saved_usd=0.0,
            status=SessionStatus.ACTIVE,
        ),
    )

    trip_id = await temp_db.log_circuit_trip(
        CircuitTripCreate(
            session_id=s1,
            trigger_reason=TripReason.CIRCULAR_REASONING,
            anomaly_score=0.88,
            tokens_at_trip=20,
            estimated_tokens_saved=3800,
        )
    )
    assert trip_id > 0

    trips = await temp_db.get_all_trips()
    assert len(trips) == 1
    assert trips[0].trigger_reason == TripReason.CIRCULAR_REASONING

    metrics = await temp_db.get_aggregate_metrics()
    assert metrics.total_sessions == 2
    assert metrics.active_sessions == 1
    assert metrics.tripped_sessions == 1
    assert metrics.total_prompt_tokens == 300
    assert metrics.total_completion_tokens == 70
    assert metrics.total_tokens_saved == 3800
    assert metrics.total_cost_saved_usd == 0.038
    assert metrics.total_circuit_trips == 1


def test_tokenomics_calculator():
    """Test token pricing and savings computations."""
    # Pricing checks
    pricing_4o = TokenomicsCalculator.get_model_pricing("gpt-4o")
    assert pricing_4o.input_per_million == 2.50
    assert pricing_4o.output_per_million == 10.00

    pricing_mini = TokenomicsCalculator.get_model_pricing("gpt-4o-mini-2024-07-18")
    assert pricing_mini.input_per_million == 0.15

    # Cost calculation
    cost = TokenomicsCalculator.calculate_cost(prompt_tokens=1000, completion_tokens=500, model="gpt-4o")
    # (1000/1M * 2.5) + (500/1M * 10) = 0.0025 + 0.005 = 0.0075
    assert pytest.approx(cost, 0.0001) == 0.0075

    # Savings calculation
    savings = TokenomicsCalculator.calculate_savings(
        tokens_at_trip=30,
        max_context_limit=4000,
        model="gpt-4o",
        pre_exec_tokens_saved=500,
    )
    assert savings.tokens_saved == 3970 + 500  # (4000 - 30) + 500 = 4470
    assert savings.reduction_percentage > 95.0
    assert savings.cost_saved_usd > 0.04
