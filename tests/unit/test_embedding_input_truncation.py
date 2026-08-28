# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""The embedding input guard must bound *real* tokens, not a chars/4 guess."""

import hashlib

import pytest

from openviking.utils.embedding_input import (
    EMBEDDING_TRUNCATION_SUFFIX,
    truncate_embedding_input,
)

tiktoken = pytest.importorskip("tiktoken")

MAX_TOKENS = 7500


def _lockfile_shaped_text() -> str:
    """Dense text in the shape that broke this: integrity hashes and versions.

    A pnpm-lock.yaml tokenizes at ~2.1 chars/token, so a chars/4 estimate lets
    roughly twice the intended budget through.
    """
    lines = []
    for i in range(20000):
        digest = hashlib.sha512(str(i).encode()).hexdigest()
        lines.append(f"  /pkg-{i}@1.{i}.2:\n    resolution: {{integrity: sha512-{digest}}}")
    return "\n".join(lines)


def test_truncated_text_fits_the_budget_for_dense_input():
    encoding = tiktoken.get_encoding("cl100k_base")
    text = _lockfile_shaped_text()
    assert len(encoding.encode(text)) > MAX_TOKENS, "fixture must exceed the budget"

    truncated = truncate_embedding_input(text, MAX_TOKENS)

    assert truncated.endswith(EMBEDDING_TRUNCATION_SUFFIX)
    # The suffix has to fit inside the budget too -- it is sent to the provider.
    assert len(encoding.encode(truncated)) <= MAX_TOKENS


def test_short_text_is_returned_unchanged():
    assert truncate_embedding_input("hello world", MAX_TOKENS) == "hello world"
