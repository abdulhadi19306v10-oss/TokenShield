"""TokenShield configuration management with Pydantic BaseSettings."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class TokenShieldConfig(BaseSettings):
    """Central configuration for TokenShield runtime and anomaly detection thresholds."""

    # Proxy Network Settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    UPSTREAM_BASE_URL: str = "https://api.openai.com/v1"
    UPSTREAM_API_KEY: str = ""
    DEFAULT_MODEL: str = "gpt-4o-mini"

    # Pre-Execution Thresholds
    MAX_TOOL_PAYLOAD_BYTES: int = 4096  # Payloads > 4KB trigger key deduplication & summarization
    SLIDING_WINDOW_TURNS: int = 10  # Max conversation turns to retain before trimming
    ENABLE_DEDUPLICATION: bool = True

    # In-Flight Streaming & Anomaly Thresholds
    NGRAM_N: int = 3  # 3-gram evaluation window
    NGRAM_WINDOW_TOKENS: int = 40  # Rolling token window for repetition inspection
    LOOP_ANOMALY_THRESHOLD: float = 0.70  # Anomaly score >= 0.70 triggers circuit breaker
    SIMILARITY_THRESHOLD: float = 0.85  # Levenshtein similarity >= 85% flags circular reasoning
    MIN_TOKENS_BEFORE_CHECK: int = 15  # Minimum tokens before anomaly evaluator begins scoring

    # Telemetry & Database
    DATABASE_PATH: str = "tokenshield_telemetry.db"

    # Circuit Breaker Policies
    ENABLE_HUMAN_CHECKPOINT: bool = False  # When True, halts and waits for Streamlit approval
    AUTO_INJECT_STEERING: bool = True  # Automatically injects system recovery turn on loop

    # ponytail: lean environment loader using pydantic-settings v2
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_config() -> TokenShieldConfig:
    """Return cached singleton configuration instance."""
    # ponytail: standard lru_cache eliminates redundant file/env reads
    return TokenShieldConfig()
