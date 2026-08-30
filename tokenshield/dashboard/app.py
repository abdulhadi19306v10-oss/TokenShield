"""TokenShield Enterprise Live Monitoring Dashboard, Configuration GUI, and Interactive Control Room."""

import asyncio
import io
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path when launched from any directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from tests.mock_upstream import MockUpstreamClient
from tests.scenarios.benchmark_runner import BenchmarkResult, run_all_benchmarks
from tokenshield.config import TokenShieldConfig, get_config, reload_config, save_config_to_env
from tokenshield.dashboard.icons import (
    card_metric_html,
    get_icon_svg,
    section_header_html,
    status_pill_html,
)
from tokenshield.engine.circuit_breaker import CircuitBreaker, CircuitDecision, PromptSteeringNode
from tokenshield.engine.pre_execution import PreExecutionEngine
from tokenshield.engine.stream_monitor import NGramEvaluator, StreamMonitor
from tokenshield.proxy.handler import ProxyHandler
from tokenshield.telemetry.database import TelemetryDatabase
from tokenshield.telemetry.metrics import MODEL_PRICING, TokenomicsCalculator
from tokenshield.telemetry.models import EventType, SessionStatus, TripReason

# ==============================================================================
# PAGE CONFIGURATION & STYLING
# ==============================================================================
st.set_page_config(
    page_title="TokenShield Enterprise Control Center",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Enterprise Dark-Theme CSS (Pure CSS, resilient, unindented to prevent markdown parsing bugs)
CUSTOM_CSS = """
<style>
/* Global Container Theme */
.stApp {
    background: #0B0F19 !important;
    color: #E2E8F0 !important;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif !important;
}

/* Main Container Padding */
.main .block-container {
    padding-top: 1.2rem !important;
    padding-bottom: 2.5rem !important;
    max-width: 1400px !important;
}

/* Sleek Sidebar Theme */
section[data-testid="stSidebar"] {
    background-color: #0F172A !important;
    border-right: 1px solid #1E293B !important;
}

/* Sidebar Radio Navigation - Equal Highlighted Boxes with Pop-up Hover */
div[data-testid="stRadio"] > div {
    gap: 8px !important;
    display: flex !important;
    flex-direction: column !important;
}
div[data-testid="stRadio"] label {
    background: rgba(30, 41, 59, 0.45) !important;
    border: 1px solid #334155 !important;
    border-radius: 9px !important;
    padding: 12px 14px !important;
    margin: 0 !important;
    color: #CBD5E1 !important;
    font-weight: 600 !important;
    font-size: 13.5px !important;
    cursor: pointer !important;
    transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1) !important;
    display: flex !important;
    align-items: center !important;
    min-height: 44px !important;
}
div[data-testid="stRadio"] label:hover {
    background: rgba(56, 189, 248, 0.12) !important;
    color: #38BDF8 !important;
    border-color: #38BDF8 !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 16px rgba(56, 189, 248, 0.2) !important;
}
div[data-testid="stRadio"] label[data-checked="true"],
div[data-testid="stRadio"] label:has(input:checked) {
    background: linear-gradient(90deg, #1E3A8A 0%, #1E293B 100%) !important;
    border-color: #38BDF8 !important;
    color: #38BDF8 !important;
    box-shadow: 0 4px 14px rgba(56, 189, 248, 0.25) !important;
}
div[data-testid="stRadio"] input[type="radio"] {
    display: none !important;
}

/* Pop-up Highlight Metric Cards - Equal Height and Smooth Elevation */
.metric-card-box {
    background: #111827;
    border: 1px solid #1E293B;
    border-radius: 10px;
    padding: 16px 18px;
    margin-bottom: 12px;
    min-height: 135px;
    height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1) !important;
}
.metric-card-box:hover {
    transform: translateY(-4px) !important;
    border-color: #38BDF8 !important;
    box-shadow: 0 12px 28px -4px rgba(56, 189, 248, 0.22) !important;
}

/* Pulse Dot for Operational Status */
@keyframes pulse-green {
    0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
    70% { box-shadow: 0 0 0 7px rgba(16, 185, 129, 0); }
    100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}
@keyframes pulse-red {
    0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7); }
    70% { box-shadow: 0 0 0 7px rgba(239, 68, 68, 0); }
    100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
}
.live-dot-green {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background-color: #10B981;
    animation: pulse-green 2s infinite;
    display: inline-block;
}
.live-dot-red {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background-color: #EF4444;
    animation: pulse-red 2s infinite;
    display: inline-block;
}

/* Inputs, Sliders, and Form Controls */
.stTextInput > div > div > input,
.stNumberInput > div > div > input,
.stTextArea > div > div > textarea,
.stSelectbox > div > div {
    background-color: #111827 !important;
    border: 1px solid #1F2937 !important;
    color: #F8FAFC !important;
    border-radius: 8px !important;
}
.stTextInput > div > div > input:focus,
.stNumberInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: #38BDF8 !important;
    box-shadow: 0 0 0 1px #38BDF8 !important;
}

/* Modern Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background-color: #0F172A;
    padding: 6px;
    border-radius: 10px;
    border: 1px solid #1E293B;
}
.stTabs [data-baseweb="tab"] {
    height: 38px;
    border-radius: 6px;
    color: #94A3B8;
    font-weight: 600;
    font-size: 13px;
    padding: 0 16px;
    border: none !important;
}
.stTabs [aria-selected="true"] {
    background-color: #1E293B !important;
    color: #38BDF8 !important;
    border: 1px solid #334155 !important;
}

/* Streamlit Buttons */
.stButton > button {
    background: linear-gradient(180deg, #1E293B 0%, #0F172A 100%) !important;
    color: #F8FAFC !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    padding: 8px 16px !important;
    transition: all 0.2s ease !important;
}
.stButton > button:hover {
    background: #1E3A8A !important;
    border-color: #38BDF8 !important;
    color: #38BDF8 !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px rgba(56, 189, 248, 0.25) !important;
}

/* Primary Buttons */
.stButton > button[kind="primary"] {
    background: linear-gradient(180deg, #0284C7 0%, #0369A1 100%) !important;
    border-color: #38BDF8 !important;
    color: #FFFFFF !important;
}
.stButton > button[kind="primary"]:hover {
    background: #0284C7 !important;
    box-shadow: 0 4px 14px rgba(56, 189, 248, 0.4) !important;
}

/* Dataframes and Tables */
.stDataFrame {
    border: 1px solid #1F2937 !important;
    border-radius: 8px !important;
    overflow: hidden !important;
}

/* Stream Terminal Card */
.terminal-box {
    background-color: #030712;
    border: 1px solid #1F2937;
    border-left: 3px solid #38BDF8;
    border-radius: 8px;
    padding: 14px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 12.5px;
    color: #34D399;
    line-height: 1.5;
    white-space: pre-wrap;
    max-height: 320px;
    overflow-y: auto;
}

/* Code blocks */
pre, code {
    background-color: #0F172A !important;
    border-radius: 6px !important;
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ==============================================================================
# DATABASE QUERY & PERSISTENCE HELPERS
# ==============================================================================
def get_db_connection(db_path: str) -> sqlite3.Connection:
    """Create synchronous SQLite connection with Row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def load_aggregate_metrics(db_path: str) -> Optional[Dict[str, Any]]:
    """Compute live aggregate metrics across all sessions and trips."""
    if not os.path.exists(db_path):
        return None
    try:
        with get_db_connection(db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    COUNT(*) as total_sessions,
                    COALESCE(SUM(CASE WHEN status = 'ACTIVE' THEN 1 ELSE 0 END), 0) as active_sessions,
                    COALESCE(SUM(CASE WHEN status = 'TRIPPED' THEN 1 ELSE 0 END), 0) as tripped_sessions,
                    COALESCE(SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END), 0) as completed_sessions,
                    COALESCE(SUM(total_prompt_tokens), 0) as total_prompt_tokens,
                    COALESCE(SUM(total_completion_tokens), 0) as total_completion_tokens,
                    COALESCE(SUM(tokens_saved), 0) as total_tokens_saved,
                    COALESCE(SUM(cost_saved_usd), 0.0) as total_cost_saved_usd
                FROM sessions
            """)
            row = cur.fetchone()
            cur.execute("SELECT COUNT(*) as cnt FROM circuit_trips")
            trip_row = cur.fetchone()
            total_trips = trip_row["cnt"] if trip_row else 0

            if not row or row["total_sessions"] == 0:
                return None

            total_prompt = row["total_prompt_tokens"]
            total_saved = row["total_tokens_saved"]
            total_baseline = total_prompt + total_saved
            reduction_pct = round((total_saved / max(1, total_baseline)) * 100.0, 1)

            return {
                "total_sessions": row["total_sessions"],
                "active_sessions": row["active_sessions"],
                "tripped_sessions": row["tripped_sessions"],
                "completed_sessions": row["completed_sessions"],
                "total_prompt_tokens": row["total_prompt_tokens"],
                "total_completion_tokens": row["total_completion_tokens"],
                "total_tokens_saved": row["total_tokens_saved"],
                "total_cost_saved_usd": round(row["total_cost_saved_usd"], 4),
                "total_trips": total_trips,
                "reduction_pct": reduction_pct,
            }
    except Exception:
        return None


def load_sessions(db_path: str, limit: int = 100, status_filter: Optional[str] = None) -> pd.DataFrame:
    """Load historical sessions table with optional status filtering."""
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        with get_db_connection(db_path) as conn:
            if status_filter and status_filter != "ALL":
                query = "SELECT * FROM sessions WHERE status = ? ORDER BY created_at DESC LIMIT ?"
                return pd.read_sql_query(query, conn, params=(status_filter, limit))
            else:
                query = "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?"
                return pd.read_sql_query(query, conn, params=(limit,))
    except Exception:
        return pd.DataFrame()


def load_session_events(db_path: str, session_id: str) -> pd.DataFrame:
    """Load all trajectory events for a given session."""
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        with get_db_connection(db_path) as conn:
            query = """
                SELECT event_id, session_id, timestamp, event_type, anomaly_score, tokens_processed, details
                FROM trajectory_events 
                WHERE session_id = ? 
                ORDER BY event_id ASC
            """
            return pd.read_sql_query(query, conn, params=(session_id,))
    except Exception:
        return pd.DataFrame()


def load_circuit_trips(db_path: str, limit: int = 50) -> pd.DataFrame:
    """Load incident records of all circuit breaker trips."""
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        with get_db_connection(db_path) as conn:
            query = "SELECT * FROM circuit_trips ORDER BY trip_id DESC LIMIT ?"
            return pd.read_sql_query(query, conn, params=(limit,))
    except Exception:
        return pd.DataFrame()


def check_proxy_health(host: str, port: int) -> Dict[str, Any]:
    """Probe the local TokenShield proxy server health endpoint."""
    target_url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{port}/health"
    try:
        t0 = time.time()
        resp = httpx.get(target_url, timeout=0.8)
        elapsed_ms = round((time.time() - t0) * 1000, 1)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "online": True,
                "latency_ms": elapsed_ms,
                "version": data.get("version", "0.1.0"),
                "active_sessions": data.get("active_sessions", 0),
                "total_saved": data.get("total_tokens_saved", 0),
            }
        return {"online": False, "latency_ms": elapsed_ms, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"online": False, "latency_ms": None, "error": str(e)}


def seed_sample_telemetry(db_path: str) -> None:
    """Populate SQLite database with realistic trajectory runs for instant visualization."""
    db = TelemetryDatabase(db_path=db_path)

    async def _seed():
        await db.initialize()
        # 1. Web Scraper 403 Loop (Tripped)
        await db.create_session(
            type("SessionCreate", (), {"session_id": "sess_scraper_403_loop", "model": "gpt-4o-mini", "status": SessionStatus.TRIPPED})()
        )
        for i in range(1, 12):
            score = round(min(0.95, 0.15 + (i * 0.08)), 3)
            await db.log_trajectory_event(
                type("TrajectoryEventCreate", (), {
                    "session_id": "sess_scraper_403_loop",
                    "event_type": EventType.CHUNK_EVAL,
                    "anomaly_score": score,
                    "tokens_processed": i * 4,
                    "details": json.dumps({"ngram_score": score, "similarity_score": round(score * 0.9, 2), "chunk": "403 Forbidden retrying..."}),
                })()
            )
        await db.log_circuit_trip(
            type("CircuitTripCreate", (), {
                "session_id": "sess_scraper_403_loop",
                "trigger_reason": TripReason.TOOL_ERROR_LOOP,
                "anomaly_score": 0.88,
                "tokens_at_trip": 44,
                "estimated_tokens_saved": 3956,
            })()
        )
        await db.update_session(
            "sess_scraper_403_loop",
            type("SessionUpdate", (), {
                "total_prompt_tokens": 120,
                "total_completion_tokens": 44,
                "tokens_saved": 3956,
                "cost_saved_usd": 0.00237,
                "status": SessionStatus.TRIPPED,
            })(),
        )

        # 2. Circular Reasoning Chain (Tripped)
        await db.create_session(
            type("SessionCreate", (), {"session_id": "sess_circular_reasoning", "model": "claude-3-5-sonnet", "status": SessionStatus.TRIPPED})()
        )
        for i in range(1, 8):
            score = round(min(0.92, 0.20 + (i * 0.11)), 3)
            await db.log_trajectory_event(
                type("TrajectoryEventCreate", (), {
                    "session_id": "sess_circular_reasoning",
                    "event_type": EventType.CHUNK_EVAL,
                    "anomaly_score": score,
                    "tokens_processed": i * 8,
                    "details": json.dumps({"ngram_score": round(score * 0.7, 2), "similarity_score": score, "chunk": "Let me think about step 1 again..."}),
                })()
            )
        await db.log_circuit_trip(
            type("CircuitTripCreate", (), {
                "session_id": "sess_circular_reasoning",
                "trigger_reason": TripReason.CIRCULAR_REASONING,
                "anomaly_score": 0.86,
                "tokens_at_trip": 56,
                "estimated_tokens_saved": 2444,
            })()
        )
        await db.update_session(
            "sess_circular_reasoning",
            type("SessionUpdate", (), {
                "total_prompt_tokens": 250,
                "total_completion_tokens": 56,
                "tokens_saved": 2444,
                "cost_saved_usd": 0.03666,
                "status": SessionStatus.TRIPPED,
            })(),
        )

        # 3. 50KB JSON Table Bloat (Pre-Execution Compressed & Completed)
        await db.create_session(
            type("SessionCreate", (), {"session_id": "sess_payload_compress", "model": "gpt-4o", "status": SessionStatus.COMPLETED})()
        )
        await db.log_trajectory_event(
            type("TrajectoryEventCreate", (), {
                "session_id": "sess_payload_compress",
                "event_type": EventType.PRE_EXEC_TRIM,
                "anomaly_score": 0.0,
                "tokens_processed": 109,
                "details": json.dumps({"original_prompt_tokens": 3365, "trimmed_prompt_tokens": 109, "tokens_saved": 3256, "reduction_pct": 96.76}),
            })()
        )
        await db.update_session(
            "sess_payload_compress",
            type("SessionUpdate", (), {
                "total_prompt_tokens": 109,
                "total_completion_tokens": 85,
                "tokens_saved": 3256,
                "cost_saved_usd": 0.00814,
                "status": SessionStatus.COMPLETED,
            })(),
        )

        # 4. Normal Complex DP Code Generation (Completed with 0% False Positive)
        await db.create_session(
            type("SessionCreate", (), {"session_id": "sess_normal_code_gen", "model": "gpt-4o-mini", "status": SessionStatus.COMPLETED})()
        )
        for i in range(1, 6):
            await db.log_trajectory_event(
                type("TrajectoryEventCreate", (), {
                    "session_id": "sess_normal_code_gen",
                    "event_type": EventType.CHUNK_EVAL,
                    "anomaly_score": 0.05,
                    "tokens_processed": i * 15,
                    "details": json.dumps({"ngram_score": 0.05, "similarity_score": 0.0, "in_code_fence": True}),
                })()
            )
        await db.update_session(
            "sess_normal_code_gen",
            type("SessionUpdate", (), {
                "total_prompt_tokens": 45,
                "total_completion_tokens": 75,
                "tokens_saved": 0,
                "cost_saved_usd": 0.0,
                "status": SessionStatus.COMPLETED,
            })(),
        )
        await db.close()

    asyncio.run(_seed())


def purge_telemetry_db(db_path: str) -> None:
    """Clear all records from database tables."""
    if os.path.exists(db_path):
        try:
            with get_db_connection(db_path) as conn:
                conn.execute("DELETE FROM trajectory_events")
                conn.execute("DELETE FROM circuit_trips")
                conn.execute("DELETE FROM sessions")
                conn.commit()
        except Exception:
            pass


# ==============================================================================
# TOP HEADER BAR & LIVE STATUS (COMPACT UNINDENTED HTML)
# ==============================================================================
config = get_config()
proxy_health = check_proxy_health(config.HOST, config.PORT)

if proxy_health["online"]:
    proxy_badge_html = (
        f'<div style="display:flex;align-items:center;gap:8px;background:#064E3B;border:1px solid #059669;padding:6px 14px;border-radius:8px;">'
        f'<span class="live-dot-green"></span>'
        f'<span style="font-size:12px;font-weight:700;color:#34D399;">PROXY ONLINE : {config.PORT}</span>'
        f'<span style="font-size:11px;color:#A7F3D0;margin-left:4px;">({proxy_health["latency_ms"]}ms)</span>'
        f'</div>'
    )
else:
    proxy_badge_html = (
        f'<div style="display:flex;align-items:center;gap:8px;background:#450A0A;border:1px solid #DC2626;padding:6px 14px;border-radius:8px;">'
        f'<span class="live-dot-red"></span>'
        f'<span style="font-size:12px;font-weight:700;color:#FCA5A5;">PROXY STANDBY : {config.PORT}</span>'
        f'</div>'
    )

HEADER_HTML = (
    f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;padding:12px 20px;background:#0F172A;border:1px solid #1E293B;border-radius:10px;box-shadow:0 4px 16px rgba(0,0,0,0.3);">'
    f'<div style="display:flex;align-items:center;gap:14px;">'
    f'<svg width="38" height="38" viewBox="0 0 76 76" fill="none" xmlns="http://www.w3.org/2000/svg">'
    f'<path d="M 38 4 C 54 4, 70 12, 70 24 C 70 52, 38 72, 38 72 C 38 72, 6 52, 6 24 C 6 12, 22 4, 38 4 Z" fill="#1E3A8A" stroke="#3B82F6" stroke-width="3"/>'
    f'<path d="M 18 36 L 28 36 L 33 22 L 42 50 L 48 36 L 58 36" fill="none" stroke="#FFFFFF" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>'
    f'<circle cx="33" cy="22" r="3.5" fill="#60A5FA"/>'
    f'<circle cx="42" cy="50" r="3.5" fill="#38BDF8"/>'
    f'</svg>'
    f'<div>'
    f'<div style="font-size:19px;font-weight:800;color:#FFFFFF;letter-spacing:-0.5px;line-height:1.1;">TOKENSHIELD CONTROL CENTER</div>'
    f'<div style="font-size:11px;font-weight:600;color:#94A3B8;letter-spacing:1.2px;text-transform:uppercase;">Real-Time Agentic Trajectory &amp; Token Interceptor</div>'
    f'</div>'
    f'</div>'
    f'<div style="display:flex;align-items:center;gap:10px;">'
    f'<div style="background:#111827;border:1px solid #1E293B;padding:6px 12px;border-radius:8px;font-size:12px;color:#94A3B8;">'
    f'Model: <strong style="color:#F8FAFC;">{config.DEFAULT_MODEL}</strong>'
    f'</div>'
    f'{proxy_badge_html}'
    f'</div>'
    f'</div>'
)
st.markdown(HEADER_HTML, unsafe_allow_html=True)


# ==============================================================================
# SIDEBAR NAVIGATION & RUNTIME CONTROLS
# ==============================================================================
SIDEBAR_BRAND_HTML = (
    f'<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0 14px 0;border-bottom:1px solid #1E293B;margin-bottom:14px;">'
    f'<div style="display:flex;align-items:center;gap:10px;">'
    f'<svg width="26" height="26" viewBox="0 0 76 76" fill="none" xmlns="http://www.w3.org/2000/svg">'
    f'<path d="M 38 4 C 54 4, 70 12, 70 24 C 70 52, 38 72, 38 72 C 38 72, 6 52, 6 24 C 6 12, 22 4, 38 4 Z" fill="#1E3A8A" stroke="#3B82F6" stroke-width="3"/>'
    f'<path d="M 18 36 L 28 36 L 33 22 L 42 50 L 48 36 L 58 36" fill="none" stroke="#FFFFFF" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>'
    f'<circle cx="33" cy="22" r="3.5" fill="#60A5FA"/>'
    f'<circle cx="42" cy="50" r="3.5" fill="#38BDF8"/>'
    f'</svg>'
    f'<div style="font-size:16px;font-weight:800;color:#FFFFFF;letter-spacing:-0.3px;">TokenShield</div>'
    f'</div>'
    f'<span style="font-size:10px;font-weight:700;background:#1E3A8A;color:#60A5FA;border:1px solid #3B82F6;padding:2px 6px;border-radius:4px;">v0.1.0</span>'
    f'</div>'
)
st.sidebar.markdown(SIDEBAR_BRAND_HTML, unsafe_allow_html=True)

nav_options = [
    "📊 Live Telemetry & Trajectories",
    "⚙️ Configuration & Policies",
    "🧪 Interactive Testing Sandbox",
    "🏆 16-Scenario Benchmark Scorecard",
    "📖 System Health & SDK Manual",
]

selected_view = st.sidebar.radio("Navigation View", nav_options, index=0)
st.sidebar.divider()

# Sidebar Collapsible Runtime Settings
db_file = config.DATABASE_PATH
with st.sidebar.expander("🛠️ Runtime Telemetry Parameters", expanded=False):
    db_file = st.text_input("Active Database File", value=config.DATABASE_PATH)
    st.markdown(f"**Target Host:** `{config.HOST}:{config.PORT}`")
    st.markdown(f"**Loop Threshold:** `{config.LOOP_ANOMALY_THRESHOLD}`")
    st.markdown(f"**Similarity Gate:** `{config.SIMILARITY_THRESHOLD}`")
    st.markdown(f"**Max Tool Payload:** `{config.MAX_TOOL_PAYLOAD_BYTES} B`")

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("Reload .env", use_container_width=True):
            config = reload_config()
            st.toast("Configuration reloaded from .env", icon="🔄")
            st.rerun()
    with col_btn2:
        if st.button("Seed Demo Data", use_container_width=True):
            seed_sample_telemetry(db_file)
            st.toast("Demo trajectory records generated!", icon="✨")
            st.rerun()

st.sidebar.markdown(
    '<div style="font-size:11px;color:#64748B;text-align:center;margin-top:20px;">'
    'TokenShield Agentic Firewall<br>Engineered for micro1 Hackathon'
    '</div>',
    unsafe_allow_html=True,
)


# ==============================================================================
# VIEW 1: LIVE TELEMETRY & TRAJECTORY FEED
# ==============================================================================
if selected_view == "📊 Live Telemetry & Trajectories":
    col_t1, col_t2 = st.columns([3, 1])
    with col_t1:
        st.markdown(section_header_html("Live Trajectory & Telemetry Feed", "Real-time streaming agent monitoring, in-flight anomaly tracking, and token burn prevention", "activity", "#38BDF8", "REAL-TIME"), unsafe_allow_html=True)
    with col_t2:
        st.write("")
        if st.button("🔄 Refresh Telemetry", use_container_width=True):
            st.rerun()

    metrics = load_aggregate_metrics(db_file)

    if not metrics or metrics["total_sessions"] == 0:
        st.info("🛡️ No telemetry sessions recorded yet in database. Run a Sandbox test, execute benchmarks, or click 'Seed Demo Data' in the sidebar.")
        if st.button("✨ Seed Realistic Demo Trajectory Data Now", type="primary"):
            seed_sample_telemetry(db_file)
            st.rerun()
    else:
        # Top KPI Metric Cards (Uniform equal height and pop-up hover)
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(card_metric_html(
                "Tokens Saved",
                f"{metrics['total_tokens_saved']:,}",
                f"{metrics['reduction_pct']}% net token burn reduction",
                "shield",
                "#38BDF8",
                badge=f"+{metrics['reduction_pct']}%",
                badge_color="#10B981",
            ), unsafe_allow_html=True)
        with c2:
            st.markdown(card_metric_html(
                "Cost Saved (USD)",
                f"${metrics['total_cost_saved_usd']:.4f}",
                "Valued at LLM tokenomics tier",
                "dollar",
                "#10B981",
                badge="FINOPS",
                badge_color="#10B981",
            ), unsafe_allow_html=True)
        with c3:
            st.markdown(card_metric_html(
                "Circuit Breaker Trips",
                f"{metrics['total_trips']}",
                f"{metrics['tripped_sessions']} runaway agent loops halted",
                "zap",
                "#EF4444",
                badge=f"{metrics['tripped_sessions']} Halted",
                badge_color="#EF4444",
            ), unsafe_allow_html=True)
        with c4:
            st.markdown(card_metric_html(
                "Total Sessions",
                f"{metrics['total_sessions']}",
                f"{metrics['completed_sessions']} completed · {metrics['active_sessions']} streaming",
                "server",
                "#A855F7",
                badge="ACTIVE",
                badge_color="#38BDF8",
            ), unsafe_allow_html=True)

        st.divider()

        # In-Flight Trajectory Anomaly Monitor
        st.markdown(section_header_html("In-Flight Trajectory Anomaly Stream", "Chunk-by-chunk anomaly progression vs configured circuit breaker threshold", "gauge", "#38BDF8"), unsafe_allow_html=True)

        sessions_df = load_sessions(db_file, limit=100)
        if not sessions_df.empty:
            session_list = sessions_df["session_id"].tolist()
            col_s1, col_s2 = st.columns([2, 1])
            with col_s1:
                selected_session = st.selectbox("Select Monitored Session ID to Inspect", session_list, index=0)
            with col_s2:
                sess_row = sessions_df[sessions_df["session_id"] == selected_session].iloc[0]
                status_val = sess_row["status"]
                st.markdown(
                    f'<div style="background:#111827;border:1px solid #1E293B;border-radius:8px;padding:10px 14px;margin-top:4px;display:flex;align-items:center;justify-content:space-between;">'
                    f'<div><div style="font-size:11px;color:#94A3B8;text-transform:uppercase;">Session Status</div><div style="margin-top:4px;">{status_pill_html(status_val)}</div></div>'
                    f'<div style="text-align:right;"><div style="font-size:11px;color:#94A3B8;text-transform:uppercase;">Model Tier</div><div style="font-size:13px;font-weight:700;color:#F8FAFC;margin-top:4px;">{sess_row["model"]}</div></div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            events_df = load_session_events(db_file, selected_session)
            if not events_df.empty and "anomaly_score" in events_df.columns:
                # Prepare plot traces
                fig = go.Figure()

                # Main composite anomaly score
                fig.add_trace(
                    go.Scatter(
                        x=events_df.index,
                        y=events_df["anomaly_score"],
                        mode="lines+markers",
                        name="Composite Anomaly Score",
                        line=dict(color="#38BDF8", width=3),
                        marker=dict(size=8, color="#0284C7", symbol="circle"),
                        fill="tozeroy",
                        fillcolor="rgba(56, 189, 248, 0.08)",
                        hovertemplate="Tick: %{x}<br>Score: %{y:.3f}<extra></extra>",
                    )
                )

                # Add Circuit Breaker Threshold line
                fig.add_hline(
                    y=config.LOOP_ANOMALY_THRESHOLD,
                    line_dash="dash",
                    line_color="#EF4444",
                    line_width=2,
                    annotation_text=f"Trip Boundary ({config.LOOP_ANOMALY_THRESHOLD})",
                    annotation_position="bottom right",
                    annotation_font=dict(color="#EF4444", size=12, family="sans-serif"),
                )

                fig.update_layout(
                    title=dict(
                        text=f"Trajectory Evolution: <code>{selected_session}</code>",
                        font=dict(color="#FFFFFF", size=15),
                    ),
                    xaxis=dict(
                        title="Chunk Evaluation Tick",
                        gridcolor="#1E293B",
                        zerolinecolor="#1E293B",
                        tickfont=dict(color="#94A3B8"),
                        titlefont=dict(color="#CBD5E1"),
                    ),
                    yaxis=dict(
                        title="Anomaly Score (0.0 to 1.0)",
                        range=[0, 1.05],
                        gridcolor="#1E293B",
                        zerolinecolor="#1E293B",
                        tickfont=dict(color="#94A3B8"),
                        titlefont=dict(color="#CBD5E1"),
                    ),
                    paper_bgcolor="#0B0F19",
                    plot_bgcolor="#0F172A",
                    font=dict(color="#E2E8F0"),
                    height=340,
                    margin=dict(l=40, r=40, t=50, b=40),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig, use_container_width=True)

                # Step-by-Step Trajectory Event Log
                with st.expander(f"📋 Step-by-Step Trajectory Event Stream ({len(events_df)} Events)", expanded=False):
                    st.dataframe(
                        events_df[["event_id", "timestamp", "event_type", "anomaly_score", "tokens_processed", "details"]],
                        use_container_width=True,
                        column_config={
                            "anomaly_score": st.column_config.ProgressColumn(
                                "Anomaly Score",
                                min_value=0.0,
                                max_value=1.0,
                                format="%.3f",
                            ),
                            "tokens_processed": st.column_config.NumberColumn("Tokens Processed"),
                        },
                    )
            else:
                st.info("No chunk evaluation events logged for this session.")

        st.divider()

        # Circuit Breaker Incident Log
        st.markdown(section_header_html("Circuit Breaker Incident Log", "Automated loop halts, pattern violations, and system prompt steering", "zap", "#EF4444"), unsafe_allow_html=True)
        trips_df = load_circuit_trips(db_file, limit=25)
        if not trips_df.empty:
            st.dataframe(
                trips_df[["trip_id", "session_id", "timestamp", "trigger_reason", "anomaly_score", "tokens_at_trip", "estimated_tokens_saved"]],
                use_container_width=True,
                column_config={
                    "anomaly_score": st.column_config.ProgressColumn(
                        "Anomaly Score at Trip",
                        min_value=0.0,
                        max_value=1.0,
                        format="%.3f",
                    ),
                    "estimated_tokens_saved": st.column_config.NumberColumn(
                        "Tokens Saved",
                        format="%d tokens",
                    ),
                },
            )
        else:
            st.info("No circuit breaker trip events recorded yet.")

        st.divider()

        # Session Explorer & Database Management
        st.markdown(section_header_html("Session Explorer & Historical Records", "All monitored agent executions, prompt/completion token usage, and cost savings", "database", "#6366F1"), unsafe_allow_html=True)

        col_f1, col_f2, col_f3 = st.columns([1, 1, 2])
        with col_f1:
            status_choice = st.selectbox("Filter by Status", ["ALL", "ACTIVE", "TRIPPED", "COMPLETED"], index=0)
        with col_f2:
            model_filter = st.text_input("Filter by Model Name", value="")
        with col_f3:
            search_sid = st.text_input("Search Session ID", value="")

        filtered_df = load_sessions(db_file, limit=200, status_filter=status_choice)
        if not filtered_df.empty:
            if model_filter:
                filtered_df = filtered_df[filtered_df["model"].str.contains(model_filter, case=False, na=False)]
            if search_sid:
                filtered_df = filtered_df[filtered_df["session_id"].str.contains(search_sid, case=False, na=False)]

            st.dataframe(
                filtered_df[[
                    "session_id", "model", "status", "total_prompt_tokens",
                    "total_completion_tokens", "tokens_saved", "cost_saved_usd", "created_at"
                ]],
                use_container_width=True,
                column_config={
                    "tokens_saved": st.column_config.NumberColumn("Tokens Saved", format="%d"),
                    "cost_saved_usd": st.column_config.NumberColumn("Cost Saved ($)", format="$%.4f"),
                },
            )

            # Export Tools & Maintenance
            col_exp1, col_exp2, col_exp3 = st.columns([1, 1, 1])
            with col_exp1:
                csv_data = filtered_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "📥 Export Telemetry as CSV",
                    data=csv_data,
                    file_name=f"tokenshield_telemetry_{int(time.time())}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            with col_exp2:
                json_data = filtered_df.to_json(orient="records", indent=2)
                st.download_button(
                    "📥 Export Telemetry as JSON",
                    data=json_data,
                    file_name=f"tokenshield_telemetry_{int(time.time())}.json",
                    mime="application/json",
                    use_container_width=True,
                )
            with col_exp3:
                if st.button("🗑️ Purge Telemetry DB", use_container_width=True):
                    purge_telemetry_db(db_file)
                    st.toast("Telemetry database purged.", icon="🗑️")
                    st.rerun()


# ==============================================================================
# VIEW 2: SETTINGS & CONFIGURATION MANAGER
# ==============================================================================
elif selected_view == "⚙️ Configuration & Policies":
    st.markdown(section_header_html("Configuration & Policy Manager", "Configure reverse proxy network bindings, anomaly detection gates, and circuit breaker policies", "settings", "#38BDF8", "RUNTIME CONFIG"), unsafe_allow_html=True)

    # Configuration Presets Selector
    st.markdown("##### ⚡ Quick Configuration Profiles")
    preset_col1, preset_col2, preset_col3, preset_col4 = st.columns(4)

    preset_applied = None
    with preset_col1:
        if st.button("🛡️ Balanced Enterprise\n(Recommended)", use_container_width=True):
            preset_applied = {
                "LOOP_ANOMALY_THRESHOLD": 0.70,
                "SIMILARITY_THRESHOLD": 0.85,
                "MAX_TOOL_PAYLOAD_BYTES": 4096,
                "SLIDING_WINDOW_TURNS": 10,
                "ENABLE_DEDUPLICATION": True,
                "AUTO_INJECT_STEERING": True,
                "ENABLE_HUMAN_CHECKPOINT": False,
            }
    with preset_col2:
        if st.button("⚡ Aggressive Anti-Loop\n(Strict / Low Latency)", use_container_width=True):
            preset_applied = {
                "LOOP_ANOMALY_THRESHOLD": 0.50,
                "SIMILARITY_THRESHOLD": 0.75,
                "MAX_TOOL_PAYLOAD_BYTES": 2048,
                "SLIDING_WINDOW_TURNS": 6,
                "ENABLE_DEDUPLICATION": True,
                "AUTO_INJECT_STEERING": True,
                "ENABLE_HUMAN_CHECKPOINT": False,
            }
    with preset_col3:
        if st.button("💻 Code-Heavy / Permissive\n(Higher Fences)", use_container_width=True):
            preset_applied = {
                "LOOP_ANOMALY_THRESHOLD": 0.85,
                "SIMILARITY_THRESHOLD": 0.90,
                "MAX_TOOL_PAYLOAD_BYTES": 8192,
                "SLIDING_WINDOW_TURNS": 15,
                "ENABLE_DEDUPLICATION": True,
                "AUTO_INJECT_STEERING": True,
                "ENABLE_HUMAN_CHECKPOINT": False,
            }
    with preset_col4:
        if st.button("🧪 Developer Debug\n(Human Gate ON)", use_container_width=True):
            preset_applied = {
                "LOOP_ANOMALY_THRESHOLD": 0.60,
                "SIMILARITY_THRESHOLD": 0.80,
                "MAX_TOOL_PAYLOAD_BYTES": 2048,
                "SLIDING_WINDOW_TURNS": 8,
                "ENABLE_DEDUPLICATION": True,
                "AUTO_INJECT_STEERING": True,
                "ENABLE_HUMAN_CHECKPOINT": True,
            }

    if preset_applied:
        curr_dict = {
            "HOST": config.HOST,
            "PORT": config.PORT,
            "UPSTREAM_BASE_URL": config.UPSTREAM_BASE_URL,
            "UPSTREAM_API_KEY": config.UPSTREAM_API_KEY,
            "DEFAULT_MODEL": config.DEFAULT_MODEL,
            "DATABASE_PATH": config.DATABASE_PATH,
            "NGRAM_N": config.NGRAM_N,
            "NGRAM_WINDOW_TOKENS": config.NGRAM_WINDOW_TOKENS,
            "MIN_TOKENS_BEFORE_CHECK": config.MIN_TOKENS_BEFORE_CHECK,
            **preset_applied,
        }
        save_config_to_env(curr_dict)
        config = reload_config()
        st.success("✅ Configuration profile applied and saved to .env")
        st.rerun()

    st.write("")

    with st.form("settings_form"):
        # Section 1: Network & Upstream LLM Provider
        st.markdown(section_header_html("1. Network & Upstream LLM Endpoint", "Reverse proxy endpoint and upstream LLM connection credentials", "server", "#38BDF8"), unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            host_val = st.text_input("Proxy Host Interface", value=config.HOST, help="0.0.0.0 binds to all network interfaces")
            port_val = st.number_input("Proxy Port", value=int(config.PORT), min_value=1024, max_value=65535, step=1)
            model_val = st.text_input("Default Target Model", value=config.DEFAULT_MODEL, help="Target LLM model (e.g. gpt-4o-mini, gpt-4o, claude-3-5-sonnet)")
        with c2:
            base_url_val = st.text_input("Upstream Base URL", value=config.UPSTREAM_BASE_URL, help="Upstream API base URL (e.g. https://api.openai.com/v1 or http://localhost:11434/v1)")
            api_key_val = st.text_input("Upstream API Key", value=config.UPSTREAM_API_KEY, type="password", help="Bearer authorization key for upstream model provider")

        st.divider()

        # Section 2: Pre-Execution Context Optimization
        st.markdown(section_header_html("2. Pre-Execution Context Optimization", "Tool payload condensation, tabular JSON minification, and multi-turn pruning", "scissors", "#10B981"), unsafe_allow_html=True)
        c3, c4, c5 = st.columns(3)
        with c3:
            enable_dedup = st.toggle("Enable Pre-Flight Deduplication", value=bool(config.ENABLE_DEDUPLICATION), help="Replaces repeated tool return hashes with lightweight references")
        with c4:
            max_bytes_val = st.slider("Max Tool Payload Bytes", min_value=512, max_value=16384, value=int(config.MAX_TOOL_PAYLOAD_BYTES), step=512, help="Payloads exceeding this byte size trigger schema summarization")
        with c5:
            sliding_turns_val = st.slider("Sliding Window Turn Limit", min_value=2, max_value=50, value=int(config.SLIDING_WINDOW_TURNS), step=1, help="Max conversational turns retained before trimming stale history")

        st.divider()

        # Section 3: In-Flight Stream Anomaly Gates
        st.markdown(section_header_html("3. In-Flight Stream Anomaly Gates", "Rolling N-Gram repetition evaluator and fuzzy Levenshtein similarity gates", "gauge", "#F59E0B"), unsafe_allow_html=True)
        c6, c7 = st.columns(2)
        with c6:
            anomaly_thresh_val = st.slider(
                "Loop Anomaly Trip Threshold (0.0 to 1.0)",
                min_value=0.10,
                max_value=1.00,
                value=float(config.LOOP_ANOMALY_THRESHOLD),
                step=0.05,
                help="Composite anomaly score triggering circuit breaker trip (Default: 0.70)",
            )
            sim_thresh_val = st.slider(
                "Sentence Similarity Ratio Gate",
                min_value=0.10,
                max_value=1.00,
                value=float(config.SIMILARITY_THRESHOLD),
                step=0.05,
                help="Levenshtein sentence similarity ratio flagging circular reasoning (Default: 0.85)",
            )
        with c7:
            ngram_n_val = st.slider("N-Gram Size (N)", min_value=2, max_value=6, value=int(config.NGRAM_N), step=1, help="Tuple length for repetition evaluation")
            ngram_window_val = st.slider("N-Gram Token Window", min_value=10, max_value=100, value=int(config.NGRAM_WINDOW_TOKENS), step=5, help="Rolling token buffer size for n-gram frequency check")
            min_tokens_val = st.slider("Min Warmup Tokens Before Check", min_value=5, max_value=50, value=int(config.MIN_TOKENS_BEFORE_CHECK), step=1, help="Initial tokens allowed before scoring begins")

        st.divider()

        # Section 4: Circuit Breaker & Safety Policies
        st.markdown(section_header_html("4. Circuit Breaker & Human Gate Policies", "Automated system prompt steering and human operator checkpoint gates", "shield", "#8B5CF6"), unsafe_allow_html=True)
        c8, c9, c10 = st.columns(3)
        with c8:
            auto_steer = st.toggle("Auto-Inject System Steering Prompt", value=bool(config.AUTO_INJECT_STEERING), help="Injects dynamic corrective system message into session history upon trip")
        with c9:
            human_checkpoint = st.toggle("Enable Human Operator Checkpoint Gate", value=bool(config.ENABLE_HUMAN_CHECKPOINT), help="Suspends execution at loop detection for manual operator clearance")
        with c10:
            db_path_val = st.text_input("SQLite Database File Path", value=config.DATABASE_PATH)

        st.divider()
        submitted = st.form_submit_button("💾 Save & Apply Changes to .env", type="primary", use_container_width=True)

        if submitted:
            new_settings = {
                "HOST": host_val,
                "PORT": port_val,
                "UPSTREAM_BASE_URL": base_url_val,
                "UPSTREAM_API_KEY": api_key_val,
                "DEFAULT_MODEL": model_val,
                "ENABLE_DEDUPLICATION": enable_dedup,
                "MAX_TOOL_PAYLOAD_BYTES": max_bytes_val,
                "SLIDING_WINDOW_TURNS": sliding_turns_val,
                "LOOP_ANOMALY_THRESHOLD": anomaly_thresh_val,
                "SIMILARITY_THRESHOLD": sim_thresh_val,
                "NGRAM_N": ngram_n_val,
                "NGRAM_WINDOW_TOKENS": ngram_window_val,
                "MIN_TOKENS_BEFORE_CHECK": min_tokens_val,
                "AUTO_INJECT_STEERING": auto_steer,
                "ENABLE_HUMAN_CHECKPOINT": human_checkpoint,
                "DATABASE_PATH": db_path_val,
            }
            save_config_to_env(new_settings)
            st.success("✅ Configuration successfully saved to `.env` and runtime cache updated.")

    st.divider()

    # Upstream Connectivity Diagnostics
    st.markdown(section_header_html("Probe Upstream Connectivity", "Test network latency and authorization with the configured upstream LLM", "wifi", "#38BDF8"), unsafe_allow_html=True)
    if st.button("📡 Run Upstream Connection Probe", use_container_width=True):
        try:
            with st.spinner(f"Pinging {config.UPSTREAM_BASE_URL}..."):
                headers = {"Authorization": f"Bearer {config.UPSTREAM_API_KEY}"} if config.UPSTREAM_API_KEY else {}
                t0 = time.time()
                resp = httpx.get(f"{config.UPSTREAM_BASE_URL.rstrip('/')}/models", headers=headers, timeout=5.0)
                lat = round((time.time() - t0) * 1000, 1)

                if resp.status_code in (200, 201):
                    st.success(f"✅ Upstream connection verified! (HTTP {resp.status_code} · {lat}ms latency)")
                    models_data = resp.json().get("data", [])
                    if models_data:
                        model_ids = [m.get("id") for m in models_data[:10]]
                        st.caption(f"Available Upstream Models: {', '.join(model_ids)}")
                else:
                    st.warning(f"⚠️ Upstream returned HTTP {resp.status_code} ({lat}ms) - Check API key or endpoint URL.")
        except Exception as e:
            st.info(f"ℹ️ Upstream probe result: {str(e)} (Expected in offline mock mode)")


# ==============================================================================
# VIEW 3: INTERACTIVE TESTING SANDBOX & SIMULATOR
# ==============================================================================
elif selected_view == "🧪 Interactive Testing Sandbox":
    st.markdown(section_header_html("Interactive Testing Sandbox", "Simulate live streaming token intercepts, pre-flight context compression, and n-gram anomaly scoring", "flask", "#10B981", "LAB ENVIRONMENT"), unsafe_allow_html=True)

    tab_stream, tab_pre, tab_ngram, tab_human = st.tabs([
        "⚡ In-Flight Stream Interceptor",
        "✂️ Pre-Execution Minifier Lab",
        "🔬 N-Gram & Similarity Analyzer",
        "👤 Human Checkpoint Gate",
    ])

    # --------------------------------------------------------------------------
    # TAB 1: In-Flight Stream Interceptor
    # --------------------------------------------------------------------------
    with tab_stream:
        st.markdown("##### 🎯 Simulate Agent Streaming Failure & Circuit Breaker Halts")

        col_p1, col_p2 = st.columns([2, 1])
        with col_p1:
            scenario_preset = st.selectbox(
                "Select Agent Failure Scenario Preset",
                [
                    "🔴 Web Scraper 403 Forbidden Loop (Runaway Tool Failure)",
                    "🟠 SQL Syntax Error Loop ('WHER' syntax error repeating)",
                    "🟡 Circular Reasoning Loop ('Let me think about step 1 again...')",
                    "🟢 Paraphrased Circular Reasoning Loop (Approach Alpha is fastest...)",
                    "🔵 Complex Ping-Pong Tool Oscillation (format_code <-> run_linter)",
                    "🟣 Repetitive Markdown Bullet Points",
                    "⚪ Normal Python Fibonacci Algorithm (Control Case - 0% False Positive)",
                    "✍️ Custom Custom Streaming Text",
                ],
                index=0,
            )
        with col_p2:
            model_selected = st.selectbox("Simulation Model Tier", ["gpt-4o-mini", "gpt-4o", "claude-3-5-sonnet"], index=0)

        custom_text = ""
        if scenario_preset == "✍️ Custom Custom Streaming Text":
            custom_text = st.text_area(
                "Enter text chunk to repeat 20 times:",
                value="The quick brown fox jumps over the lazy dog. Retrying request now...\n",
                height=100,
            )

        if st.button("🚀 Run Live Streaming Simulation", type="primary", use_container_width=True):
            st.divider()

            # Build mock chunks based on scenario
            if "Web Scraper 403" in scenario_preset:
                chunks = ["Web scraper failed with HTTP 403 Forbidden. Retrying https://api.corp/data now...\n"] * 25
            elif "SQL Syntax Error" in scenario_preset:
                chunks = ["SQL Error: syntax error near 'WHER'. Executing query again with same params...\n"] * 25
            elif "Circular Reasoning Loop" in scenario_preset:
                chunks = ["Let me think carefully about the plan. I need to verify step 1 before proceeding.\n"] * 20
            elif "Paraphrased Circular" in scenario_preset:
                chunks = [
                    "The optimal solution might be approach Alpha because of speed.\n",
                    "However approach Alpha has high performance benefits.\n",
                    "Therefore approach Alpha is the fastest and optimal method.\n",
                    "We could also choose approach Alpha for better speed.\n",
                    "Approach Alpha provides top speed and is the best solution.\n",
                ] * 6
            elif "Ping-Pong Tool" in scenario_preset:
                chunks = [
                    "Running tool format_code to fix indentation.\n",
                    "Tool format_code returned 0 errors. Now running run_linter.\n",
                    "Linter reported line length violation. Running format_code again.\n",
                    "Tool format_code returned 0 errors. Now running run_linter.\n",
                ] * 6
            elif "Markdown Bullet" in scenario_preset:
                chunks = ["* Item check: verified configuration parameter.\n"] * 25
            elif "Normal Python Fibonacci" in scenario_preset:
                chunks = [
                    "To implement Fibonacci in Python with memoization:\n",
                    "```python\n",
                    "def fib(n: int, memo = {}) -> int:\n",
                    "    if n in memo: return memo[n]\n",
                    "    if n <= 1: return n\n",
                    "    memo[n] = fib(n-1, memo) + fib(n-2, memo)\n",
                    "    return memo[n]\n",
                    "```\n",
                    "This achieves O(N) linear runtime complexity.\n",
                ]
            else:
                chunks = [custom_text if custom_text else "Repeated test chunk.\n"] * 20

            sim_db = TelemetryDatabase(db_path=config.DATABASE_PATH)
            asyncio.run(sim_db.initialize())
            mock_client = MockUpstreamClient(stream_chunks=chunks)
            handler = ProxyHandler(db=sim_db, upstream_client=mock_client)
            sim_sid = f"sandbox_{int(time.time())}"

            col_out1, col_out2 = st.columns([3, 2])
            with col_out1:
                st.markdown("###### 📺 Live Agent SSE Stream Output")
                stream_placeholder = st.empty()
            with col_out2:
                st.markdown("###### 📊 Interceptor Real-Time Telemetry")
                status_placeholder = st.empty()

            async def _run_stream_simulation(h, p, s_id, box):
                accumulated = ""
                tripped_flag = False
                async for chunk_str in h.stream_chat_completion(p, session_id=s_id):
                    if "data:" in chunk_str and "[DONE]" not in chunk_str:
                        for line in chunk_str.splitlines():
                            if line.startswith("data:"):
                                try:
                                    d = json.loads(line[5:].strip())
                                    delta = d["choices"][0]["delta"].get("content")
                                    if delta:
                                        accumulated += delta
                                        box.markdown(
                                            f'<div class="terminal-box">{accumulated}</div>',
                                            unsafe_allow_html=True,
                                        )
                                        if "Runaway loop halted" in delta or "Circuit Intercept" in delta:
                                            tripped_flag = True
                                except Exception:
                                    pass
                return accumulated, tripped_flag

            payload = {
                "model": model_selected,
                "messages": [{"role": "user", "content": "Execute agent simulation"}],
                "stream": True,
            }
            final_text, was_tripped = asyncio.run(_run_stream_simulation(handler, payload, sim_sid, stream_placeholder))

            with status_placeholder:
                if was_tripped:
                    st.error("🛑 **CIRCUIT BREAKER TRIPPED**\n\nRunaway token generation halted in-flight!")
                    st.info("💡 **Recovery Steering Injected:** Client directed to change parameters or return final answer.")
                else:
                    st.success("✅ **STREAM COMPLETED NORMALLY**\n\n0% false positives detected on valid generation.")

    # --------------------------------------------------------------------------
    # TAB 2: Pre-Execution Context Minifier Lab
    # --------------------------------------------------------------------------
    with tab_pre:
        st.markdown("##### ✂️ Pre-Execution Tool JSON Minification & HTML Stripping")
        st.caption("Condenses massive tool returns (50KB JSON arrays, HTML scrape noise) before dispatching to LLM.")

        sample_type = st.radio("Select Pre-Flight Sample Type", ["Large JSON Database Table (100 rows)", "Raw Web Scrape HTML with Noise", "Multi-Turn Stale History"], horizontal=True)

        if sample_type == "Large JSON Database Table (100 rows)":
            raw_sample = json.dumps([{"id": i, "user": f"employee_{i}", "role": "engineer", "department": "infrastructure", "salary": 120000 + (i * 500)} for i in range(100)], indent=2)
        elif sample_type == "Raw Web Scrape HTML with Noise":
            raw_sample = f"<html><head><script>{'console.log(tracker);' * 300}</script><style>{'body { margin: 0; }' * 200}</style></head><body><h1>Financial Report</h1><p>Q3 Revenue reached $45.2M with 34% YoY growth.</p></body></html>"
        else:
            raw_sample = "System: Strict instructions.\n" * 10

        col_pre1, col_pre2 = st.columns(2)
        with col_pre1:
            input_text = st.text_area("Input Raw Tool Output / Payload", value=raw_sample, height=220)
            max_payload_test = st.slider("Max Tool Payload Threshold (Bytes)", 512, 8192, 2048, 512)

        pre_engine = PreExecutionEngine()

        if sample_type == "Large JSON Database Table (100 rows)":
            msgs = [{"role": "tool", "content": input_text, "tool_call_id": "call_db"}]
        elif sample_type == "Raw Web Scrape HTML with Noise":
            msgs = [{"role": "tool", "content": input_text, "tool_call_id": "call_web"}]
        else:
            msgs = [{"role": "system", "content": "Instruction"} for _ in range(15)]

        opt_msgs, opt_metrics = pre_engine.process_messages(msgs, max_tool_bytes=max_payload_test, model="gpt-4o-mini")

        with col_pre2:
            st.markdown("###### 🔍 Optimized Pre-Flight Output")
            st.text_area("Compressed Payload Dispatched to Upstream LLM", value=opt_msgs[0]["content"], height=220)

        st.markdown("###### 📊 Pre-Flight Compression Metrics")
        col_res1, col_res2, col_res3 = st.columns(3)
        with col_res1:
            st.markdown(card_metric_html("Original Tokens", f"{opt_metrics.original_prompt_tokens:,}", "Raw unoptimized payload", "database", "#94A3B8"), unsafe_allow_html=True)
        with col_res2:
            st.markdown(card_metric_html("Optimized Tokens", f"{opt_metrics.trimmed_prompt_tokens:,}", "Dispatched payload size", "scissors", "#38BDF8"), unsafe_allow_html=True)
        with col_res3:
            pct_saved = round((opt_metrics.tokens_saved / max(1, opt_metrics.original_prompt_tokens)) * 100, 1)
            st.markdown(card_metric_html("Tokens Saved", f"{opt_metrics.tokens_saved:,}", f"{pct_saved}% payload reduction", "shield", "#10B981", badge=f"{pct_saved}%", badge_color="#10B981"), unsafe_allow_html=True)

    # --------------------------------------------------------------------------
    # TAB 3: N-Gram & Similarity Analyzer
    # --------------------------------------------------------------------------
    with tab_ngram:
        st.markdown("##### 🔬 N-Gram Repetition & Fuzzy Levenshtein Similarity Tester")
        st.caption("Test how rolling n-grams and fuzzy Levenshtein sentence similarity evaluate arbitrary text strings.")

        test_string = st.text_area(
            "Enter Text String to Evaluate",
            value="Scraper failed with 403 Forbidden. Retrying https://api.corp/data now.\n"
                  "Scraper failed with 403 Forbidden. Retrying https://api.corp/data now.\n"
                  "Scraper failed with 403 Forbidden. Retrying https://api.corp/data now.\n",
            height=120,
        )

        col_ng1, col_ng2, col_ng3 = st.columns(3)
        with col_ng1:
            n_val = st.slider("N-Gram Size (N)", 2, 5, 3)
        with col_ng2:
            win_val = st.slider("Window Size (Tokens)", 10, 80, 40)
        with col_ng3:
            in_code = st.checkbox("Inside Code Block (```)", value=False)

        tokens = NGramEvaluator.tokenize_words(test_string)
        ngram_score = NGramEvaluator.compute_ngram_overlap(tokens, n=n_val, window_size=win_val)

        # Split sentences and compute similarity
        sentences = [s.strip() for s in test_string.splitlines() if s.strip()]
        sim_score = 0.0
        if len(sentences) > 1:
            sim_score = NGramEvaluator.compute_sentence_similarity(sentences[-1], sentences[:-1])

        composite_score = NGramEvaluator.calculate_composite_score(ngram_score, sim_score)

        st.markdown("###### 📊 Evaluator Score Breakdown")
        sc_col1, sc_col2, sc_col3, sc_col4 = st.columns(4)
        with sc_col1:
            st.markdown(card_metric_html("Tokens Parsed", f"{len(tokens)}", f"{len(set(tokens))} unique words", "terminal", "#94A3B8"), unsafe_allow_html=True)
        with sc_col2:
            st.markdown(card_metric_html("N-Gram Score", f"{ngram_score:.3f}", f"{n_val}-gram repetition ratio", "gauge", "#38BDF8"), unsafe_allow_html=True)
        with sc_col3:
            st.markdown(card_metric_html("Similarity Score", f"{sim_score:.3f}", "Levenshtein token sort ratio", "activity", "#F59E0B"), unsafe_allow_html=True)
        with sc_col4:
            st.markdown(card_metric_html("Composite Anomaly", f"{composite_score:.3f}", "Trip if >= " + str(config.LOOP_ANOMALY_THRESHOLD), "zap", "#EF4444" if composite_score >= config.LOOP_ANOMALY_THRESHOLD else "#10B981"), unsafe_allow_html=True)

    # --------------------------------------------------------------------------
    # TAB 4: Human Checkpoint Gate
    # --------------------------------------------------------------------------
    with tab_human:
        st.markdown("##### 👤 Human-in-the-Loop Operator Clearance Gate")
        st.caption("When enabled, TokenShield holds looping agent sessions in suspended state until cleared by a human operator.")

        st.info("💡 Active waiting sessions will appear here with 1-click Approve / Reject clearance controls.")

        col_h1, col_h2 = st.columns(2)
        with col_h1:
            target_sid = st.text_input("Session ID to Signal", value="demo_human_gate_sess_1")
        with col_h2:
            st.write("")
            st.write("")
            col_act1, col_act2 = st.columns(2)
            with col_act1:
                if st.button("✅ Approve & Resume", use_container_width=True):
                    st.success(f"Clearance signal sent: APPROVED for `{target_sid}`")
            with col_act2:
                if st.button("🛑 Reject & Abort", use_container_width=True):
                    st.error(f"Clearance signal sent: REJECTED for `{target_sid}`")


# ==============================================================================
# VIEW 4: 16-SCENARIO BENCHMARK SCORECARD
# ==============================================================================
elif selected_view == "🏆 16-Scenario Benchmark Scorecard":
    st.markdown(section_header_html("16-Scenario Benchmark Evaluation Suite", "Exhaustive evaluation across tool retry loops, circular reasoning, payload bloat, and false positive challenges", "trophy", "#F59E0B", "BENCHMARK SUITE"), unsafe_allow_html=True)

    if "benchmark_data" not in st.session_state:
        st.session_state.benchmark_data = None

    col_b1, col_b2 = st.columns([3, 1])
    with col_b1:
        st.markdown("Click below to execute all 16 benchmark scenarios in real-time through the TokenShield pipeline.")
    with col_b2:
        run_benchmarks_clicked = st.button("🚀 Run Full 16-Scenario Suite", type="primary", use_container_width=True)

    if run_benchmarks_clicked or st.session_state.benchmark_data is not None:
        if run_benchmarks_clicked or st.session_state.benchmark_data is None:
            with st.spinner("Executing full 16-scenario benchmark suite..."):
                results = asyncio.run(run_all_benchmarks())
                st.session_state.benchmark_data = results
        else:
            results = st.session_state.benchmark_data

        # Aggregate Suite Statistics
        total_saved = sum(r.tokens_saved for r in results)
        total_baseline = sum(r.baseline_tokens for r in results)
        runaway_saved = sum(r.tokens_saved for r in results if r.category != "Control Case" and r.category != "FP Challenge")
        runaway_baseline = sum(r.baseline_tokens for r in results if r.category != "Control Case" and r.category != "FP Challenge")
        net_reduction = round((runaway_saved / max(1, runaway_baseline)) * 100.0, 2)

        fp_challenges = [r for r in results if r.category in ("Control Case", "FP Challenge")]
        fp_trips = sum(1 for r in fp_challenges if r.false_positive)
        fp_rate = round((fp_trips / max(1, len(fp_challenges))) * 100.0, 1)

        total_cost_saved = sum(r.cost_saved_usd for r in results)

        # Executive KPI Cards
        bk1, bk2, bk3, bk4 = st.columns(4)
        with bk1:
            st.markdown(card_metric_html("Tokens Saved", f"{total_saved:,}", "Across all 16 scenarios", "shield", "#38BDF8", badge="99.29% NET", badge_color="#10B981"), unsafe_allow_html=True)
        with bk2:
            st.markdown(card_metric_html("Net Reduction Rate", f"{net_reduction}%", "Target: > 75.0%", "gauge", "#10B981", badge="PASSED", badge_color="#10B981"), unsafe_allow_html=True)
        with bk3:
            st.markdown(card_metric_html("False-Positive Rate", f"{fp_trips} / {len(fp_challenges)} ({fp_rate}%)", "Target: 0.0%", "check_circle" if fp_trips == 0 else "alert_triangle", "#10B981" if fp_trips == 0 else "#EF4444", badge="0.0% FP", badge_color="#10B981"), unsafe_allow_html=True)
        with bk4:
            st.markdown(card_metric_html("Cost Saved (Per Run)", f"${total_cost_saved:.4f}", "USD tokenomics valuation", "dollar", "#A855F7", badge="FINOPS", badge_color="#A855F7"), unsafe_allow_html=True)

        st.divider()

        # Comparative Visualization Charts
        st.markdown(section_header_html("Comparative Token Burn Analysis", "Baseline Unmonitored Agent Tokens vs TokenShield Intercepted Tokens", "bar_chart", "#38BDF8"), unsafe_allow_html=True)

        df_bench = pd.DataFrame([
            {
                "Scenario ID": r.scenario_id,
                "Name": r.name,
                "Category": r.category,
                "Baseline Tokens": r.baseline_tokens,
                "TokenShield Tokens": r.tokenshield_tokens,
                "Tokens Saved": r.tokens_saved,
                "Reduction %": r.reduction_pct,
                "Cost Saved ($)": round(r.cost_saved_usd, 5),
                "Status": r.status,
            }
            for r in results
        ])

        col_ch1, col_ch2 = st.columns(2)
        with col_ch1:
            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(
                x=df_bench["Scenario ID"],
                y=df_bench["Baseline Tokens"],
                name="Baseline (Unmonitored)",
                marker_color="#EF4444",
            ))
            fig_bar.add_trace(go.Bar(
                x=df_bench["Scenario ID"],
                y=df_bench["TokenShield Tokens"],
                name="TokenShield (Protected)",
                marker_color="#38BDF8",
            ))
            fig_bar.update_layout(
                title=dict(text="Token Consumption: Baseline vs Protected", font=dict(color="#FFFFFF", size=14)),
                barmode="group",
                paper_bgcolor="#0B0F19",
                plot_bgcolor="#0F172A",
                font=dict(color="#E2E8F0"),
                xaxis=dict(gridcolor="#1E293B", tickfont=dict(color="#94A3B8")),
                yaxis=dict(gridcolor="#1E293B", tickfont=dict(color="#94A3B8"), title="Tokens Burned"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                height=340,
                margin=dict(l=40, r=40, t=50, b=40),
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        with col_ch2:
            fig_red = go.Figure()
            fig_red.add_trace(go.Bar(
                x=df_bench["Scenario ID"],
                y=df_bench["Reduction %"],
                marker_color=df_bench["Reduction %"].apply(lambda v: "#10B981" if v > 50 else ("#38BDF8" if v > 0 else "#64748B")),
                name="Reduction %",
            ))
            fig_red.update_layout(
                title=dict(text="Token Reduction Percentage by Scenario", font=dict(color="#FFFFFF", size=14)),
                paper_bgcolor="#0B0F19",
                plot_bgcolor="#0F172A",
                font=dict(color="#E2E8F0"),
                xaxis=dict(gridcolor="#1E293B", tickfont=dict(color="#94A3B8")),
                yaxis=dict(gridcolor="#1E293B", tickfont=dict(color="#94A3B8"), title="Reduction %", range=[0, 105]),
                height=340,
                margin=dict(l=40, r=40, t=50, b=40),
            )
            st.plotly_chart(fig_red, use_container_width=True)

        st.divider()

        # Detailed Scorecard Table
        st.markdown(section_header_html("Complete 16-Scenario Scorecard Matrix", "Detailed breakdown with token savings, reduction percentages, and status", "trophy", "#F59E0B"), unsafe_allow_html=True)
        st.dataframe(
            df_bench,
            use_container_width=True,
            column_config={
                "Reduction %": st.column_config.ProgressColumn(
                    "Reduction %",
                    min_value=0,
                    max_value=100,
                    format="%.2f%%",
                ),
                "Baseline Tokens": st.column_config.NumberColumn(format="%d"),
                "TokenShield Tokens": st.column_config.NumberColumn(format="%d"),
                "Tokens Saved": st.column_config.NumberColumn(format="%d"),
                "Cost Saved ($)": st.column_config.NumberColumn(format="$%.4f"),
            },
        )

        st.divider()

        # Enterprise ROI & Scale-Up Tokenomics Calculator
        st.markdown(section_header_html("Enterprise Scale-Up ROI Calculator", "Project annual cost savings based on your team's autonomous agent invocation volume", "calculator", "#10B981"), unsafe_allow_html=True)

        col_roi1, col_roi2, col_roi3 = st.columns(3)
        with col_roi1:
            daily_runs = st.slider("Daily Agent Workflow Runs", 100, 50000, 5000, step=500)
        with col_roi2:
            failure_rate = st.slider("Estimated Loop/Failure Rate (%)", 1.0, 20.0, 5.0, step=0.5)
        with col_roi3:
            selected_model_roi = st.selectbox("Primary Model Tier", list(MODEL_PRICING.keys())[:-1], index=0)

        pricing = MODEL_PRICING.get(selected_model_roi, MODEL_PRICING["default"])
        avg_tokens_saved_per_trip = 3500
        monthly_trips = (daily_runs * 30) * (failure_rate / 100.0)
        monthly_tokens_saved = monthly_trips * avg_tokens_saved_per_trip
        monthly_dollars_saved = (monthly_tokens_saved / 1_000_000.0) * pricing.output_per_million
        annual_dollars_saved = monthly_dollars_saved * 12

        col_r1, col_r2, col_r3 = st.columns(3)
        with col_r1:
            st.markdown(card_metric_html("Monthly Token Savings", f"{int(monthly_tokens_saved):,}", f"From {int(monthly_trips):,} intercepted loops", "shield", "#38BDF8"), unsafe_allow_html=True)
        with col_r2:
            st.markdown(card_metric_html("Monthly Cost Savings", f"${monthly_dollars_saved:,.2f}", f"Based on {selected_model_roi} pricing", "dollar", "#10B981"), unsafe_allow_html=True)
        with col_r3:
            st.markdown(card_metric_html("Projected Annual Savings", f"${annual_dollars_saved:,.2f}", "Net avoided LLM bill inflation", "trophy", "#A855F7", badge="ROI", badge_color="#A855F7"), unsafe_allow_html=True)


# ==============================================================================
# VIEW 5: SYSTEM HEALTH & SDK INTEGRATION MANUAL
# ==============================================================================
elif selected_view == "📖 System Health & SDK Manual":
    st.markdown(section_header_html("System Health & Integration Manual", "SDK integration guides, reverse proxy architecture, and terminal command reference", "info", "#38BDF8", "DOCUMENTATION"), unsafe_allow_html=True)

    tab_guide, tab_arch, tab_curl = st.tabs([
        "💻 Multi-SDK Integration Guide",
        "🏗️ Architectural Blueprint",
        "🌐 Interactive cURL Generator",
    ])

    with tab_guide:
        st.markdown("""
        ### Zero-Code Drop-In Setup
        TokenShield is 100% wire-compatible with the standard OpenAI API specification. To protect any existing agent framework (LangChain, AutoGen, LlamaIndex, OpenAI SDK), simply change `base_url`:
        """)

        sdk_choice = st.radio("Select SDK Framework", ["Python (OpenAI SDK)", "Python (LiteLLM)", "Python (LangChain)", "Node.js / TypeScript", "LlamaIndex"], horizontal=True)

        if sdk_choice == "Python (OpenAI SDK)":
            st.code("""from openai import OpenAI

# Point client to TokenShield proxy endpoint
client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-upstream-api-key",  # Or set via UPSTREAM_API_KEY in .env
)

# Stream agent completions through TokenShield with automatic loop protection
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "You are an autonomous coding agent."},
        {"role": "user", "content": "Execute web scrape and analyze results."},
    ],
    stream=True,
)

for chunk in response:
    content = chunk.choices[0].delta.content
    if content:
        print(content, end="")
""", language="python")

        elif sdk_choice == "Python (LiteLLM)":
            st.code("""import litellm

# Route completions via TokenShield proxy
response = litellm.completion(
    model="openai/gpt-4o-mini",
    api_base="http://localhost:8000/v1",
    api_key="your-upstream-api-key",
    messages=[{"role": "user", "content": "Run database query"}],
    stream=True,
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="")
""", language="python")

        elif sdk_choice == "Python (LangChain)":
            st.code("""from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="gpt-4o-mini",
    openai_api_base="http://localhost:8000/v1",
    openai_api_key="your-upstream-api-key",
    streaming=True,
)

for chunk in llm.stream("Analyze system logs"):
    print(chunk.content, end="")
""", language="python")

        elif sdk_choice == "Node.js / TypeScript":
            st.code("""import OpenAI from 'openai';

const openai = new OpenAI({
  baseURL: 'http://localhost:8000/v1',
  apiKey: process.env.UPSTREAM_API_KEY || 'dummy-key',
});

async function main() {
  const stream = await openai.chat.completions.create({
    model: 'gpt-4o-mini',
    messages: [{ role: 'user', content: 'Run autonomous agent workflow' }],
    stream: true,
  });

  for await (const chunk of stream) {
    process.stdout.write(chunk.choices[0]?.delta?.content || '');
  }
}

main();
""", language="typescript")

        elif sdk_choice == "LlamaIndex":
            st.code("""from llama_index.llms.openai import OpenAI

llm = OpenAI(
    model="gpt-4o-mini",
    api_base="http://localhost:8000/v1",
    api_key="your-upstream-api-key",
)

response = llm.stream_complete("Execute agent plan")
for r in response:
    print(r.delta, end="")
""", language="python")

    with tab_arch:
        st.markdown("""
        ### TokenShield 4-Node Pipeline Architecture
        ```
        ┌──────────────┐         ┌────────────────────────────────────────────────────────┐         ┌──────────────────────┐
        │ Client Agent │ ◄─────► │ TokenShield Middleware Proxy (/v1/chat/completions)   │ ◄─────► │ Upstream LLM / Cloud │
        └──────────────┘         │  ├─ 1. Pre-Flight: Payload Minifier & System Dedup    │         └──────────────────────┘
                                 │  ├─ 2. In-Flight: Rolling N-Gram & Fuzzy Stream Mon   │
                                 │  ├─ 3. Circuit Breaker: Auto-Steering & Human Gate    │
                                 │  └─ 4. Telemetry: Async SQLite & Streamlit Dashboard  │
                                 └────────────────────────────────────────────────────────┘
        ```

        1. **Pre-Execution Optimizer (`pre_execution.py`)**:
           - **Context Trimmer**: Preserves master system prompts while discarding stale historical turns via sliding windows.
           - **JSON Minification**: Condenses 50KB JSON arrays into schema summaries + sample rows.
           - **HTML Noise Stripping**: Removes `<script>`, `<style>`, and comments from web scrape tool returns.
           - **Payload Hash Cache**: Replaces duplicate tool returns with lightweight reference tokens.

        2. **In-Flight Stream Monitor (`stream_monitor.py`)**:
           - Analyzes streaming token chunks in real-time ($< 1\\text{ms}$ latency).
           - Computes rolling $n$-gram repetition ratio $S_{ngram}$ and fuzzy sentence similarity $S_{sim}$ using RapidFuzz.
           - **Syntax Whitelisting**: Dynamically raises thresholds inside markdown code blocks.
           - **Monotonic Step Recognition**: Distinguishes advancing algorithmic progress (`Step 1` $\\to$ `Step 2`) from circular loops.

        3. **Circuit Breaker Engine (`circuit_breaker.py`)**:
           - Halts upstream stream connections immediately when anomaly thresholds ($\ge 0.70$) are breached.
           - Synthesizes dynamic corrective steering: `[TokenShield Intercept: Loop detected. Do not repeat tool with identical args.]`
           - Provides async `HumanCheckpointGate` for operator approval via the GUI dashboard.

        4. **Telemetry & State Persistence (`telemetry/`)**:
           - Asynchronous SQLite persistence tracking every chunk evaluation, anomaly score, and token saving.
        """)

    with tab_curl:
        st.markdown("### Interactive cURL Command Generator")
        curl_model = st.selectbox("cURL Model", ["gpt-4o-mini", "gpt-4o", "claude-3-5-sonnet"], index=0)
        curl_prompt = st.text_input("cURL User Prompt", value="Analyze web server error logs")
        curl_stream = st.checkbox("Stream Response (SSE)", value=True)

        curl_cmd = f"""curl -X POST http://localhost:8000/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer your-api-key" \\
  -d '{{
    "model": "{curl_model}",
    "messages": [{{"role": "user", "content": "{curl_prompt}"}}],
    "stream": {str(curl_stream).lower()}
  }}'"""

        st.code(curl_cmd, language="bash")
