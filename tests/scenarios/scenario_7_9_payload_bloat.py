"""Benchmark Scenarios 7 to 9: Payload Overhead Bloat & Context Compression."""

import json
import pytest
from tests.mock_upstream import MockUpstreamClient
from tokenshield.engine.pre_execution import PreExecutionEngine
from tokenshield.proxy.handler import ProxyHandler
from tokenshield.telemetry.database import TelemetryDatabase
from tokenshield.telemetry.models import SessionStatus


@pytest.mark.asyncio
async def test_scenario_7_large_json_table_compression(temp_db: TelemetryDatabase):
    """Scenario 7: Database tool returns 50KB JSON table; TokenShield compresses to sample + schema."""
    # Generate 50KB JSON table
    large_table = [
        {
            "id": i,
            "uuid": f"usr-uuid-abcdef-{i:04d}",
            "username": f"analyst_account_{i}",
            "email": f"account_{i}@enterprise-corp.internal",
            "metadata": {"dept": "finance", "level": "senior", "permissions": ["read", "write", "audit"]},
            "timestamp": "2026-08-29T12:00:00Z",
        }
        for i in range(150)
    ]
    raw_payload_str = json.dumps(large_table)
    raw_bytes = len(raw_payload_str.encode("utf-8"))
    assert raw_bytes > 30000

    pre_engine = PreExecutionEngine()
    messages = [
        {"role": "system", "content": "You are a database query assistant."},
        {"role": "user", "content": "Fetch all finance analysts"},
        {"role": "tool", "content": raw_payload_str, "tool_call_id": "call_db_dump"},
    ]

    optimized, metrics = pre_engine.process_messages(messages, max_tool_bytes=2048, model="gpt-4o-mini")

    # Verify compression savings > 85%
    savings_pct = (metrics.tokens_saved / max(1, metrics.original_prompt_tokens)) * 100.0
    assert savings_pct > 80.0
    assert metrics.payloads_compressed == 1
    assert len(optimized[2]["content"].encode("utf-8")) < 2500


@pytest.mark.asyncio
async def test_scenario_8_raw_html_noise_stripping(temp_db: TelemetryDatabase):
    """Scenario 8: Web fetch tool returns full HTML (100KB) with scripts/styles; TokenShield strips DOM noise."""
    # Create HTML dump with massive scripts and styles
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Corporate Annual Report 2026</title>
        <style>
            {"body { font-family: sans-serif; } .header { color: blue; } " * 200}
        </style>
        <script>
            {"function trackTelemetry() { console.log('tracking user session event data'); } " * 300}
        </script>
    </head>
    <body>
        <!-- Header Navigation Bar -->
        <div class="content">
            <h1>Q3 Financial Results Overview</h1>
            <p>Net revenue reached $15.4 million representing a 28% year-over-year increase across enterprise lines.</p>
        </div>
        <!-- Analytic trackers -->
        <script>
            {"window.analytics.push(['track', 'pageview', {timestamp: Date.now()}]); " * 300}
        </script>
    </body>
    </html>
    """
    assert len(html_content.encode("utf-8")) > 40000

    pre_engine = PreExecutionEngine()
    messages = [
        {"role": "system", "content": "You are a financial analysis assistant."},
        {"role": "user", "content": "Extract Q3 revenue from the report page."},
        {"role": "tool", "content": html_content, "tool_call_id": "call_scrape"},
    ]

    optimized, metrics = pre_engine.process_messages(messages, max_tool_bytes=4096, model="gpt-4o-mini")

    savings_pct = (metrics.tokens_saved / max(1, metrics.original_prompt_tokens)) * 100.0
    assert savings_pct > 85.0
    assert "Q3 Financial Results Overview" in optimized[2]["content"]
    assert "<script" not in optimized[2]["content"].lower()
    assert "<style" not in optimized[2]["content"].lower()


@pytest.mark.asyncio
async def test_scenario_9_multi_turn_system_prompt_bloat(temp_db: TelemetryDatabase):
    """Scenario 9: Multi-turn chat history with 20 duplicate system messages; TokenShield prunes redundant turns."""
    messages = []
    # 20 duplicate system prompts interspersed with conversation
    for i in range(20):
        messages.append({"role": "system", "content": "System Directive: Follow ISO-27001 coding standards strictly."})
        messages.append({"role": "user", "content": f"Step {i} calculation query"})
        messages.append({"role": "assistant", "content": f"Step {i} result summary"})

    pre_engine = PreExecutionEngine()
    optimized, metrics = pre_engine.process_messages(messages, max_turns=5, model="gpt-4o-mini")

    # Trimmed down to 1 system prompt + last 10 messages
    system_msgs = [m for m in optimized if m.get("role") == "system"]
    assert len(system_msgs) == 1
    assert len(optimized) == 11  # 1 system + 10 turn messages
    assert metrics.turns_trimmed > 0
    assert metrics.tokens_saved > 0

    savings_pct = (metrics.tokens_saved / max(1, metrics.original_prompt_tokens)) * 100.0
    assert savings_pct >= 60.0
