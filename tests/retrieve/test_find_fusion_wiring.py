# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
import asyncio

from openviking.storage.viking_fs import apply_lexical_fusion
from openviking_cli.retrieve.types import ContextType, MatchedContext
from openviking_cli.utils.config import RetrievalConfig


def test_fusion_fields_default_off():
    cfg = RetrievalConfig()
    assert cfg.lexical_fusion_weight == 0.0
    assert cfg.filename_boost_weight == 0.0
    assert cfg.graph_expansion_hops == 0


def _dense_matches():
    return [
        MatchedContext(
            uri="viking://r/locales/de.json",
            context_type=ContextType.RESOURCE,
            score=0.9,
        ),
        MatchedContext(
            uri="viking://r/lib/aws/sqs.ts",
            context_type=ContextType.RESOURCE,
            score=0.5,
        ),
    ]


async def _fake_grep(pattern):
    return ["viking://r/lib/aws/sqs.ts", "viking://r/fiscal/fiskaly.ts"]


async def _fake_abstract(uri):
    return "abstract for " + uri


def test_apply_lexical_fusion_reranks_and_appends():
    fused = asyncio.run(
        apply_lexical_fusion(
            _dense_matches(),
            terms=["sqs", "fiskaly"],
            grep_uris=_fake_grep,
            read_abstract=_fake_abstract,
            lexical_weight=0.3,
            filename_weight=0.1,
            limit=5,
        )
    )
    uris = [m.uri for m in fused]
    assert uris[0] == "viking://r/lib/aws/sqs.ts"
    assert "viking://r/fiscal/fiskaly.ts" in uris
    assert fused[0].signals["lexical"] > 0


def test_apply_lexical_fusion_disabled_returns_dense():
    dense = _dense_matches()
    fused = asyncio.run(
        apply_lexical_fusion(
            dense,
            terms=["sqs"],
            grep_uris=_fake_grep,
            read_abstract=_fake_abstract,
            lexical_weight=0.0,
            filename_weight=0.0,
            limit=1,
        )
    )
    assert fused == dense[:1]


def test_apply_lexical_fusion_survives_grep_failure():
    async def broken_grep(pattern):
        raise RuntimeError("boom")

    dense = _dense_matches()
    fused = asyncio.run(
        apply_lexical_fusion(
            dense,
            terms=["sqs"],
            grep_uris=broken_grep,
            read_abstract=_fake_abstract,
            lexical_weight=0.3,
            filename_weight=0.1,
            limit=5,
        )
    )
    assert fused == dense


def test_lexical_only_hits_keep_their_namespace_context_type():
    """Regression: lexical-only hits must not all be labelled 'resource'.

    apply_lexical_fusion synthesises a MatchedContext for URIs that grep found
    but dense retrieval did not return. Hard-coding ContextType.RESOURCE there
    mislabels memory (and skill) files, and recall's _extract_memories reads
    only result.memories -- so mislabelled memories are silently dropped.
    """

    async def grep_hits(pattern):
        return [
            "viking://user/opencode/memories/preferences/user/git_worktree_setup.md",
            "viking://agent/skills/deploy/SKILL.md",
            "viking://resources/repo/src/main.ts",
        ]

    async def abstract_of(uri):
        return "abstract for " + uri

    fused = asyncio.run(
        apply_lexical_fusion(
            [],
            terms=["worktree", "deploy", "main"],
            grep_uris=grep_hits,
            read_abstract=abstract_of,
            lexical_weight=0.3,
            filename_weight=0.1,
            limit=10,
        )
    )
    by_uri = {m.uri: m.context_type for m in fused}
    assert by_uri[
        "viking://user/opencode/memories/preferences/user/git_worktree_setup.md"
    ] == ContextType.MEMORY
    assert by_uri["viking://agent/skills/deploy/SKILL.md"] == ContextType.SKILL
    assert by_uri["viking://resources/repo/src/main.ts"] == ContextType.RESOURCE


def test_missing_target_directory_is_not_treated_as_lexical_failure():
    """A missing grep target means 'no lexical hits', not a failure.

    Memory-type directories only exist once that type has been written, so
    grep raising NotFoundError is a normal condition. It must not emit an
    exception traceback nor discard the dense results' fusion scoring.
    """
    from openviking_cli.exceptions import NotFoundError

    async def missing_target_grep(pattern):
        raise NotFoundError("viking://user/u/memories/experiences", "file")

    async def abstract_of(uri):
        return "abstract"

    dense = [
        MatchedContext(
            uri="viking://user/u/memories/experiences/a.md",
            context_type=ContextType.MEMORY,
            score=0.8,
        )
    ]
    fused = asyncio.run(
        apply_lexical_fusion(
            dense,
            terms=["anything"],
            grep_uris=missing_target_grep,
            read_abstract=abstract_of,
            lexical_weight=0.3,
            filename_weight=0.1,
            limit=5,
        )
    )
    # Dense results survive, and fusion scoring still ran (score recomputed).
    assert [m.uri for m in fused] == ["viking://user/u/memories/experiences/a.md"]
    assert fused[0].signals, "fusion signals should still be attached"
