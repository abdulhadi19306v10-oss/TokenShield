"""Unit tests for ChunkStreamInspector, NGramEvaluator, and StreamMonitor."""

import json
import pytest
from tokenshield.engine.stream_monitor import (
    ChunkStreamInspector,
    NGramEvaluator,
    StreamMonitor,
)
from tokenshield.telemetry.models import TripReason


def test_chunk_stream_inspector_parsing():
    """Verify SSE chunk buffering and delta extraction."""
    inspector = ChunkStreamInspector()

    # Feed normal frame
    raw_sse = 'data: {"id":"chat-1","choices":[{"index":0,"delta":{"content":"Hello world"},"finish_reason":null}]}\n\n'
    results = inspector.feed_chunk(raw_sse)
    assert len(results) == 1
    assert results[0] == ("Hello world", None)
    assert inspector.total_tokens == 1

    # Feed fragmented frame across 2 network chunks
    chunk_part1 = 'data: {"id":"chat-2","choices":[{"index":0,"delta":{"content":"part'
    chunk_part2 = 'ial"},"finish_reason":null}]}\n\n'
    res1 = inspector.feed_chunk(chunk_part1)
    assert len(res1) == 0  # Buffered, incomplete

    res2 = inspector.feed_chunk(chunk_part2)
    assert len(res2) == 1
    assert res2[0] == ("partial", None)

    # Feed [DONE]
    res3 = inspector.feed_chunk("data: [DONE]\n\n")
    assert len(res3) == 1
    assert res3[0] == (None, "stop")


def test_ngram_evaluator_repetition():
    """Verify n-gram overlap scoring on repeating vs diverse token streams."""
    evaluator = NGramEvaluator()

    diverse_tokens = ["the", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog", "in", "the", "park", "today"]
    score_diverse = evaluator.compute_ngram_overlap(diverse_tokens, n=3)
    assert score_diverse < 0.25

    # Verbatim repeating loop: "repeat this phrase repeat this phrase repeat this phrase..."
    repeat_tokens = ["repeat", "this", "phrase"] * 6
    score_repeat = evaluator.compute_ngram_overlap(repeat_tokens, n=3)
    assert score_repeat > 0.60


def test_sentence_similarity_evaluator():
    """Verify semantic sentence similarity scoring on circular phrasing."""
    evaluator = NGramEvaluator()

    past_sentences = [
        "First I need to inspect the database schema carefully.",
        "Now let me verify the configuration file settings.",
    ]

    # Dissimilar sentence
    sim_low = evaluator.compute_sentence_similarity(
        "The weather outside is completely sunny today.",
        past_sentences,
    )
    assert sim_low < 0.40

    # Circular paraphrase
    sim_high = evaluator.compute_sentence_similarity(
        "First I must inspect the database schema very carefully.",
        past_sentences,
    )
    assert sim_high > 0.80


def test_stream_monitor_detects_repetition_loop():
    """Verify StreamMonitor detects verbatim repetition loop and trips."""
    monitor = StreamMonitor(session_id="test-rep-session")

    # Feed repeating tokens
    repeating_chunk = "Let me think about step one. "
    loop_detected = False
    last_res = None

    for _ in range(8):
        res = monitor.evaluate_chunk(repeating_chunk)
        last_res = res
        if res.is_loop_detected:
            loop_detected = True
            break

    assert loop_detected is True
    assert last_res is not None
    assert last_res.anomaly_score >= 0.70
    assert last_res.trigger_reason in (TripReason.NGRAM_REPETITION, TripReason.CIRCULAR_REASONING)


def test_stream_monitor_code_fence_whitelist():
    """Verify that repetition inside markdown code fences does not false-positive trip."""
    monitor = StreamMonitor(session_id="test-code-session")

    # Start code block
    monitor.evaluate_chunk("Here is the python code:\n```python\n")

    # Repeated code constructs (e.g. for loop syntax)
    code_lines = [
        "for i in range(10):\n",
        "    for j in range(10):\n",
        "        for k in range(10):\n",
        "            print(i, j, k)\n",
    ]
    for line in code_lines:
        res = monitor.evaluate_chunk(line)
        assert res.in_code_fence is True
        # Code fence increases threshold, so it should not trip
        assert res.is_loop_detected is False


def test_stream_monitor_normal_generation_passes():
    """Verify that normal diverse multi-sentence generation stays below anomaly thresholds."""
    monitor = StreamMonitor(session_id="test-normal-session")

    paragraphs = [
        "Artificial intelligence systems require robust monitoring infrastructure. ",
        "By intercepting streaming tokens in real time, proxies can detect runaway loops early. ",
        "This saves significant API costs and reduces latency for end users. ",
        "In addition, pre-execution compression removes redundant JSON bloat. ",
    ]

    for p in paragraphs:
        res = monitor.evaluate_chunk(p)
        assert res.is_loop_detected is False
        assert res.anomaly_score < 0.60
