# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Helpers for bounding text sent to embedding providers."""

from __future__ import annotations

import math
from functools import lru_cache

EMBEDDING_TRUNCATION_SUFFIX = "\n...(truncated for embedding)"

# A lockfile tokenizes at ~2.1 chars/token and a base64 blob nearer 1.4, so the
# prose-shaped 4-chars/token guess overshoots by 2x on exactly the files that are
# large enough to matter: pnpm-lock.yaml truncated to "7500 estimated" tokens is
# 14143 real ones, and the provider rejects the whole request with HTTP 400. Only
# a real tokenizer bounds this; the divisor below is the no-tiktoken fallback and
# is deliberately pessimistic, because under-filling an embedding costs a little
# recall while over-filling it drops the file from the index entirely.
_FALLBACK_CHARS_PER_TOKEN = 2


@lru_cache(maxsize=1)
def _encoding():
    """cl100k_base, or None when tiktoken is unavailable.

    tiktoken is only a ``benchmark`` extra of this package, so it is present in
    practice (litellm pins it) but must not be a hard import.
    """
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def estimate_embedding_input_tokens(text: str) -> int:
    """Count tokens for the raw text embedding input guard."""
    if not text:
        return 0
    encoding = _encoding()
    if encoding is not None:
        return max(1, len(encoding.encode(text, disallowed_special=())))
    cjk_chars = sum(
        1
        for char in text
        if "一" <= char <= "鿿"
        or "぀" <= char <= "ヿ"
        or "가" <= char <= "힯"
    )
    other_chars = len(text) - cjk_chars
    return max(1, cjk_chars + math.ceil(other_chars / _FALLBACK_CHARS_PER_TOKEN))


def truncate_embedding_input(
    text: str,
    max_tokens: int,
    suffix: str = EMBEDDING_TRUNCATION_SUFFIX,
) -> str:
    """Trim raw text so the result fits ``max_tokens``, suffix included."""
    if not text:
        return text
    if max_tokens <= 0:
        return suffix.lstrip()

    encoding = _encoding()
    if encoding is not None:
        tokens = encoding.encode(text, disallowed_special=())
        if len(tokens) <= max_tokens:
            return text
        budget = max_tokens - len(encoding.encode(suffix, disallowed_special=()))
        if budget <= 0:
            return suffix.lstrip()
        # Slicing tokens can cut a multi-byte character; tiktoken replaces the
        # dangling bytes rather than raising.
        return encoding.decode(tokens[:budget]).rstrip() + suffix

    if estimate_embedding_input_tokens(text) <= max_tokens:
        return text
    budget = max_tokens - estimate_embedding_input_tokens(suffix)
    if budget <= 0:
        return suffix.lstrip()
    low = 0
    high = len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_embedding_input_tokens(text[:mid]) <= budget:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip() + suffix


def resolve_embedding_max_input_tokens(
    config: dict[str, object] | None,
    default: int | None = None,
) -> int | None:
    """Read and normalize max_input_tokens from an embedder config dict."""
    raw_value = (config or {}).get("max_input_tokens", default)
    if raw_value is None:
        return default

    try:
        max_tokens = int(raw_value)
    except (TypeError, ValueError):
        return default

    if max_tokens <= 0:
        return default
    return max_tokens
