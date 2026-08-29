"""FastAPI application providing OpenAI-compatible /v1/chat/completions proxy and telemetry endpoints."""

from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from tokenshield.config import get_config
from tokenshield.proxy.handler import ProxyHandler
from tokenshield.telemetry.database import TelemetryDatabase


class ChatMessage(BaseModel):
    role: str
    content: Any
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


class ChatCompletionRequest(BaseModel):
    model: str = "gpt-4o-mini"
    messages: List[Dict[str, Any]]
    stream: bool = False
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Any] = None

    model_config = {"extra": "allow"}


class HumanGateRequest(BaseModel):
    session_id: str
    approved: bool


def create_app(
    db: Optional[TelemetryDatabase] = None,
    handler: Optional[ProxyHandler] = None,
) -> FastAPI:
    """Create and configure FastAPI application with OpenAI-compatible routes."""
    config = get_config()
    database = db or TelemetryDatabase()
    proxy_handler = handler or ProxyHandler(db=database)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: initialize database tables
        await database.initialize()
        yield
        # Shutdown: close db pool
        await database.close()

    app = FastAPI(
        title="TokenShield Proxy",
        description="Real-Time Agentic Trajectory & Token Interceptor Middleware",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Attach shared handler to app state
    app.state.handler = proxy_handler
    app.state.db = database

    # --- Standard OpenAI Endpoints ---

    @app.post("/v1/chat/completions")
    @app.post("/chat/completions")
    async def chat_completions(request: Request, payload: ChatCompletionRequest):
        """OpenAI-compatible chat completion proxy endpoint supporting streaming and sync execution."""
        session_id = request.headers.get("x-session-id") or request.headers.get("session-id")
        raw_payload = payload.model_dump(exclude_none=True)

        if payload.stream:
            # ponytail: direct async generator stream with standard text/event-stream media type
            generator = proxy_handler.stream_chat_completion(raw_payload, session_id=session_id)
            return StreamingResponse(
                generator,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            result = await proxy_handler.sync_chat_completion(raw_payload, session_id=session_id)
            return JSONResponse(content=result)

    @app.get("/v1/models")
    @app.get("/models")
    async def list_models():
        """Return available model IDs for OpenAI client SDK compatibility."""
        return {
            "object": "list",
            "data": [
                {"id": "gpt-4o", "object": "model", "owned_by": "tokenshield"},
                {"id": "gpt-4o-mini", "object": "model", "owned_by": "tokenshield"},
                {"id": "claude-3-5-sonnet", "object": "model", "owned_by": "tokenshield"},
            ],
        }

    # --- Health & Control Endpoints ---

    @app.get("/health")
    async def health_check():
        """Health and telemetry status check."""
        metrics = await database.get_aggregate_metrics()
        return {
            "status": "healthy",
            "service": "tokenshield",
            "version": "0.1.0",
            "active_sessions": metrics.active_sessions,
            "total_tokens_saved": metrics.total_tokens_saved,
        }

    @app.post("/v1/control/human-gate")
    async def resolve_human_gate(body: HumanGateRequest):
        """Operator signal endpoint to resume or terminate a session held at human checkpoint."""
        resolved = proxy_handler.circuit_breaker.human_gate.resolve_clearance(
            session_id=body.session_id,
            approved=body.approved,
        )
        if not resolved:
            raise HTTPException(status_code=404, detail="Session not waiting for human clearance")
        return {"session_id": body.session_id, "status": "resolved", "approved": body.approved}

    # --- Telemetry Query Endpoints for Dashboard ---

    @app.get("/v1/telemetry/metrics")
    async def get_metrics():
        return await database.get_aggregate_metrics()

    @app.get("/v1/telemetry/sessions")
    async def get_sessions(limit: int = 50, offset: int = 0):
        return await database.list_sessions(limit=limit, offset=offset)

    @app.get("/v1/telemetry/events/{session_id}")
    async def get_events(session_id: str):
        return await database.get_session_events(session_id=session_id)

    @app.get("/v1/telemetry/trips")
    async def get_trips(limit: int = 50):
        return await database.get_all_trips(limit=limit)

    return app


# Default application instance for Uvicorn
app = create_app()
