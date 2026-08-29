"""Pre-execution context compression, sliding window trimmer, and tool payload deduplicator."""

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple
import tiktoken
from pydantic import BaseModel

from tokenshield.config import get_config


class PreExecutionMetrics(BaseModel):
    """Metrics recorded during pre-execution message optimization."""

    original_prompt_tokens: int = 0
    trimmed_prompt_tokens: int = 0
    tokens_saved: int = 0
    payloads_compressed: int = 0
    duplicate_payloads_truncated: int = 0
    turns_trimmed: int = 0


class ContextTrimmerNode:
    """Prunes stale historical turns while preserving leading system instructions."""

    @staticmethod
    def deduplicate_system_prompts(messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
        """Remove duplicate system messages that repeat across multiple conversational turns."""
        seen_system_hashes = set()
        deduped: List[Dict[str, Any]] = []
        pruned_count = 0

        for idx, msg in enumerate(messages):
            if msg.get("role") == "system":
                content = msg.get("content", "")
                h = hashlib.sha256(content.encode("utf-8")).hexdigest()
                # ponytail: preserve the first occurrence, drop subsequent duplicate system prompts
                if h in seen_system_hashes:
                    pruned_count += 1
                    continue
                seen_system_hashes.add(h)
            deduped.append(msg)

        return deduped, pruned_count

    @classmethod
    def trim_history(
        cls,
        messages: List[Dict[str, Any]],
        max_turns: int = 10,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Retain leading system prompts and the most recent N turns, discarding stale intermediate turns."""
        if not messages or max_turns <= 0:
            return messages, 0

        # 1. Deduplicate system prompts first
        messages, dedup_pruned = cls.deduplicate_system_prompts(messages)

        # 2. Identify leading system instructions
        lead_system_msgs: List[Dict[str, Any]] = []
        other_msgs: List[Dict[str, Any]] = []
        still_in_lead = True

        for msg in messages:
            if still_in_lead and msg.get("role") == "system":
                lead_system_msgs.append(msg)
            else:
                still_in_lead = False
                other_msgs.append(msg)

        # Each conversational turn typically comprises 2 messages (user/assistant or tool_call/tool_response)
        max_retained_messages = max_turns * 2
        if len(other_msgs) <= max_retained_messages:
            return lead_system_msgs + other_msgs, dedup_pruned

        # ponytail: slicing the tail directly retains the freshest context
        trimmed_others = other_msgs[-max_retained_messages:]
        turns_pruned = (len(other_msgs) - len(trimmed_others)) // 2

        return lead_system_msgs + trimmed_others, turns_pruned + dedup_pruned


class PayloadDeduplicationEngine:
    """Minifies, condenses, and hash-deduplicates oversized tool outputs and raw HTML/JSON."""

    # Regex patterns for HTML noise stripping
    _SCRIPT_RE = re.compile(r"<script[\s\S]*?</script>", re.IGNORECASE)
    _STYLE_RE = re.compile(r"<style[\s\S]*?</style>", re.IGNORECASE)
    _COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
    _WHITESPACE_RE = re.compile(r"\s{2,}")

    @classmethod
    def strip_html_noise(cls, html_str: str) -> str:
        """Strip scripts, styles, comments, and redundant DOM whitespace from HTML dumps."""
        # ponytail: sequential regex replacements efficiently strip unwanted markup
        cleaned = cls._SCRIPT_RE.sub("", html_str)
        cleaned = cls._STYLE_RE.sub("", cleaned)
        cleaned = cls._COMMENT_RE.sub("", cleaned)
        cleaned = cls._WHITESPACE_RE.sub(" ", cleaned)
        return cleaned.strip()

    @staticmethod
    def minify_json(json_str: str) -> str:
        """Minify JSON payload by removing whitespace and indentation."""
        try:
            parsed = json.loads(json_str)
            return json.dumps(parsed, separators=(",", ":"))
        except (json.JSONDecodeError, TypeError):
            return json_str

    @classmethod
    def clean_dict_nulls(cls, obj: Any) -> Any:
        """Recursively strip null keys and empty collections to reduce token payload."""
        if isinstance(obj, dict):
            return {
                k: cls.clean_dict_nulls(v)
                for k, v in obj.items()
                if v is not None and v != "" and v != [] and v != {}
            }
        elif isinstance(obj, list):
            return [cls.clean_dict_nulls(elem) for elem in obj if elem is not None]
        return obj

    @classmethod
    def compress_single_payload(cls, content: str, max_bytes: int) -> str:
        """Compress oversized JSON or HTML content using schema summarization and minification."""
        # Check for JSON structure
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                total_items = len(parsed)
                if total_items > 3:
                    # ponytail: summarize tabular JSON by showing first 3 items + schema summary
                    sample = [cls.clean_dict_nulls(item) for item in parsed[:3]]
                    keys = list(parsed[0].keys()) if parsed and isinstance(parsed[0], dict) else []
                    compact_summary = {
                        "_tokenshield_summary": f"Showing 3 of {total_items} items (minified & compressed)",
                        "schema_fields": keys,
                        "sample": sample,
                        "total_count": total_items,
                    }
                    return json.dumps(compact_summary, separators=(",", ":"))
                else:
                    return json.dumps(cls.clean_dict_nulls(parsed), separators=(",", ":"))
            elif isinstance(parsed, dict):
                cleaned = cls.clean_dict_nulls(parsed)
                minified = json.dumps(cleaned, separators=(",", ":"))
                if len(minified.encode("utf-8")) > max_bytes:
                    return minified[:max_bytes] + "... [Truncated by TokenShield]"
                return minified
        except (json.JSONDecodeError, TypeError):
            pass

        # Check for HTML structure
        content_lower = content.lower()
        if "<html" in content_lower or "<body" in content_lower or "<script" in content_lower or "<div" in content_lower:
            stripped = cls.strip_html_noise(content)
            if len(stripped.encode("utf-8")) > max_bytes:
                return stripped[:max_bytes] + "... [Truncated HTML by TokenShield]"
            return stripped

        # Plain text fallback
        if len(content.encode("utf-8")) > max_bytes:
            return content[:max_bytes] + "... [Truncated by TokenShield]"
        return content

    @classmethod
    def compress_tool_outputs(
        cls,
        messages: List[Dict[str, Any]],
        max_bytes: int = 4096,
        enable_dedup: bool = True,
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        """Compress tool payloads and replace exact repeated tool returns with hash references."""
        seen_payload_hashes = set()
        compressed_messages: List[Dict[str, Any]] = []
        payloads_compressed = 0
        duplicate_truncated = 0

        for msg in messages:
            role = msg.get("role")
            # Intercept tool responses
            if role in ("tool", "function") or "tool_call_id" in msg:
                content = msg.get("content", "")
                if not isinstance(content, str):
                    content = str(content)

                content_bytes = len(content.encode("utf-8"))

                # 1. Exact Duplicate Hash Caching
                if enable_dedup:
                    payload_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                    if payload_hash in seen_payload_hashes:
                        new_msg = dict(msg)
                        new_msg["content"] = f"[Duplicate Tool Output Ref: {payload_hash[:12]} - Truncated to avoid repetition]"
                        compressed_messages.append(new_msg)
                        duplicate_truncated += 1
                        continue
                    seen_payload_hashes.add(payload_hash)

                # 2. Oversized Payload Compression
                if content_bytes > max_bytes:
                    compressed_content = cls.compress_single_payload(content, max_bytes)
                    new_msg = dict(msg)
                    new_msg["content"] = compressed_content
                    compressed_messages.append(new_msg)
                    payloads_compressed += 1
                else:
                    compressed_messages.append(msg)
            else:
                compressed_messages.append(msg)

        return compressed_messages, payloads_compressed, duplicate_truncated


class PreExecutionEngine:
    """Unified pre-flight optimizer combining context trimming, deduplication, and token counting."""

    def __init__(self):
        self.config = get_config()
        self.trimmer = ContextTrimmerNode()
        self.deduplicator = PayloadDeduplicationEngine()

    @staticmethod
    def _get_encoding(model: str):
        """Retrieve tiktoken encoding with fallback."""
        try:
            return tiktoken.encoding_for_model(model)
        except Exception:
            return tiktoken.get_encoding("cl100k_base")

    @classmethod
    def count_tokens(cls, messages: List[Dict[str, Any]], model: str = "gpt-4o-mini") -> int:
        """Calculate token count of message history using tiktoken."""
        enc = cls._get_encoding(model)
        total = 0
        for msg in messages:
            # Approx 3 tokens per message role/delimiter + content tokens
            total += 3
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(enc.encode(content))
            elif isinstance(content, list):
                # Handle multimodal or list formatted content blocks
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        total += len(enc.encode(str(block["text"])))
                    else:
                        total += len(enc.encode(str(block)))
            # Tool calls metadata tokens
            if "tool_calls" in msg:
                total += len(enc.encode(str(msg["tool_calls"])))
        return total

    def process_messages(
        self,
        messages: List[Dict[str, Any]],
        max_turns: Optional[int] = None,
        max_tool_bytes: Optional[int] = None,
        enable_dedup: Optional[bool] = None,
        model: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], PreExecutionMetrics]:
        """Execute full pre-flight optimization pipeline and calculate token savings."""
        target_model = model or self.config.DEFAULT_MODEL
        target_turns = max_turns if max_turns is not None else self.config.SLIDING_WINDOW_TURNS
        target_bytes = max_tool_bytes if max_tool_bytes is not None else self.config.MAX_TOOL_PAYLOAD_BYTES
        target_dedup = enable_dedup if enable_dedup is not None else self.config.ENABLE_DEDUPLICATION

        # 1. Count original input tokens
        orig_tokens = self.count_tokens(messages, target_model)

        # 2. Context Window & System Prompt Trimming
        trimmed_msgs, turns_trimmed = self.trimmer.trim_history(messages, max_turns=target_turns)

        # 3. Tool Output Compression & Hash Deduplication
        optimized_msgs, payloads_comp, dup_trunc = self.deduplicator.compress_tool_outputs(
            trimmed_msgs,
            max_bytes=target_bytes,
            enable_dedup=target_dedup,
        )

        # 4. Count optimized tokens & compute net savings
        trimmed_tokens = self.count_tokens(optimized_msgs, target_model)
        tokens_saved = max(0, orig_tokens - trimmed_tokens)

        metrics = PreExecutionMetrics(
            original_prompt_tokens=orig_tokens,
            trimmed_prompt_tokens=trimmed_tokens,
            tokens_saved=tokens_saved,
            payloads_compressed=payloads_comp,
            duplicate_payloads_truncated=dup_trunc,
            turns_trimmed=turns_trimmed,
        )

        return optimized_msgs, metrics
