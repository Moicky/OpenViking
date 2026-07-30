# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
from openviking.retrieve.lexical_fusion import (
    extract_identifiers,
    filename_matches,
    fuse_scores,
)


def test_extracts_identifier_shaped_tokens_first():
    terms = extract_identifiers(
        "receipt creation fiscal signing Fiskaly initiateReceiptSignature order paid"
    )
    assert "initiateReceiptSignature" in terms
    assert terms.index("initiateReceiptSignature") == 0


def test_drops_stopwords_and_dedupes():
    terms = extract_identifiers("how are the receipts and receipts created")
    lowered = [t.lower() for t in terms]
    assert "how" not in lowered
    assert lowered.count("receipts") == 1


def test_caps_term_count():
    query = " ".join(f"uniqueterm{i}" for i in range(20))
    assert len(extract_identifiers(query)) == 8


def test_filename_matches():
    assert filename_matches("viking://r/lib/aws/sqs.ts", ["SQS", "fiskaly"])
    assert not filename_matches("viking://r/locales/de.json", ["sqs", "fiskaly"])


def test_fuse_blends_dense_lexical_and_filename():
    fused = fuse_scores(
        dense_scores={"a": 0.9, "b": 0.5},
        lexical_ranking=["b"],
        filename_hits={"b"},
        lexical_weight=0.3,
        filename_weight=0.1,
    )
    assert fused["b"]["fused"] > fused["b"]["dense_norm"] * 0.6
    assert fused["a"]["lexical"] == 0.0
    assert fused["b"]["filename"] == 1.0


def test_fuse_with_no_lexical_hits_preserves_dense_order():
    fused = fuse_scores(
        dense_scores={"a": 0.9, "b": 0.5},
        lexical_ranking=[],
        filename_hits=set(),
        lexical_weight=0.3,
        filename_weight=0.1,
    )
    assert fused["a"]["fused"] > fused["b"]["fused"]
