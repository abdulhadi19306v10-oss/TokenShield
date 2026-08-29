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


def reload_config() -> TokenShieldConfig:
    """Clear cache and reload configuration from disk/env."""
    get_config.cache_clear()
    return get_config()


def save_config_to_env(updates: dict, env_path: str = ".env") -> bool:
    """Save dictionary of configuration keys to .env file."""
    # ponytail: direct file write updates .env without heavy dotenv dependencies
    lines = [
        "# TokenShield Runtime Configuration",
        f"HOST={updates.get('HOST', '0.0.0.0')}",
        f"PORT={updates.get('PORT', 8000)}",
        f"UPSTREAM_BASE_URL={updates.get('UPSTREAM_BASE_URL', 'https://api.openai.com/v1')}",
        f"UPSTREAM_API_KEY={updates.get('UPSTREAM_API_KEY', '')}",
        f"DEFAULT_MODEL={updates.get('DEFAULT_MODEL', 'gpt-4o-mini')}",
        "",
        "# Pre-Execution Thresholds",
        f"MAX_TOOL_PAYLOAD_BYTES={updates.get('MAX_TOOL_PAYLOAD_BYTES', 4096)}",
        f"SLIDING_WINDOW_TURNS={updates.get('SLIDING_WINDOW_TURNS', 10)}",
        f"ENABLE_DEDUPLICATION={str(updates.get('ENABLE_DEDUPLICATION', True)).lower()}",
        "",
        "# In-Flight Streaming & Anomaly Thresholds",
        f"NGRAM_N={updates.get('NGRAM_N', 3)}",
        f"NGRAM_WINDOW_TOKENS={updates.get('NGRAM_WINDOW_TOKENS', 40)}",
        f"LOOP_ANOMALY_THRESHOLD={updates.get('LOOP_ANOMALY_THRESHOLD', 0.70)}",
        f"SIMILARITY_THRESHOLD={updates.get('SIMILARITY_THRESHOLD', 0.85)}",
        f"MIN_TOKENS_BEFORE_CHECK={updates.get('MIN_TOKENS_BEFORE_CHECK', 15)}",
        "",
        "# Telemetry & Database",
        f"DATABASE_PATH={updates.get('DATABASE_PATH', 'tokenshield_telemetry.db')}",
        "",
        "# Circuit Breaker Policies",
        f"ENABLE_HUMAN_CHECKPOINT={str(updates.get('ENABLE_HUMAN_CHECKPOINT', False)).lower()}",
        f"AUTO_INJECT_STEERING={str(updates.get('AUTO_INJECT_STEERING', True)).lower()}",
    ]
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    reload_config()
    return True
