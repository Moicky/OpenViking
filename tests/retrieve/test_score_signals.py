# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
import asyncio

from openviking.retrieve.hierarchical_retriever import HierarchicalRetriever


def test_matched_context_carries_signals():
    retriever = HierarchicalRetriever.__new__(HierarchicalRetriever)
    retriever.hotness_alpha = 0.0
    candidates = [
        {
            "uri": "viking://resources/r/a.ts",
            "_final_score": 0.42,
            "context_type": "resource",
            "level": 2,
        }
    ]
    matched = asyncio.run(
        retriever._convert_to_matched_contexts(candidates, ctx=None, apply_hotness=False)
    )
    assert matched[0].signals["retrieval"] == 0.42
    assert matched[0].signals["final"] == matched[0].score


def test_signals_include_hotness_when_applied():
    retriever = HierarchicalRetriever.__new__(HierarchicalRetriever)
    retriever.hotness_alpha = 0.5
    candidates = [
        {
            "uri": "viking://resources/r/a.ts",
            "_final_score": 0.8,
            "context_type": "resource",
            "level": 2,
            "active_count": 3,
            "updated_at": "2026-07-01T00:00:00+00:00",
        }
    ]
    matched = asyncio.run(
        retriever._convert_to_matched_contexts(candidates, ctx=None, apply_hotness=True)
    )
    assert "hotness" in matched[0].signals
    assert matched[0].signals["final"] == matched[0].score
