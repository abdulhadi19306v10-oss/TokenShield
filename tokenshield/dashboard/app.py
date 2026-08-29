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
from tokenshield.engine.pre_execution import PreExecutionEngine
from tokenshield.proxy.handler import ProxyHandler
from tokenshield.telemetry.database import TelemetryDatabase
from tokenshield.telemetry.metrics import TokenomicsCalculator
from tokenshield.telemetry.models import SessionStatus

# Page Configuration
st.set_page_config(
    page_title="TokenShield GUI & Control Center",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)


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


# --- Sidebar ---
config = get_config()

st.sidebar.title("🛡️ TokenShield")
st.sidebar.caption("Real-Time Agentic Trajectory & Token Interceptor")

db_file = st.sidebar.text_input("Active Database Path", value=config.DATABASE_PATH)
auto_refresh = st.sidebar.checkbox("Auto-refresh (5s)", value=False)
if auto_refresh:
    time.sleep(5)
    st.rerun()

st.sidebar.divider()
st.sidebar.subheader("Quick Status")
st.sidebar.markdown(f"**Proxy Target:** `{config.HOST}:{config.PORT}`")
st.sidebar.markdown(f"**Default Model:** `{config.DEFAULT_MODEL}`")
st.sidebar.markdown(f"**Trip Threshold:** `{config.LOOP_ANOMALY_THRESHOLD}`")
st.sidebar.markdown(f"**Similarity Threshold:** `{config.SIMILARITY_THRESHOLD}`")

st.sidebar.divider()
if st.sidebar.button("🔄 Reload Settings from .env"):
    config = reload_config()
    st.sidebar.success("Configuration reloaded successfully!")


# --- Main Tabbed Navigation ---
tab_telemetry, tab_settings, tab_sandbox, tab_benchmarks, tab_about = st.tabs([
    "📊 Live Telemetry",
    "⚙️ Settings & Config GUI",
    "🧪 Interactive Sandbox",
    "🏆 16-Scenario Benchmarks",
    "ℹ️ System Health & Guide",
])


# ==============================================================================
# TAB 1: LIVE TELEMETRY & CONTROL ROOM
# ==============================================================================
with tab_telemetry:
    st.title("🛡️ Live Telemetry & Control Room")
    st.markdown("Real-time monitoring of LLM streaming agent trajectories, context deduplication savings, and circuit trips.")

    metrics = load_aggregate_metrics(db_file)

    if not metrics or metrics["total_sessions"] == 0:
        st.info("No telemetry sessions recorded yet. Start proxy requests, run a sandbox test, or launch benchmarks.")
    else:
        # Top KPI Scorecards
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Tokens Saved", f"{metrics['total_tokens_saved']:,}")
        with col2:
            st.metric("Total Cost Saved (USD)", f"${metrics['total_cost_saved_usd']:.4f}")
        with col3:
            st.metric("Circuit Breaker Trips", f"{metrics['total_trips']}", delta=f"{metrics['tripped_sessions']} sessions")
        with col4:
            st.metric("Monitored Sessions", f"{metrics['total_sessions']}", delta=f"{metrics['active_sessions']} active")

        st.divider()

        # Real-time Trajectory Anomaly Monitor
        st.subheader("📈 In-Flight Trajectory Anomaly Monitor")
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
                        line=dict(color="#2563EB", width=2),
                        marker=dict(size=6),
                    )
                )

                fig.add_hline(
                    y=config.LOOP_ANOMALY_THRESHOLD,
                    line_dash="dash",
                    line_color="#DC2626",
                    annotation_text=f"Trip Threshold ({config.LOOP_ANOMALY_THRESHOLD})",
                    annotation_position="bottom right",
                )

                fig.update_layout(
                    title=f"Anomaly Progression for Session: {selected_session}",
                    xaxis_title="Event Sequence / Evaluation Tick",
                    yaxis_title="Anomaly Score (0.0 to 1.0)",
                    yaxis=dict(range=[0, 1.05]),
                    template="plotly_white",
                    height=380,
                )
                st.plotly_chart(fig, use_container_width=True)

                with st.expander("🔍 View Raw Trajectory Event Telemetry"):
                    st.dataframe(events_df, use_container_width=True)
            else:
                st.info("No chunk evaluation events logged for this session.")

        st.divider()

        # Circuit Breaker Trips Log
        st.subheader("⚡ Intercepted Loop Incidents")
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
        st.subheader("📋 Session History & Tokenomics")
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
    st.title("⚙️ Settings & Configuration Manager")
    st.markdown("Modify TokenShield proxy configuration, anomaly detection thresholds, and circuit breaker policies directly from this graphical interface.")

    with st.form("settings_form"):
        st.subheader("🌐 Network & Upstream Provider")
        c1, c2 = st.columns(2)
        with c1:
            host_val = st.text_input("Proxy Host", value=config.HOST, help="Network interface to bind (0.0.0.0 for all interfaces)")
            port_val = st.number_input("Proxy Port", value=int(config.PORT), min_value=1024, max_value=65535)
            model_val = st.text_input("Default Model", value=config.DEFAULT_MODEL, help="Target LLM model name (e.g. gpt-4o-mini, gpt-4o, claude-3-5-sonnet)")
        with c2:
            base_url_val = st.text_input("Upstream Base URL", value=config.UPSTREAM_BASE_URL, help="Upstream API base URL (e.g. https://api.openai.com/v1)")
            api_key_val = st.text_input("Upstream API Key", value=config.UPSTREAM_API_KEY, type="password", help="Authorization Bearer key for upstream LLM")

        st.divider()
        st.subheader("🗜️ Pre-Execution Optimization")
        c3, c4, c5 = st.columns(3)
        with c3:
            enable_dedup = st.toggle("Enable Pre-Flight Deduplication", value=bool(config.ENABLE_DEDUPLICATION))
        with c4:
            max_bytes_val = st.slider("Max Tool Payload Bytes", min_value=512, max_value=16384, value=int(config.MAX_TOOL_PAYLOAD_BYTES), step=512, help="Payloads exceeding this size trigger schema summarization")
        with c5:
            sliding_turns_val = st.slider("Sliding Window Turns", min_value=2, max_value=50, value=int(config.SLIDING_WINDOW_TURNS), step=1, help="Max conversational turns retained before trimming stale history")

        st.divider()
        st.subheader("⚡ In-Flight Stream Anomaly Thresholds")
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
        st.subheader("🛡️ Circuit Breaker & Database Policies")
        c8, c9, c10 = st.columns(3)
        with c8:
            auto_steer = st.toggle("Auto-Inject System Steering", value=bool(config.AUTO_INJECT_STEERING), help="Injects corrective recovery guidance when loops trip")
        with c9:
            human_checkpoint = st.toggle("Enable Human Checkpoint Gate", value=bool(config.ENABLE_HUMAN_CHECKPOINT), help="Suspends execution at loop detection for manual operator clearance")
        with c10:
            db_path_val = st.text_input("Database File Path", value=config.DATABASE_PATH)

        st.divider()
        submitted = st.form_submit_button("💾 Save & Apply to .env File", use_container_width=True)

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
            st.success("✅ Configuration saved to .env and runtime cache updated!")

    st.divider()
    st.subheader("🔌 Test Upstream Connectivity")
    if st.button("Probe Upstream Connection"):
        try:
            with st.spinner("Pinging upstream endpoint..."):
                resp = httpx.get(f"{config.UPSTREAM_BASE_URL.rstrip('/')}/models", headers={"Authorization": f"Bearer {config.UPSTREAM_API_KEY}"} if config.UPSTREAM_API_KEY else {}, timeout=5.0)
                st.info(f"Upstream responded with status HTTP {resp.status_code}")
        except Exception as e:
            st.warning(f"Connection probe test: {str(e)} (Normal if running in offline mock mode)")


# ==============================================================================
# TAB 3: INTERACTIVE SANDBOX & PROMPT SIMULATOR
# ==============================================================================
with tab_sandbox:
    st.title("🧪 Interactive Testing Sandbox")
    st.markdown("Test TokenShield's pre-flight context compression and in-flight streaming circuit breaker in real time.")

    preset = st.selectbox(
        "Select Simulation Scenario Preset",
        [
            "Infinite Web Scraper 403 Loop (Runaway Tool Failure)",
            "Circular Analytical Reasoning Loop (Repeating Thought Chain)",
            "50KB Tabular JSON Bloat (Pre-Flight Compression)",
            "Normal Complex Code Generation (0% False-Positive Test)",
        ]
    )

    if st.button("🚀 Run Live Sandbox Simulation"):
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
                
                st.success("✅ Pre-Flight Context Optimization Complete!")
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    st.metric("Original Prompt Tokens", f"{metrics.original_prompt_tokens}")
                with col_b:
                    st.metric("Compressed Tokens", f"{metrics.trimmed_prompt_tokens}")
                with col_c:
                    st.metric("Tokens Saved", f"{metrics.tokens_saved}", delta=f"{round((metrics.tokens_saved/metrics.original_prompt_tokens)*100, 1)}% reduction")
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
                                            box.text_area("Live Stream Output", value=accumulated_text, height=200)
                                            if "Runaway loop halted" in c:
                                                was_tripped = True
                                    except Exception:
                                        pass
                    return accumulated_text, was_tripped

                streamed_text, tripped = asyncio.run(execute_simulation(handler, payload, sid, stream_box))

                if tripped:
                    st.error("⚡ **Circuit Breaker Tripped!** Runaway loop intercepted in-flight to prevent token burn.")
                    st.info("System recovery prompt injected into session history.")
                else:
                    st.success("✅ Stream completed normally with 0% false positives.")


# ==============================================================================
# TAB 4: 16-SCENARIO BENCHMARK SCORECARD
# ==============================================================================
with tab_benchmarks:
    st.title("🏆 16-Scenario Benchmark Evaluation Suite")
    st.markdown("Run the complete 16-scenario benchmark suite to evaluate token reduction rates, cost savings, and false-positive resilience.")

    if st.button("▶️ Execute Full 16-Scenario Benchmark Suite", use_container_width=True):
        with st.spinner("Running all 16 benchmark scenarios..."):
            results = asyncio.run(run_all_benchmarks())

            # Convert to DataFrame
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
                st.metric("Total Tokens Saved Across Suite", f"{total_saved:,}")
            with col_m2:
                st.metric("Net Token Reduction Rate", f"{avg_reduction}%", delta="Target > 75%")
            with col_m3:
                st.metric("False-Positive Rate", f"{fp_count} / 4 ({0.0 if fp_count == 0 else 100.0}%)", delta="0% target")


# ==============================================================================
# TAB 5: SYSTEM HEALTH & QUICK GUIDE
# ==============================================================================
with tab_about:
    st.title("ℹ️ System Health & Integration Guide")
    st.markdown("""
    ### 🛡️ How to Route Agent Requests Through TokenShield
    Clients simply point their standard OpenAI client SDK `base_url` to TokenShield:
    ```python
    from openai import OpenAI

    client = OpenAI(
        base_url="http://localhost:8000/v1",
        api_key="your-upstream-api-key",
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello TokenShield!"}],
        stream=True,
    )
    ```

    ---
    ### 🚀 Terminal Commands
    * **Start Proxy Server:** `uvicorn tokenshield.proxy.server:app --host 0.0.0.0 --port 8000 --reload`
    * **Start Dashboard:** `streamlit run tokenshield/dashboard/app.py`
    * **Run Test Suite:** `pytest tests/ -v`
    * **Run Benchmarks:** `python tests/scenarios/benchmark_runner.py`
    """)
