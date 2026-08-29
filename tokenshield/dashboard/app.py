"""TokenShield Live Monitoring Dashboard, Configuration GUI, and Interactive Control Room."""

import asyncio
import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional
import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tests.mock_upstream import MockUpstreamClient
from tests.scenarios.benchmark_runner import run_all_benchmarks
from tokenshield.config import TokenShieldConfig, get_config, reload_config, save_config_to_env
from tokenshield.dashboard.icons import (
    card_metric_html,
    get_icon_svg,
    section_header_html,
)
from tokenshield.engine.pre_execution import PreExecutionEngine
from tokenshield.proxy.handler import ProxyHandler
from tokenshield.telemetry.database import TelemetryDatabase
from tokenshield.telemetry.metrics import TokenomicsCalculator
from tokenshield.telemetry.models import SessionStatus

# Page Configuration
st.set_page_config(
    page_title="TokenShield Control Center",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Enterprise Dark-Theme CSS
CUSTOM_CSS = """
<style>
    /* Global Typography & Background Adjustments */
    .main {
        background-color: #0B0F19;
    }
    h1, h2, h3, h4 {
        color: #F8FAFC !important;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }
    
    /* Sleek Tab Container */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #111827;
        padding: 8px 12px;
        border-radius: 8px;
        border: 1px solid #1F2937;
    }
    .stTabs [data-baseweb="tab"] {
        height: 42px;
        white-space: pre-wrap;
        background-color: transparent;
        border-radius: 6px;
        color: #94A3B8;
        font-weight: 600;
        font-size: 14px;
        padding: 0 16px;
        border: none !important;
    }
    .stTabs [aria-selected="true"] {
        background-color: #1E293B !important;
        color: #38BDF8 !important;
        border-bottom: 2px solid #38BDF8 !important;
    }

    /* Buttons */
    .stButton > button {
        border-radius: 6px;
        font-weight: 600;
        letter-spacing: 0.2px;
        transition: all 0.15s ease-in-out;
    }
    
    /* Code & JSON blocks */
    .stCodeBlock, .stJson {
        border: 1px solid #1F2937 !important;
        border-radius: 8px !important;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# --- Database Query Helpers ---
def get_db_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def load_aggregate_metrics(db_path: str):
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

            return {
                "total_sessions": row["total_sessions"],
                "active_sessions": row["active_sessions"],
                "tripped_sessions": row["tripped_sessions"],
                "total_prompt_tokens": row["total_prompt_tokens"],
                "total_completion_tokens": row["total_completion_tokens"],
                "total_tokens_saved": row["total_tokens_saved"],
                "total_cost_saved_usd": round(row["total_cost_saved_usd"], 4),
                "total_trips": total_trips,
            }
    except Exception:
        return None


def load_sessions(db_path: str, limit: int = 100) -> pd.DataFrame:
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        with get_db_connection(db_path) as conn:
            query = "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?"
            return pd.read_sql_query(query, conn, params=(limit,))
    except Exception:
        return pd.DataFrame()


def load_session_events(db_path: str, session_id: str) -> pd.DataFrame:
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
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        with get_db_connection(db_path) as conn:
            query = "SELECT * FROM circuit_trips ORDER BY trip_id DESC LIMIT ?"
            return pd.read_sql_query(query, conn, params=(limit,))
    except Exception:
        return pd.DataFrame()


# --- Branding Header Component ---
LOGO_SVG_HTML = """
<div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; padding: 14px 20px; background: #0F172A; border: 1px solid #1E293B; border-radius: 8px;">
    <div style="display: flex; align-items: center; gap: 16px;">
        <svg width="42" height="42" viewBox="0 0 76 76" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M 38 4 C 54 4, 70 12, 70 24 C 70 52, 38 72, 38 72 C 38 72, 6 52, 6 24 C 6 12, 22 4, 38 4 Z" fill="#1E3A8A" stroke="#3B82F6" stroke-width="3" />
            <path d="M 18 36 L 28 36 L 33 22 L 42 50 L 48 36 L 58 36" fill="none" stroke="#FFFFFF" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" />
            <circle cx="33" cy="22" r="3.5" fill="#60A5FA" />
            <circle cx="42" cy="50" r="3.5" fill="#38BDF8" />
        </svg>
        <div>
            <div style="font-size: 22px; font-weight: 800; color: #FFFFFF; letter-spacing: -0.5px; line-height: 1.1;">TOKENSHIELD</div>
            <div style="font-size: 11px; font-weight: 600; color: #94A3B8; letter-spacing: 1.5px; text-transform: uppercase;">Real-Time Agentic Trajectory &amp; Token Interceptor</div>
        </div>
    </div>
    <div style="display: flex; align-items: center; gap: 8px; background: #1E293B; padding: 6px 12px; border-radius: 6px; border: 1px solid #334155;">
        <div style="width: 8px; height: 8px; border-radius: 50%; background: #10B981;"></div>
        <span style="font-size: 12px; font-weight: 600; color: #E2E8F0;">Operational (Port 8000)</span>
    </div>
</div>
"""

# --- Sidebar ---
config = get_config()

st.sidebar.markdown(LOGO_SVG_HTML, unsafe_allow_html=True)
db_file = st.sidebar.text_input("Active Database Path", value=config.DATABASE_PATH)
auto_refresh = st.sidebar.checkbox("Auto-refresh (5s)", value=False)
if auto_refresh:
    time.sleep(5)
    st.rerun()

st.sidebar.divider()
st.sidebar.markdown(section_header_html("Runtime Parameters", "Active proxy configurations", "sliders", "#38BDF8"), unsafe_allow_html=True)
st.sidebar.markdown(f"**Proxy Address:** `{config.HOST}:{config.PORT}`")
st.sidebar.markdown(f"**Target Model:** `{config.DEFAULT_MODEL}`")
st.sidebar.markdown(f"**Anomaly Threshold:** `{config.LOOP_ANOMALY_THRESHOLD}`")
st.sidebar.markdown(f"**Similarity Ratio:** `{config.SIMILARITY_THRESHOLD}`")

st.sidebar.divider()
if st.sidebar.button("Reload Settings from .env", use_container_width=True):
    config = reload_config()
    st.sidebar.success("Configuration reloaded successfully.")


# --- Main Tabbed Navigation ---
tab_telemetry, tab_settings, tab_sandbox, tab_benchmarks, tab_about = st.tabs([
    "Live Telemetry",
    "Configuration & Settings",
    "Testing Sandbox",
    "Benchmark Scorecard",
    "System Health & Guide",
])


# ==============================================================================
# TAB 1: LIVE TELEMETRY & CONTROL ROOM
# ==============================================================================
with tab_telemetry:
    st.markdown(LOGO_SVG_HTML, unsafe_allow_html=True)
    st.markdown(section_header_html("Live Telemetry & Trajectory Feed", "Real-time monitoring of agent streaming trajectories and circuit intercepts", "activity", "#38BDF8"), unsafe_allow_html=True)

    metrics = load_aggregate_metrics(db_file)

    if not metrics or metrics["total_sessions"] == 0:
        st.info("No telemetry sessions recorded yet. Start proxy requests, run a sandbox test, or launch benchmarks.")
    else:
        # Top KPI Cards with vector icons
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(card_metric_html("Tokens Saved", f"{metrics['total_tokens_saved']:,}", "From loops & payload compression", "shield", "#38BDF8"), unsafe_allow_html=True)
        with c2:
            st.markdown(card_metric_html("Estimated Cost Saved", f"${metrics['total_cost_saved_usd']:.4f}", "USD tokenomics valuation", "dollar", "#10B981"), unsafe_allow_html=True)
        with c3:
            st.markdown(card_metric_html("Circuit Intercepts", f"{metrics['total_trips']}", f"{metrics['tripped_sessions']} runaway sessions halted", "zap", "#EF4444"), unsafe_allow_html=True)
        with c4:
            st.markdown(card_metric_html("Monitored Sessions", f"{metrics['total_sessions']}", f"{metrics['active_sessions']} currently streaming", "server", "#A855F7"), unsafe_allow_html=True)

        st.divider()

        # Real-time Trajectory Anomaly Monitor
        st.markdown(section_header_html("In-Flight Trajectory Anomaly Stream", "Chunk-by-chunk anomaly progression vs circuit breaker threshold", "gauge", "#38BDF8"), unsafe_allow_html=True)
        sessions_df = load_sessions(db_file, limit=50)

        if not sessions_df.empty:
            session_list = sessions_df["session_id"].tolist()
            selected_session = st.selectbox("Select Monitored Session ID", session_list, index=0)

            events_df = load_session_events(db_file, selected_session)
            if not events_df.empty and "anomaly_score" in events_df.columns:
                fig = go.Figure()

                fig.add_trace(
                    go.Scatter(
                        x=events_df.index,
                        y=events_df["anomaly_score"],
                        mode="lines+markers",
                        name="Loop Anomaly Score",
                        line=dict(color="#38BDF8", width=2.5),
                        marker=dict(size=7, color="#0284C7"),
                        fill="tozeroy",
                        fillcolor="rgba(56, 189, 248, 0.08)",
                    )
                )

                fig.add_hline(
                    y=config.LOOP_ANOMALY_THRESHOLD,
                    line_dash="dash",
                    line_color="#EF4444",
                    annotation_text=f"Trip Threshold ({config.LOOP_ANOMALY_THRESHOLD})",
                    annotation_position="bottom right",
                    annotation_font=dict(color="#EF4444", size=12),
                )

                fig.update_layout(
                    title=f"Trajectory Anomaly Progression: {selected_session}",
                    xaxis_title="Chunk Evaluation Tick",
                    yaxis_title="Anomaly Score (0.0 to 1.0)",
                    yaxis=dict(range=[0, 1.05], gridcolor="#1E293B"),
                    xaxis=dict(gridcolor="#1E293B"),
                    paper_bgcolor="#0F172A",
                    plot_bgcolor="#0F172A",
                    font=dict(color="#E2E8F0"),
                    height=360,
                    margin=dict(l=40, r=40, t=50, b=40),
                )
                st.plotly_chart(fig, use_container_width=True)

                with st.expander("View Raw Trajectory Event Telemetry"):
                    st.dataframe(events_df, use_container_width=True)
            else:
                st.info("No chunk evaluation events logged for this session.")

        st.divider()

        # Circuit Breaker Trips Log
        st.markdown(section_header_html("Circuit Breaker Incident Log", "Recent automated halts and prompt injections", "zap", "#EF4444"), unsafe_allow_html=True)
        trips_df = load_circuit_trips(db_file, limit=20)
        if not trips_df.empty:
            st.dataframe(
                trips_df[["trip_id", "session_id", "timestamp", "trigger_reason", "anomaly_score", "tokens_at_trip", "estimated_tokens_saved"]],
                use_container_width=True,
            )
        else:
            st.write("No circuit breaker trip events recorded.")

        st.divider()

        # Session Explorer
        st.markdown(section_header_html("Session History & Tokenomics", "Detailed session metadata and prompt/completion tokens", "database", "#6366F1"), unsafe_allow_html=True)
        if not sessions_df.empty:
            st.dataframe(
                sessions_df[[
                    "session_id", "model", "status", "total_prompt_tokens",
                    "total_completion_tokens", "tokens_saved", "cost_saved_usd", "created_at"
                ]],
                use_container_width=True,
            )


# ==============================================================================
# TAB 2: SETTINGS & CONFIGURATION GUI
# ==============================================================================
with tab_settings:
    st.markdown(section_header_html("Configuration & Settings Manager", "Modify TokenShield runtime parameters, anomaly thresholds, and circuit breaker policies", "settings", "#38BDF8"), unsafe_allow_html=True)

    with st.form("settings_form"):
        st.markdown(section_header_html("Network & Upstream Provider", "Reverse proxy endpoint and upstream LLM connection", "server", "#38BDF8"), unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            host_val = st.text_input("Proxy Host", value=config.HOST, help="Network interface to bind (0.0.0.0 for all interfaces)")
            port_val = st.number_input("Proxy Port", value=int(config.PORT), min_value=1024, max_value=65535)
            model_val = st.text_input("Default Model", value=config.DEFAULT_MODEL, help="Target LLM model name (e.g. gpt-4o-mini, llama3.1, claude-3-5-sonnet)")
        with c2:
            base_url_val = st.text_input("Upstream Base URL", value=config.UPSTREAM_BASE_URL, help="Upstream API base URL (e.g. https://api.openai.com/v1 or http://localhost:11434/v1)")
            api_key_val = st.text_input("Upstream API Key", value=config.UPSTREAM_API_KEY, type="password", help="Authorization Bearer key for upstream LLM")

        st.divider()
        st.markdown(section_header_html("Pre-Execution Optimization", "Payload minification, JSON schema summarization, and turn pruning", "scissors", "#10B981"), unsafe_allow_html=True)
        c3, c4, c5 = st.columns(3)
        with c3:
            enable_dedup = st.toggle("Enable Pre-Flight Deduplication", value=bool(config.ENABLE_DEDUPLICATION))
        with c4:
            max_bytes_val = st.slider("Max Tool Payload Bytes", min_value=512, max_value=16384, value=int(config.MAX_TOOL_PAYLOAD_BYTES), step=512, help="Payloads exceeding this size trigger schema summarization")
        with c5:
            sliding_turns_val = st.slider("Sliding Window Turns", min_value=2, max_value=50, value=int(config.SLIDING_WINDOW_TURNS), step=1, help="Max conversational turns retained before trimming stale history")

        st.divider()
        st.markdown(section_header_html("In-Flight Stream Anomaly Thresholds", "Rolling N-gram evaluation and fuzzy Levenshtein similarity gates", "gauge", "#F59E0B"), unsafe_allow_html=True)
        c6, c7 = st.columns(2)
        with c6:
            anomaly_thresh_val = st.slider(
                "Loop Anomaly Threshold",
                min_value=0.10,
                max_value=1.00,
                value=float(config.LOOP_ANOMALY_THRESHOLD),
                step=0.05,
                help="Composite anomaly score (0.0 - 1.0) that triggers circuit breaker trip (Default: 0.70)",
            )
            sim_thresh_val = st.slider(
                "Sentence Similarity Threshold",
                min_value=0.10,
                max_value=1.00,
                value=float(config.SIMILARITY_THRESHOLD),
                step=0.05,
                help="Levenshtein sentence similarity ratio flagging circular reasoning (Default: 0.85)",
            )
        with c7:
            ngram_n_val = st.slider("N-Gram Size (N)", min_value=2, max_value=6, value=int(config.NGRAM_N), step=1)
            ngram_window_val = st.slider("N-Gram Window Tokens", min_value=10, max_value=100, value=int(config.NGRAM_WINDOW_TOKENS), step=5)
            min_tokens_val = st.slider("Min Warmup Tokens Before Check", min_value=5, max_value=50, value=int(config.MIN_TOKENS_BEFORE_CHECK), step=1)

        st.divider()
        st.markdown(section_header_html("Circuit Breaker & Database Policies", "System recovery steering and human-in-the-loop checkpoint gates", "shield", "#8B5CF6"), unsafe_allow_html=True)
        c8, c9, c10 = st.columns(3)
        with c8:
            auto_steer = st.toggle("Auto-Inject System Steering", value=bool(config.AUTO_INJECT_STEERING), help="Injects corrective recovery guidance when loops trip")
        with c9:
            human_checkpoint = st.toggle("Enable Human Checkpoint Gate", value=bool(config.ENABLE_HUMAN_CHECKPOINT), help="Suspends execution at loop detection for manual operator clearance")
        with c10:
            db_path_val = st.text_input("Database File Path", value=config.DATABASE_PATH)

        st.divider()
        submitted = st.form_submit_button("Save & Apply to .env File", use_container_width=True)

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
            st.success("Configuration saved to .env and runtime cache updated.")

    st.divider()
    st.markdown(section_header_html("Probe Upstream Connectivity", "Test connectivity to configured LLM endpoint", "activity", "#38BDF8"), unsafe_allow_html=True)
    if st.button("Probe Upstream Connection"):
        try:
            with st.spinner("Pinging upstream endpoint..."):
                resp = httpx.get(f"{config.UPSTREAM_BASE_URL.rstrip('/')}/models", headers={"Authorization": f"Bearer {config.UPSTREAM_API_KEY}"} if config.UPSTREAM_API_KEY else {}, timeout=5.0)
                st.info(f"Upstream responded with status HTTP {resp.status_code}")
        except Exception as e:
            st.warning(f"Connection probe status: {str(e)} (Expected in offline mock mode)")


# ==============================================================================
# TAB 3: INTERACTIVE SANDBOX & PROMPT SIMULATOR
# ==============================================================================
with tab_sandbox:
    st.markdown(section_header_html("Interactive Testing Sandbox", "Simulate live streaming payloads, tool retry loops, and pre-flight compression", "flask", "#10B981"), unsafe_allow_html=True)

    preset = st.selectbox(
        "Select Simulation Scenario Preset",
        [
            "Infinite Web Scraper 403 Loop (Runaway Tool Failure)",
            "Circular Analytical Reasoning Loop (Repeating Thought Chain)",
            "50KB Tabular JSON Bloat (Pre-Flight Compression)",
            "Normal Complex Code Generation (0% False-Positive Test)",
        ]
    )

    if st.button("Run Simulation", use_container_width=True):
        st.write("---")
        with st.spinner("Executing simulation..."):
            sim_db = TelemetryDatabase(db_path=config.DATABASE_PATH)
            asyncio.run(sim_db.initialize())

            if preset == "Infinite Web Scraper 403 Loop (Runaway Tool Failure)":
                chunks = ["Scraper failed with HTTP 403 Forbidden. Retrying https://api.corp/data now...\n"] * 20
                mock = MockUpstreamClient(stream_chunks=chunks)
                handler = ProxyHandler(db=sim_db, upstream_client=mock)
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "user", "content": "Fetch data from https://api.corp/data"},
                        {"role": "tool", "content": '{"error": "403 Forbidden"}', "tool_call_id": "c1"},
                    ],
                    "stream": True,
                }
            elif preset == "Circular Analytical Reasoning Loop (Repeating Thought Chain)":
                chunks = ["Let me think carefully about step 1. I need to verify step 1 before proceeding.\n"] * 15
                mock = MockUpstreamClient(stream_chunks=chunks)
                handler = ProxyHandler(db=sim_db, upstream_client=mock)
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "Analyze step 1"}],
                    "stream": True,
                }
            elif preset == "50KB Tabular JSON Bloat (Pre-Flight Compression)":
                large_table = [{"id": i, "user": f"user_{i}", "data": "x" * 100} for i in range(100)]
                pre = PreExecutionEngine()
                msgs = [{"role": "tool", "content": json.dumps(large_table), "tool_call_id": "c_db"}]
                opt_msgs, metrics = pre.process_messages(msgs, max_tool_bytes=2048, model="gpt-4o-mini")
                
                st.success("Pre-Flight Context Optimization Complete")
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    st.markdown(card_metric_html("Original Tokens", f"{metrics.original_prompt_tokens:,}", "Raw JSON table dump", "database", "#94A3B8"), unsafe_allow_html=True)
                with col_b:
                    st.markdown(card_metric_html("Compressed Tokens", f"{metrics.trimmed_prompt_tokens:,}", "Schema + sample rows", "scissors", "#38BDF8"), unsafe_allow_html=True)
                with col_c:
                    pct = round((metrics.tokens_saved / metrics.original_prompt_tokens) * 100, 1)
                    st.markdown(card_metric_html("Tokens Saved", f"{metrics.tokens_saved:,}", f"{pct}% payload reduction", "shield", "#10B981"), unsafe_allow_html=True)
                st.json(json.loads(opt_msgs[0]["content"]))
                handler = None
            else:
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
                mock = MockUpstreamClient(stream_chunks=chunks)
                handler = ProxyHandler(db=sim_db, upstream_client=mock)
                payload = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Write fibonacci"}], "stream": True}

            if handler is not None:
                stream_box = st.empty()
                sid = f"sandbox_sim_{int(time.time())}"

                async def execute_simulation(h, p, s_id, box):
                    accumulated_text = ""
                    was_tripped = False
                    async for chunk_str in h.stream_chat_completion(p, session_id=s_id):
                        if "data:" in chunk_str and "[DONE]" not in chunk_str:
                            for line in chunk_str.splitlines():
                                if line.startswith("data:"):
                                    try:
                                        d = json.loads(line[5:].strip())
                                        c = d["choices"][0]["delta"].get("content")
                                        if c:
                                            accumulated_text += c
                                            box.text_area("Live Stream Terminal", value=accumulated_text, height=180)
                                            if "Runaway loop halted" in c:
                                                was_tripped = True
                                    except Exception:
                                        pass
                    return accumulated_text, was_tripped

                streamed_text, tripped = asyncio.run(execute_simulation(handler, payload, sid, stream_box))

                if tripped:
                    st.error("Circuit Breaker Tripped: Runaway loop intercepted in-flight to prevent token burn.")
                    st.info("System recovery prompt injected into session history.")
                else:
                    st.success("Stream completed normally with 0% false positives.")


# ==============================================================================
# TAB 4: 16-SCENARIO BENCHMARK SCORECARD
# ==============================================================================
with tab_benchmarks:
    st.markdown(section_header_html("16-Scenario Benchmark Evaluation Suite", "Run comprehensive benchmarks across tool loops, circular reasoning, payload bloat, and false positive challenges", "trophy", "#F59E0B"), unsafe_allow_html=True)

    if st.button("Execute Full 16-Scenario Benchmark Suite", use_container_width=True):
        with st.spinner("Running all 16 benchmark scenarios..."):
            results = asyncio.run(run_all_benchmarks())

            df_results = pd.DataFrame([
                {
                    "Scenario ID": r.scenario_id,
                    "Name": r.name,
                    "Category": r.category,
                    "Baseline Tokens": r.baseline_tokens,
                    "TokenShield Tokens": r.tokenshield_tokens,
                    "Tokens Saved": r.tokens_saved,
                    "Reduction %": f"{r.reduction_pct}%",
                    "Status": r.status,
                }
                for r in results
            ])

            total_saved = sum(r.tokens_saved for r in results)
            total_baseline = sum(r.baseline_tokens for r in results)
            avg_reduction = round((total_saved / max(1, total_baseline)) * 100.0, 2)
            fp_count = sum(1 for r in results if r.false_positive)

            st.dataframe(df_results, use_container_width=True)

            col_m1, col_m2, col_m3 = st.columns(3)
            with col_m1:
                st.markdown(card_metric_html("Tokens Saved", f"{total_saved:,}", "Across all 16 scenarios", "shield", "#38BDF8"), unsafe_allow_html=True)
            with col_m2:
                st.markdown(card_metric_html("Net Reduction Rate", f"{avg_reduction}%", "Target > 75%", "gauge", "#10B981"), unsafe_allow_html=True)
            with col_m3:
                st.markdown(card_metric_html("False-Positive Rate", f"{fp_count} / 4 ({0.0 if fp_count == 0 else 100.0}%)", "Target: 0.0%", "check", "#38BDF8" if fp_count == 0 else "#EF4444"), unsafe_allow_html=True)


# ==============================================================================
# TAB 5: SYSTEM HEALTH & QUICK GUIDE
# ==============================================================================
with tab_about:
    st.markdown(section_header_html("System Health & Integration Manual", "SDK integration patterns and terminal command reference", "info", "#38BDF8"), unsafe_allow_html=True)
    st.markdown("""
    ### How to Route Agent Requests Through TokenShield
    Point your standard OpenAI client SDK `base_url` to TokenShield:
    ```python
    from openai import OpenAI

    client = OpenAI(
        base_url="http://localhost:8000/v1",
        api_key="your-upstream-api-key",
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Execute autonomous task"}],
        stream=True,
    )
    ```

    ---
    ### Terminal Commands
    * **Start Proxy Server:** `uvicorn tokenshield.proxy.server:app --host 0.0.0.0 --port 8000 --reload`
    * **Start Dashboard:** `streamlit run tokenshield/dashboard/app.py`
    * **Run Test Suite:** `pytest tests/ -v`
    * **Run Benchmarks:** `python tests/scenarios/benchmark_runner.py`
    """)
