"""Unit tests for ContextTrimmerNode, PayloadDeduplicationEngine, and PreExecutionEngine."""

import json
import pytest
from tokenshield.engine.pre_execution import (
    ContextTrimmerNode,
    PayloadDeduplicationEngine,
    PreExecutionEngine,
)


def test_trim_history_preserves_system_prompt():
    """Verify that leading system instructions are preserved when trimming stale turns."""
    messages = [
        {"role": "system", "content": "You are a helpful coding assistant with strict safety rules."},
    ]
    # Add 20 turns (40 messages)
    for i in range(20):
        messages.append({"role": "user", "content": f"User question {i}"})
        messages.append({"role": "assistant", "content": f"Assistant response {i}"})

    # Trim to max 5 turns (should keep system + last 10 messages)
    trimmed, turns_pruned = ContextTrimmerNode.trim_history(messages, max_turns=5)

    assert len(trimmed) == 1 + 10  # 1 system + 10 turn messages
    assert trimmed[0]["role"] == "system"
    assert trimmed[0]["content"] == "You are a helpful coding assistant with strict safety rules."
    assert trimmed[-1]["content"] == "Assistant response 19"
    assert turns_pruned == 15


def test_deduplicate_system_prompts():
    """Verify pruning of duplicate system messages across turns (Scenario 9)."""
    messages = [
        {"role": "system", "content": "Master instructions: be concise."},
        {"role": "user", "content": "Turn 1"},
        {"role": "system", "content": "Master instructions: be concise."},
        {"role": "assistant", "content": "Turn 1 response"},
        {"role": "system", "content": "Master instructions: be concise."},
        {"role": "user", "content": "Turn 2"},
    ]

    deduped, pruned = ContextTrimmerNode.deduplicate_system_prompts(messages)
    assert pruned == 2
    assert len(deduped) == 4
    system_msgs = [m for m in deduped if m.get("role") == "system"]
    assert len(system_msgs) == 1
    assert system_msgs[0]["content"] == "Master instructions: be concise."


def test_compress_large_json_table():
    """Verify tabular JSON payloads > 4KB are condensed to sample + schema (Scenario 7)."""
    # Create large list of 50 items (> 5KB)
    large_table = [
        {"user_id": i, "name": f"User_{i}", "email": f"user{i}@example.com", "role": "member", "status": "active"}
        for i in range(50)
    ]
    raw_json = json.dumps(large_table)
    assert len(raw_json.encode("utf-8")) > 4096

    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "tool", "content": raw_json, "tool_call_id": "call_1"},
    ]

    compressed_msgs, comp_count, dup_count = PayloadDeduplicationEngine.compress_tool_outputs(
        messages, max_bytes=2048, enable_dedup=True
    )

    assert comp_count == 1
    tool_content = json.loads(compressed_msgs[1]["content"])
    assert "_tokenshield_summary" in tool_content
    assert tool_content["total_count"] == 50
    assert len(tool_content["sample"]) == 3
    assert "user_id" in tool_content["schema_fields"]
    assert len(compressed_msgs[1]["content"].encode("utf-8")) < 1000


def test_strip_html_noise():
    """Verify HTML scripts, styles, comments, and DOM bloat are stripped (Scenario 8)."""
    raw_html = """
    <html>
        <head>
            <script type="text/javascript">var tracking = "xyz"; console.log(tracking);</script>
            <style>body { background: red; margin: 0; }</style>
        </head>
        <body>
            <!-- Main Content Header -->
            <div class="content">
                <h1>Article Title</h1>
                <p>Essential extracted text paragraph.</p>
            </div>
            <!-- Footer tracker -->
            <script>sendTelemetry();</script>
        </body>
    </html>
    """
    cleaned = PayloadDeduplicationEngine.strip_html_noise(raw_html)
    assert "<script" not in cleaned.lower()
    assert "<style" not in cleaned.lower()
    assert "<!--" not in cleaned
    assert "Article Title" in cleaned
    assert "Essential extracted text paragraph." in cleaned


def test_duplicate_tool_payload_hash_deduplication():
    """Verify identical tool responses across turns are replaced with hash references."""
    repeated_output = json.dumps({"status": "error", "message": "Access Denied: 403 Forbidden"})
    messages = [
        {"role": "user", "content": "fetch url"},
        {"role": "tool", "content": repeated_output, "tool_call_id": "call_1"},
        {"role": "assistant", "content": "retrying..."},
        {"role": "tool", "content": repeated_output, "tool_call_id": "call_2"},
        {"role": "assistant", "content": "retrying again..."},
        {"role": "tool", "content": repeated_output, "tool_call_id": "call_3"},
    ]

    compressed_msgs, comp_count, dup_count = PayloadDeduplicationEngine.compress_tool_outputs(
        messages, max_bytes=4096, enable_dedup=True
    )

    assert dup_count == 2
    assert compressed_msgs[1]["content"] == repeated_output
    assert "[Duplicate Tool Output Ref:" in compressed_msgs[3]["content"]
    assert "[Duplicate Tool Output Ref:" in compressed_msgs[5]["content"]


def test_pre_execution_engine_full_pipeline():
    """Verify full end-to-end pre-flight optimization and token savings calculation."""
    engine = PreExecutionEngine()

    large_table = [
        {"id": i, "title": f"Doc {i}", "data": "x" * 100}
        for i in range(30)
    ]
    raw_json = json.dumps(large_table)

    messages = [
        {"role": "system", "content": "System directive."},
    ]
    for i in range(15):
        messages.append({"role": "user", "content": f"Query {i}"})
        messages.append({"role": "assistant", "content": f"Response {i}"})
    messages.append({"role": "tool", "content": raw_json, "tool_call_id": "call_99"})

    optimized, metrics = engine.process_messages(
        messages,
        max_turns=5,
        max_tool_bytes=1024,
        model="gpt-4o-mini",
    )

    assert metrics.original_prompt_tokens > metrics.trimmed_prompt_tokens
    assert metrics.tokens_saved > 0
    assert metrics.payloads_compressed >= 1
    assert metrics.turns_trimmed > 0
    assert len(optimized) < len(messages)
