"""TokenShield Live Monitoring Dashboard & Human Checkpoint Control Room."""

import json
import os
import sqlite3
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tokenshield.config import get_config

st.set_page_config(
    page_title="TokenShield Control Panel",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

config = get_config()


# --- Database Query Helpers ---
# ponytail: synchronous sqlite3 connection delivers immediate Streamlit rendering without async event loop contention
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
st.sidebar.title("🛡️ TokenShield")
st.sidebar.caption("Real-Time Agentic Trajectory & Token Interceptor")

db_file = st.sidebar.text_input("Database Path", value=config.DATABASE_PATH)
auto_refresh = st.sidebar.checkbox("Auto-refresh (5s)", value=False)
if auto_refresh:
    # ponytail: native experimental rerun for continuous real-time polling
    st.empty()
    st.sidebar.caption("Auto-refresh active")

st.sidebar.divider()
st.sidebar.subheader("Configuration")
st.sidebar.markdown(f"**Host:** `{config.HOST}:{config.PORT}`")
st.sidebar.markdown(f"**Anomaly Threshold:** `{config.LOOP_ANOMALY_THRESHOLD}`")
st.sidebar.markdown(f"**Similarity Threshold:** `{config.SIMILARITY_THRESHOLD}`")
st.sidebar.markdown(f"**Sliding Window Turns:** `{config.SLIDING_WINDOW_TURNS}`")
st.sidebar.markdown(f"**Auto-Steering:** `{config.AUTO_INJECT_STEERING}`")


# --- Main Dashboard ---
st.title("🛡️ TokenShield Live Telemetry & Control Room")
st.markdown(
    "Monitoring real-time LLM streaming agent trajectories, context deduplication savings, and circuit breaker intercepts."
)

metrics = load_aggregate_metrics(db_file)

if not metrics or metrics["total_sessions"] == 0:
    st.info("No telemetry sessions recorded yet. Start running proxy requests or benchmarks to view live stream data.")
else:
    # 1. Top KPI Cards
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Tokens Saved", f"{metrics['total_tokens_saved']:,}")
    with col2:
        st.metric("Total USD Cost Saved", f"${metrics['total_cost_saved_usd']:.4f}")
    with col3:
        st.metric("Circuit Breaker Trips", f"{metrics['total_trips']}", delta=f"{metrics['tripped_sessions']} sessions")
    with col4:
        st.metric("Active Sessions", f"{metrics['active_sessions']} / {metrics['total_sessions']}")

    st.divider()

    # 2. Real-Time Trajectory Stream Chart
    st.subheader("📈 In-Flight Trajectory Anomaly Monitor")
    sessions_df = load_sessions(db_file, limit=50)

    if not sessions_df.empty:
        session_list = sessions_df["session_id"].tolist()
        selected_session = st.selectbox("Select Monitored Session", session_list, index=0)

        events_df = load_session_events(db_file, selected_session)
        if not events_df.empty and "anomaly_score" in events_df.columns:
            fig = go.Figure()

            # Plot rolling anomaly score
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

            # Red dashed trip threshold line
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

            with st.expander("View Raw Trajectory Events"):
                st.dataframe(events_df, use_container_width=True)
        else:
            st.info("No chunk evaluation events logged for this session yet.")

    st.divider()

    # 3. Circuit Breaker Trips & Interception Log
    st.subheader("⚡ Intercepted Loop Events")
    trips_df = load_circuit_trips(db_file, limit=20)
    if not trips_df.empty:
        st.dataframe(
            trips_df[["trip_id", "session_id", "timestamp", "trigger_reason", "anomaly_score", "tokens_at_trip", "estimated_tokens_saved"]],
            use_container_width=True,
        )
    else:
        st.write("No circuit breaker trip events recorded.")

    st.divider()

    # 4. Monitored Sessions Explorer
    st.subheader("📋 Session History & Tokenomics")
    if not sessions_df.empty:
        st.dataframe(
            sessions_df[[
                "session_id", "model", "status", "total_prompt_tokens",
                "total_completion_tokens", "tokens_saved", "cost_saved_usd", "created_at"
            ]],
            use_container_width=True,
        )
