"""Shared Pytest fixtures for TokenShield test suite."""

import asyncio
import os
import tempfile
import pytest
import pytest_asyncio

from tokenshield.config import TokenShieldConfig
from tokenshield.telemetry.database import TelemetryDatabase


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def temp_db():
    """Create a temporary SQLite database for isolated test execution."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = TelemetryDatabase(db_path=path)
    await db.initialize()
    try:
        yield db
    finally:
        await db.close()
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


@pytest.fixture
def test_config():
    """Return test configuration instance."""
    return TokenShieldConfig(
        HOST="127.0.0.1",
        PORT=8000,
        DATABASE_PATH=":memory:",
        LOOP_ANOMALY_THRESHOLD=0.70,
        SIMILARITY_THRESHOLD=0.85,
        MIN_TOKENS_BEFORE_CHECK=10,
    )
