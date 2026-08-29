"""Asynchronous SQLite connection manager and CRUD operations for TokenShield telemetry."""

import json
from typing import Any, Dict, List, Optional
import aiosqlite

from tokenshield.config import get_config
from tokenshield.telemetry.models import (
    CREATE_TABLES_SQL,
    AggregateMetrics,
    CircuitTripCreate,
    CircuitTripRecord,
    EventType,
    SessionCreate,
    SessionRecord,
    SessionStatus,
    SessionUpdate,
    TrajectoryEventCreate,
    TrajectoryEventRecord,
    TripReason,
)


class TelemetryDatabase:
    """Async SQLite persistence layer for session trajectories, stream metrics, and trips."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_config().DATABASE_PATH
        self._conn: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """Initialize database connection and create schema if not exists."""
        if not self._conn:
            self._conn = await aiosqlite.connect(self.db_path)
            self._conn.row_factory = aiosqlite.Row
            # ponytail: executescript runs the entire schema DDL in one go
            await self._conn.executescript(CREATE_TABLES_SQL)
            await self._conn.commit()

    async def close(self) -> None:
        """Close open database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> "TelemetryDatabase":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def _ensure_connected(self) -> aiosqlite.Connection:
        if not self._conn:
            await self.initialize()
        assert self._conn is not None
        return self._conn

    # --- Session Operations ---

    async def create_session(self, session: SessionCreate) -> SessionRecord:
        """Insert or replace a new agent session."""
        conn = await self._ensure_connected()
        async with conn.execute(
            """
            INSERT INTO sessions (session_id, model, status)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                model = excluded.model,
                status = excluded.status
            RETURNING session_id, model, created_at, total_prompt_tokens, total_completion_tokens, tokens_saved, cost_saved_usd, status
            """,
            (session.session_id, session.model, session.status.value),
        ) as cursor:
            row = await cursor.fetchone()
            await conn.commit()
            return self._row_to_session(row)

    async def update_session(self, session_id: str, update: SessionUpdate) -> Optional[SessionRecord]:
        """Increment or update session token counts, savings, and status."""
        conn = await self._ensure_connected()
        # ponytail: dynamic clause builder keeps updates concise without ORM bloat
        clauses: List[str] = []
        params: List[Any] = []

        if update.total_prompt_tokens is not None:
            clauses.append("total_prompt_tokens = ?")
            params.append(update.total_prompt_tokens)
        if update.total_completion_tokens is not None:
            clauses.append("total_completion_tokens = ?")
            params.append(update.total_completion_tokens)
        if update.tokens_saved is not None:
            clauses.append("tokens_saved = ?")
            params.append(update.tokens_saved)
        if update.cost_saved_usd is not None:
            clauses.append("cost_saved_usd = ?")
            params.append(update.cost_saved_usd)
        if update.status is not None:
            clauses.append("status = ?")
            params.append(update.status.value)

        if not clauses:
            return await self.get_session(session_id)

        params.append(session_id)
        sql = f"""
            UPDATE sessions
            SET {', '.join(clauses)}
            WHERE session_id = ?
            RETURNING session_id, model, created_at, total_prompt_tokens, total_completion_tokens, tokens_saved, cost_saved_usd, status
        """
        async with conn.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            await conn.commit()
            return self._row_to_session(row) if row else None

    async def get_session(self, session_id: str) -> Optional[SessionRecord]:
        """Fetch session record by ID."""
        conn = await self._ensure_connected()
        async with conn.execute(
            """
            SELECT session_id, model, created_at, total_prompt_tokens, total_completion_tokens, tokens_saved, cost_saved_usd, status
            FROM sessions WHERE session_id = ?
            """,
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return self._row_to_session(row) if row else None

    async def list_sessions(self, limit: int = 50, offset: int = 0) -> List[SessionRecord]:
        """List sessions ordered by newest first."""
        conn = await self._ensure_connected()
        async with conn.execute(
            """
            SELECT session_id, model, created_at, total_prompt_tokens, total_completion_tokens, tokens_saved, cost_saved_usd, status
            FROM sessions ORDER BY created_at DESC LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_session(r) for r in rows]

    # --- Trajectory Event Operations ---

    async def log_trajectory_event(self, event: TrajectoryEventCreate) -> int:
        """Record an in-flight evaluation or pre-execution trajectory event."""
        conn = await self._ensure_connected()
        async with conn.execute(
            """
            INSERT INTO trajectory_events (session_id, event_type, anomaly_score, tokens_processed, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event.session_id,
                event.event_type.value,
                event.anomaly_score,
                event.tokens_processed,
                event.details,
            ),
        ) as cursor:
            event_id = cursor.lastrowid
            await conn.commit()
            return event_id

    async def get_session_events(self, session_id: str) -> List[TrajectoryEventRecord]:
        """Fetch all trajectory events for a given session."""
        conn = await self._ensure_connected()
        async with conn.execute(
            """
            SELECT event_id, session_id, timestamp, event_type, anomaly_score, tokens_processed, details
            FROM trajectory_events WHERE session_id = ? ORDER BY event_id ASC
            """,
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                TrajectoryEventRecord(
                    event_id=r["event_id"],
                    session_id=r["session_id"],
                    timestamp=str(r["timestamp"]),
                    event_type=EventType(r["event_type"]),
                    anomaly_score=r["anomaly_score"],
                    tokens_processed=r["tokens_processed"],
                    details=r["details"],
                )
                for r in rows
            ]

    # --- Circuit Trip Operations ---

    async def log_circuit_trip(self, trip: CircuitTripCreate) -> int:
        """Record a circuit breaker trip incident."""
        conn = await self._ensure_connected()
        async with conn.execute(
            """
            INSERT INTO circuit_trips (session_id, trigger_reason, anomaly_score, tokens_at_trip, estimated_tokens_saved)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                trip.session_id,
                trip.trigger_reason.value,
                trip.anomaly_score,
                trip.tokens_at_trip,
                trip.estimated_tokens_saved,
            ),
        ) as cursor:
            trip_id = cursor.lastrowid
            await conn.commit()
            return trip_id

    async def get_all_trips(self, limit: int = 50) -> List[CircuitTripRecord]:
        """Fetch all recorded circuit trip events."""
        conn = await self._ensure_connected()
        async with conn.execute(
            """
            SELECT trip_id, session_id, timestamp, trigger_reason, anomaly_score, tokens_at_trip, estimated_tokens_saved
            FROM circuit_trips ORDER BY trip_id DESC LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                CircuitTripRecord(
                    trip_id=r["trip_id"],
                    session_id=r["session_id"],
                    timestamp=str(r["timestamp"]),
                    trigger_reason=TripReason(r["trigger_reason"]),
                    anomaly_score=r["anomaly_score"],
                    tokens_at_trip=r["tokens_at_trip"],
                    estimated_tokens_saved=r["estimated_tokens_saved"],
                )
                for r in rows
            ]

    # --- Aggregations & Metrics ---

    async def get_aggregate_metrics(self) -> AggregateMetrics:
        """Compute system-wide aggregated token savings and activity metrics."""
        conn = await self._ensure_connected()
        async with conn.execute(
            """
            SELECT 
                COUNT(*) as total_sessions,
                COALESCE(SUM(CASE WHEN status = 'ACTIVE' THEN 1 ELSE 0 END), 0) as active_sessions,
                COALESCE(SUM(CASE WHEN status = 'TRIPPED' THEN 1 ELSE 0 END), 0) as tripped_sessions,
                COALESCE(SUM(total_prompt_tokens), 0) as total_prompt_tokens,
                COALESCE(SUM(total_completion_tokens), 0) as total_completion_tokens,
                COALESCE(SUM(tokens_saved), 0) as total_tokens_saved,
                COALESCE(SUM(cost_saved_usd), 0.0) as total_cost_saved_usd
            FROM sessions
            """
        ) as cursor:
            row = await cursor.fetchone()
            total_trips = 0
            async with conn.execute("SELECT COUNT(*) as cnt FROM circuit_trips") as trip_cur:
                trip_row = await trip_cur.fetchone()
                total_trips = trip_row["cnt"] if trip_row else 0

            return AggregateMetrics(
                total_sessions=row["total_sessions"],
                active_sessions=row["active_sessions"],
                tripped_sessions=row["tripped_sessions"],
                total_prompt_tokens=row["total_prompt_tokens"],
                total_completion_tokens=row["total_completion_tokens"],
                total_tokens_saved=row["total_tokens_saved"],
                total_cost_saved_usd=round(row["total_cost_saved_usd"], 4),
                total_circuit_trips=total_trips,
            )

    @staticmethod
    def _row_to_session(row: Any) -> SessionRecord:
        # ponytail: centralized converter handles row mapping consistently
        return SessionRecord(
            session_id=row["session_id"],
            model=row["model"],
            created_at=str(row["created_at"]),
            total_prompt_tokens=row["total_prompt_tokens"],
            total_completion_tokens=row["total_completion_tokens"],
            tokens_saved=row["tokens_saved"],
            cost_saved_usd=row["cost_saved_usd"],
            status=SessionStatus(row["status"]),
        )
