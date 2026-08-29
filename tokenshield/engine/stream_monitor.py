"""Real-time streaming chunk inspector, n-gram repetition evaluator, and semantic similarity monitor."""

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from rapidfuzz import fuzz
from pydantic import BaseModel

from tokenshield.config import get_config
from tokenshield.telemetry.models import TripReason


class AnomalyScoreResult(BaseModel):
    """Result of real-time stream evaluation on incoming token chunk."""

    anomaly_score: float = 0.0
    ngram_score: float = 0.0
    similarity_score: float = 0.0
    tool_repeat_score: float = 0.0
    is_loop_detected: bool = False
    trigger_reason: Optional[TripReason] = None
    in_code_fence: bool = False
    total_tokens: int = 0
    token_velocity: float = 0.0  # tokens per second


class ChunkStreamInspector:
    """Buffers raw Server-Sent Event (SSE) frames and extracts streaming text deltas."""

    def __init__(self):
        self._raw_buffer: str = ""
        self._token_count: int = 0
        self._start_time: float = time.time()

    def feed_chunk(self, raw_sse_data: str) -> List[Tuple[Optional[str], Optional[str]]]:
        """Buffer incoming network chunk and parse complete SSE data frames."""
        self._raw_buffer += raw_sse_data
        extracted: List[Tuple[Optional[str], Optional[str]]] = []

        # SSE frames are separated by double newlines (\n\n or \r\n\r\n)
        # ponytail: splitting on double newline efficiently segments SSE packets
        while "\n\n" in self._raw_buffer or "\r\n\r\n" in self._raw_buffer:
            delim = "\r\n\r\n" if "\r\n\r\n" in self._raw_buffer else "\n\n"
            frame, self._raw_buffer = self._raw_buffer.split(delim, 1)
            frame = frame.strip()

            if not frame:
                continue

            for line in frame.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        extracted.append((None, "stop"))
                        continue
                    try:
                        data = json.loads(payload)
                        choices = data.get("choices", [])
                        if choices:
                            choice = choices[0]
                            delta = choice.get("delta", {})
                            content = delta.get("content")
                            finish_reason = choice.get("finish_reason")
                            if content is not None:
                                self._token_count += 1
                            extracted.append((content, finish_reason))
                    except (json.JSONDecodeError, KeyError, IndexError):
                        pass

        return extracted

    @property
    def total_tokens(self) -> int:
        return self._token_count

    def get_token_velocity(self) -> float:
        """Calculate generation speed in tokens per second."""
        elapsed = max(0.001, time.time() - self._start_time)
        return round(self._token_count / elapsed, 2)


class NGramEvaluator:
    """Computes exact n-gram repetition ratios and fuzzy semantic circular reasoning scores."""

    # Punctuation to exclude from n-gram tokens to prevent noise
    _PUNCT_EXCLUDE = set(",;{}()[]\"'`")

    @classmethod
    def tokenize_words(cls, text: str) -> List[str]:
        """Simple word tokenization stripping punctuation noise."""
        # ponytail: regex tokenization without heavy third-party tokenizers
        words = re.findall(r"\b[\w'-]+\b|[^\w\s]", text)
        return [w.lower() for w in words if w not in cls._PUNCT_EXCLUDE]

    @classmethod
    def compute_ngram_overlap(cls, tokens: List[str], n: int = 3, window_size: int = 40) -> float:
        """Compute repetition ratio of n-grams in rolling token window."""
        if len(tokens) < n:
            return 0.0

        # Use recent window
        window = tokens[-window_size:] if len(tokens) > window_size else tokens
        if len(window) < n:
            return 0.0

        # Generate n-tuples
        # ponytail: tuple comprehension for sub-millisecond n-gram generation
        ngrams = [tuple(window[i : i + n]) for i in range(len(window) - n + 1)]
        total_ngrams = len(ngrams)

        if total_ngrams < 4:
            return 0.0

        unique_ngrams = len(set(ngrams))
        repetition_ratio = 1.0 - (unique_ngrams / total_ngrams)
        return max(0.0, min(1.0, repetition_ratio))

    @classmethod
    def compute_sentence_similarity(
        cls,
        current_sentence: str,
        past_sentences: List[str],
    ) -> float:
        """Compute highest Levenshtein token similarity against preceding sentences."""
        clean_curr = current_sentence.strip()
        if len(clean_curr) < 12 or not past_sentences:
            return 0.0

        max_sim = 0.0
        # ponytail: inspect recent 6 sentences to catch circular phrasing
        candidates = past_sentences[-6:]
        for past in candidates:
            clean_past = past.strip()
            if len(clean_past) < 12:
                continue
            ratio = fuzz.token_sort_ratio(clean_curr, clean_past) / 100.0
            if ratio > max_sim:
                max_sim = ratio

        return max_sim

    @classmethod
    def calculate_composite_score(
        cls,
        ngram_score: float,
        similarity_score: float,
        tool_repeat_score: float = 0.0,
    ) -> float:
        """Calculate weighted composite loop anomaly score."""
        # Alpha=0.45 (n-gram loops), Beta=0.40 (fuzzy reasoning), Gamma=0.15 (tool repetitions)
        if tool_repeat_score > 0.0:
            score = (0.45 * ngram_score) + (0.40 * similarity_score) + (0.15 * tool_repeat_score)
        else:
            # ponytail: normalize over active weights (0.45 + 0.40 = 0.85) when tool repeat is absent
            score = ((0.45 * ngram_score) + (0.40 * similarity_score)) / 0.85

        # Reflect strong signal if either primary indicator is elevated
        if ngram_score >= 0.60 or similarity_score >= 0.85:
            score = max(score, ngram_score, similarity_score)

        return round(min(1.0, max(0.0, score)), 4)


class StreamMonitor:
    """Monitors live streaming response tokens and detects loops in-flight."""

    _SENTENCE_SPLIT_RE = re.compile(r"[.!?\n]+")

    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self.config = get_config()
        self.inspector = ChunkStreamInspector()
        self.evaluator = NGramEvaluator()

        self._token_history: List[str] = []
        self._sentence_history: List[str] = []
        self._current_sentence_buffer: str = ""
        self._in_code_fence: bool = False
        self._consecutive_high_ticks: int = 0

    def reset(self) -> None:
        """Reset internal stream monitoring buffers."""
        self._token_history.clear()
        self._sentence_history.clear()
        self._current_sentence_buffer = ""
        self._in_code_fence = False
        self._consecutive_high_ticks = 0
        self.inspector = ChunkStreamInspector()

    def evaluate_chunk(
        self,
        chunk_text: str,
        tool_repeat_score: float = 0.0,
    ) -> AnomalyScoreResult:
        """Inspect chunk text delta, update state, and compute anomaly score."""
        if not chunk_text:
            return AnomalyScoreResult(
                in_code_fence=self._in_code_fence,
                total_tokens=len(self._token_history),
                token_velocity=self.inspector.get_token_velocity(),
            )

        # 1. Update markdown code fence state (``` toggles code block)
        # ponytail: count backtick triplets to track code context
        if "```" in chunk_text:
            fence_count = chunk_text.count("```")
            if fence_count % 2 != 0:
                self._in_code_fence = not self._in_code_fence

        # 2. Tokenize and update rolling token history
        new_tokens = self.evaluator.tokenize_words(chunk_text)
        self._token_history.extend(new_tokens)

        # 3. Update sentence buffers (only outside code fences to prevent false positives on code keywords)
        self._current_sentence_buffer += chunk_text
        parts = self._SENTENCE_SPLIT_RE.split(self._current_sentence_buffer)
        similarity_score = 0.0

        if not self._in_code_fence:
            if len(parts) > 1:
                # Completed sentences emerged
                completed = parts[:-1]
                self._current_sentence_buffer = parts[-1]
                for s in completed:
                    if s.strip():
                        sim = self.evaluator.compute_sentence_similarity(s, self._sentence_history)
                        if sim > similarity_score:
                            similarity_score = sim
                        self._sentence_history.append(s.strip())
            else:
                # Check current in-progress sentence if long enough
                if len(self._current_sentence_buffer) > 20:
                    similarity_score = self.evaluator.compute_sentence_similarity(
                        self._current_sentence_buffer, self._sentence_history
                    )
        else:
            # Inside code fences: clear sentence buffer and bypass similarity
            if len(parts) > 1:
                self._current_sentence_buffer = parts[-1]

        # 4. Compute n-gram score
        ngram_score = self.evaluator.compute_ngram_overlap(
            self._token_history,
            n=self.config.NGRAM_N,
            window_size=self.config.NGRAM_WINDOW_TOKENS,
        )

        # 5. Calculate composite anomaly score
        if self._in_code_fence:
            # ponytail: code blocks rely purely on extreme verbatim n-gram repetition
            composite = ngram_score
        else:
            composite = self.evaluator.calculate_composite_score(
                ngram_score=ngram_score,
                similarity_score=similarity_score,
                tool_repeat_score=tool_repeat_score,
            )

        # 6. Check trip threshold with code fence whitelist adjustment
        active_threshold = 0.90 if self._in_code_fence else self.config.LOOP_ANOMALY_THRESHOLD
        total_tokens_seen = len(self._token_history)

        is_loop = False
        trigger_reason: Optional[TripReason] = None

        if total_tokens_seen >= self.config.MIN_TOKENS_BEFORE_CHECK:
            if composite >= active_threshold or (similarity_score >= self.config.SIMILARITY_THRESHOLD and not self._in_code_fence):
                self._consecutive_high_ticks += 1
                # Trip on 2 consecutive ticks or extreme anomaly (>= 0.85)
                if self._consecutive_high_ticks >= 2 or composite >= 0.85:
                    is_loop = True
                    if ngram_score >= 0.60:
                        trigger_reason = TripReason.NGRAM_REPETITION
                    elif similarity_score >= self.config.SIMILARITY_THRESHOLD:
                        trigger_reason = TripReason.CIRCULAR_REASONING
                    else:
                        trigger_reason = TripReason.TOOL_ERROR_LOOP
            else:
                self._consecutive_high_ticks = max(0, self._consecutive_high_ticks - 1)

        return AnomalyScoreResult(
            anomaly_score=composite,
            ngram_score=ngram_score,
            similarity_score=similarity_score,
            tool_repeat_score=tool_repeat_score,
            is_loop_detected=is_loop,
            trigger_reason=trigger_reason,
            in_code_fence=self._in_code_fence,
            total_tokens=total_tokens_seen,
            token_velocity=self.inspector.get_token_velocity(),
        )
