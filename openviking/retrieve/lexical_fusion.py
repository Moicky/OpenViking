# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Lexical/filename fusion for semantic find.

Blends normalized dense retrieval scores with lexical (grep) rank and
filename-token hits. All weights default to 0 (feature off) and are
configured via ``retrieval.lexical_fusion_weight`` / ``retrieval.filename_boost_weight``.
"""

import re
from typing import Dict, Iterable, List, Set

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_STOPWORDS = frozenset(
    "the and how are for with this that from what where when not its was can all out get".split()
)


def _looks_like_identifier(token: str) -> bool:
    """True for camelCase/snake_case-shaped tokens, not merely mixed-case words."""
    return "_" in token or any(c.islower() for c in token[:-1]) and any(
        c.isupper() for c in token[1:]
    )


def extract_identifiers(query: str, max_terms: int = 8) -> List[str]:
    """Extract dedicated search terms, identifier-shaped tokens first."""
    seen: Set[str] = set()
    terms: List[str] = []
    for token in _IDENTIFIER_RE.findall(query):
        key = token.lower()
        if key in _STOPWORDS or key in seen:
            continue
        seen.add(key)
        terms.append(token)
    terms.sort(key=lambda t: not _looks_like_identifier(t))  # stable sort
    return terms[:max_terms]


def filename_matches(uri: str, terms: Iterable[str]) -> bool:
    basename = uri.rsplit("/", 1)[-1].lower()
    return any(t.lower() in basename for t in terms)


def fuse_scores(
    dense_scores: Dict[str, float],
    lexical_ranking: List[str],
    filename_hits: Set[str],
    lexical_weight: float,
    filename_weight: float,
) -> Dict[str, Dict[str, float]]:
    """Return per-URI signal breakdown with a blended ``fused`` score.

    dense_norm is max-normalized; lexical contribution decays by rank;
    filename hits contribute a fixed boost. Dense keeps the remaining mass
    so fused stays in [0, 1].
    """
    max_dense = max(dense_scores.values(), default=0.0) or 1.0
    lexical_rank = {uri: index for index, uri in enumerate(lexical_ranking)}
    dense_weight = max(0.0, 1.0 - lexical_weight - filename_weight)

    fused: Dict[str, Dict[str, float]] = {}
    for uri in set(dense_scores) | set(lexical_rank) | set(filename_hits):
        dense_norm = dense_scores.get(uri, 0.0) / max_dense
        lexical = 1.0 / (1.0 + lexical_rank[uri]) if uri in lexical_rank else 0.0
        filename = 1.0 if uri in filename_hits else 0.0
        fused[uri] = {
            "dense_norm": dense_norm,
            "lexical": lexical,
            "filename": filename,
            "fused": dense_weight * dense_norm
            + lexical_weight * lexical
            + filename_weight * filename,
        }
    return fused
