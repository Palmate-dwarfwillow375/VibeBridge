from __future__ import annotations

from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coerce_int(value: Any) -> int:
    try:
        if value is None or value == "":
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _pick_first_positive(*values: Any) -> int:
    for value in values:
        candidate = _coerce_int(value)
        if candidate > 0:
            return candidate
    return 0


def _usage_total(usage: dict[str, Any]) -> int:
    total_tokens = _pick_first_positive(
        usage.get("total_tokens"),
        usage.get("totalTokens"),
    )
    if total_tokens > 0:
        return total_tokens

    return sum((
        _pick_first_positive(usage.get("input_tokens"), usage.get("inputTokens")),
        _pick_first_positive(
            usage.get("cached_input_tokens"),
            usage.get("cachedInputTokens"),
            usage.get("cache_read_input_tokens"),
            usage.get("cacheReadInputTokens"),
        ),
        _pick_first_positive(usage.get("output_tokens"), usage.get("outputTokens")),
        _pick_first_positive(
            usage.get("reasoning_output_tokens"),
            usage.get("reasoningOutputTokens"),
        ),
    ))


def extract_codex_token_budget(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize Codex token usage into the frontend token-budget shape.

    Codex session logs expose both:
    - total_token_usage: cumulative lifetime usage for the whole thread
    - last_token_usage: tokens used by the most recent turn

    For a "context window usage" meter we want the current-turn / latest-turn
    footprint, not the cumulative lifetime spend. So prefer last_token_usage.
    """
    if not isinstance(payload, dict):
        return None

    normalized = payload
    if payload.get("type") == "token_count" and isinstance(payload.get("info"), dict):
        normalized = payload["info"]
    elif isinstance(payload.get("usage"), dict):
        normalized = payload["usage"]

    current_usage = _as_dict(
        normalized.get("last_token_usage")
        or normalized.get("lastUsage")
        or normalized.get("last_usage")
    )
    cumulative_usage = _as_dict(
        normalized.get("total_token_usage")
        or normalized.get("totalUsage")
        or normalized.get("total_usage")
    )

    total = _pick_first_positive(
        normalized.get("model_context_window"),
        normalized.get("modelContextWindow"),
        normalized.get("context_window"),
        normalized.get("contextWindow"),
    )
    if total <= 0:
        return None

    used = _usage_total(current_usage)
    if used <= 0:
        used = _usage_total(normalized)
    if used <= 0:
        used = _usage_total(cumulative_usage)

    input_tokens = _pick_first_positive(
        current_usage.get("input_tokens"),
        current_usage.get("inputTokens"),
        normalized.get("input_tokens"),
        normalized.get("inputTokens"),
        cumulative_usage.get("input_tokens"),
        cumulative_usage.get("inputTokens"),
    )
    cached_input_tokens = _pick_first_positive(
        current_usage.get("cached_input_tokens"),
        current_usage.get("cachedInputTokens"),
        current_usage.get("cache_read_input_tokens"),
        current_usage.get("cacheReadInputTokens"),
        normalized.get("cached_input_tokens"),
        normalized.get("cachedInputTokens"),
        normalized.get("cache_read_input_tokens"),
        normalized.get("cacheReadInputTokens"),
        cumulative_usage.get("cached_input_tokens"),
        cumulative_usage.get("cachedInputTokens"),
        cumulative_usage.get("cache_read_input_tokens"),
        cumulative_usage.get("cacheReadInputTokens"),
    )
    output_tokens = _pick_first_positive(
        current_usage.get("output_tokens"),
        current_usage.get("outputTokens"),
        normalized.get("output_tokens"),
        normalized.get("outputTokens"),
        cumulative_usage.get("output_tokens"),
        cumulative_usage.get("outputTokens"),
    )
    reasoning_output_tokens = _pick_first_positive(
        current_usage.get("reasoning_output_tokens"),
        current_usage.get("reasoningOutputTokens"),
        normalized.get("reasoning_output_tokens"),
        normalized.get("reasoningOutputTokens"),
        cumulative_usage.get("reasoning_output_tokens"),
        cumulative_usage.get("reasoningOutputTokens"),
    )

    return {
        "used": used,
        "total": total,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "cachedInputTokens": cached_input_tokens,
        "reasoningOutputTokens": reasoning_output_tokens,
        "breakdown": {
            "input": input_tokens,
            "cacheCreation": 0,
            "cacheRead": cached_input_tokens,
            "output": output_tokens,
            "reasoning": reasoning_output_tokens,
        },
    }
