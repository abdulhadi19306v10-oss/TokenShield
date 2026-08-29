"""Telemetry schemas, enums, and database DDL definitions."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    """Lifecycle states for a monitored agent session."""
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TRIPPED = "TRIPPED"
    PAUSED = "PAUSED"


class EventType(str, Enum):
    """Types of trajectory and stream interception events."""
    PRE_EXEC_TRIM = "PRE_EXEC_TRIM"
    CHUNK_EVAL = "CHUNK_EVAL"
    CIRCUIT_TRIP = "CIRCUIT_TRIP"
    STEERING_INJECT = "STEERING_INJECT"
    HUMAN_CLEARANCE = "HUMAN_CLEARANCE"


class TripReason(str, Enum):
    """Categorized triggers for circuit breaker trips."""
    NGRAM_REPETITION = "NGRAM_REPETITION"
    CIRCULAR_REASONING = "CIRCULAR_REASONING"
    TOOL_ERROR_LOOP = "TOOL_ERROR_LOOP"
    PAYLOAD_OVERFLOW = "PAYLOAD_OVERFLOW"


# --- Pydantic Data Models ---

class SessionCreate(BaseModel):
    session_id: str
    model: str
    status: SessionStatus = SessionStatus.ACTIVE


class SessionUpdate(BaseModel):
    total_prompt_tokens: Optional[int] = None
    total_completion_tokens: Optional[int] = None
    tokens_saved: Optional[int] = None
    cost_saved_usd: Optional[float] = None
    status: Optional[SessionStatus] = None


class SessionRecord(BaseModel):
    session_id: str
    model: str
    created_at: str
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    tokens_saved: int = 0
    cost_saved_usd: float = 0.0
    status: SessionStatus = SessionStatus.ACTIVE


class TrajectoryEventCreate(BaseModel):
    session_id: str
    event_type: EventType
    anomaly_score: float = 0.0
    tokens_processed: int = 0
    details: Optional[str] = None  # JSON string or description


class TrajectoryEventRecord(BaseModel):
    event_id: int
    session_id: str
    timestamp: str
    event_type: EventType
    anomaly_score: float = 0.0
    tokens_processed: int = 0
    details: Optional[str] = None


class CircuitTripCreate(BaseModel):
    session_id: str
    trigger_reason: TripReason
    anomaly_score: float
    tokens_at_trip: int
    estimated_tokens_saved: int


class CircuitTripRecord(BaseModel):
    trip_id: int
    session_id: str
    timestamp: str
    trigger_reason: TripReason
    anomaly_score: float
    tokens_at_trip: int
    estimated_tokens_saved: int


class AggregateMetrics(BaseModel):
    total_sessions: int = 0
    active_sessions: int = 0
    tripped_sessions: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens_saved: int = 0
    total_cost_saved_usd: float = 0.0
    total_circuit_trips: int = 0


# --- Database DDL ---
# ponytail: clean native SQLite schema with foreign keys and indices
CREATE_TABLES_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_prompt_tokens INTEGER DEFAULT 0,
    total_completion_tokens INTEGER DEFAULT 0,
    tokens_saved INTEGER DEFAULT 0,
    cost_saved_usd REAL DEFAULT 0.0,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trajectory_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,
    anomaly_score REAL DEFAULT 0.0,
    tokens_processed INTEGER DEFAULT 0,
    details TEXT,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS circuit_trips (
    trip_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    trigger_reason TEXT NOT NULL,
    anomaly_score REAL NOT NULL,
    tokens_at_trip INTEGER NOT NULL,
    estimated_tokens_saved INTEGER NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_session_id ON trajectory_events(session_id);
CREATE INDEX IF NOT EXISTS idx_trips_session_id ON circuit_trips(session_id);
"""
