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
