# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0

"""Hierarchical retriever rerank behavior tests."""

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from openviking.core.context import ContextLevel
from openviking.retrieve.hierarchical_retriever import HierarchicalRetriever, RetrieverMode
from openviking.server.identity import RequestContext, Role
from openviking.storage.abstract_overview import render_abstract_overview
from openviking.utils.token_estimation import estimate_text_tokens
from openviking_cli.retrieve.types import ContextType, TypedQuery
from openviking_cli.session.user_id import UserIdentifier
from openviking_cli.utils.config import RerankConfig, RetrievalConfig


def _result(uri, score, level=2, abstract=None, **extra):
    result = {
        "uri": uri,
        "abstract": abstract if abstract is not None else uri.rsplit("/", 1)[-1],
        "_score": score,
        "level": level,
        "context_type": "resource",
    }
    result.update(extra)
    return result


class DummyEmbedResult:
    def __init__(self) -> None:
        self.dense_vector = [1.0]
        self.sparse_vector = {"hello": 1.0}


class DummyEmbedder:
    def prepare_embedding_input(self, text: str) -> str:
        return text

    def embed(self, _query: str, is_query: bool = False) -> DummyEmbedResult:
        return DummyEmbedResult()

    async def embed_async(self, text: str, is_query: bool = False) -> DummyEmbedResult:
        return self.embed(text, is_query=is_query)


class DummyStorage:
    def __init__(self) -> None:
        self.collection_name = "context"
        self.acl_manager = None
        self.search_calls = []
        self.child_search_calls = []

    def _acl_enabled(self, ctx: RequestContext) -> bool:
        return self.acl_manager is not None and self.acl_manager.is_enabled(ctx.account_id)

    async def collection_exists_bound(self) -> bool:
        return True

    async def search_in_tenant(
        self,
        ctx,
        query_vector=None,
        sparse_query_vector=None,
        context_type=None,
        target_directories=None,
        extra_filter=None,
        level=None,
        limit: int = 10,
        offset: int = 0,
    ):
        self.search_calls.append(
            {
                "ctx": ctx,
                "query_vector": query_vector,
                "sparse_query_vector": sparse_query_vector,
                "context_type": context_type,
                "target_directories": target_directories,
                "extra_filter": extra_filter,
                "level": level,
                "limit": limit,
                "offset": offset,
            }
        )
        return [
            _result("viking://resources/root-a", 0.2, level=1, abstract="root A"),
            _result("viking://resources/root-b", 0.8, level=1, abstract="root B"),
        ]

    async def search_children_in_tenant(
        self,
        ctx,
        parent_uri: str,
        query_vector=None,
        sparse_query_vector=None,
        context_type=None,
        target_directories=None,
        extra_filter=None,
        limit: int = 10,
    ):
        self.child_search_calls.append(
            {
                "ctx": ctx,
                "parent_uri": parent_uri,
                "query_vector": query_vector,
                "sparse_query_vector": sparse_query_vector,
                "context_type": context_type,
                "target_directories": target_directories,
                "extra_filter": extra_filter,
                "limit": limit,
            }
        )
        if parent_uri == "viking://resources":
            return [
                _result("viking://resources/file-a", 0.2, abstract="child A", category="doc"),
                _result("viking://resources/file-b", 0.8, abstract="child B", category="doc"),
            ]
        return []


class QuickSearchStorage(DummyStorage):
    def __init__(self, results):
        super().__init__()
        self.results = list(results)

    async def search_in_tenant(
        self,
        ctx,
        query_vector=None,
        sparse_query_vector=None,
        context_type=None,
        target_directories=None,
        extra_filter=None,
        level=None,
        limit: int = 10,
        offset: int = 0,
    ):
        self.search_calls.append(
            {
                "ctx": ctx,
                "query_vector": query_vector,
                "sparse_query_vector": sparse_query_vector,
                "context_type": context_type,
                "target_directories": target_directories,
                "extra_filter": extra_filter,
                "level": level,
                "limit": limit,
                "offset": offset,
            }
        )
        return [
            dict(result)
            for result in self.results
            if level is None or result.get("level", 2) in level
        ]

    async def search_children_in_tenant(
        self,
        ctx,
        parent_uri: str,
        query_vector=None,
        sparse_query_vector=None,
        context_type=None,
        target_directories=None,
        extra_filter=None,
        limit: int = 10,
    ):
        self.child_search_calls.append(
            {
                "ctx": ctx,
                "parent_uri": parent_uri,
                "query_vector": query_vector,
                "sparse_query_vector": sparse_query_vector,
                "context_type": context_type,
                "target_directories": target_directories,
                "extra_filter": extra_filter,
                "limit": limit,
            }
        )
        return [_result(f"{parent_uri}/should-not-be-returned", 1.0, abstract="child")]


class DirectChildProxy:
    async def search_children_in_tenant(
        self,
        parent_uri: str,
        query_vector=None,
        sparse_query_vector=None,
        context_type=None,
        target_directories=None,
        extra_filter=None,
        limit: int = 10,
    ):
        return [
            _result(f"{parent_uri}/file-a", 0.2, abstract="child A"),
            _result(f"{parent_uri}/file-b", 0.8, abstract="child B"),
        ]


class FakeRerankClient:
    def __init__(self, scores):
        self.scores = list(scores)
        self.calls = []
        self._cursor = 0

    def rerank_batch(self, query: str, documents: list[str]):
        self.calls.append((query, list(documents)))
        start = self._cursor
        end = start + len(documents)
        self._cursor = end
        return list(self.scores[start:end])


def _ctx() -> RequestContext:
    return RequestContext(user=UserIdentifier("acc1", "user1"), role=Role.USER)


def _query() -> TypedQuery:
    return TypedQuery(query="hello", context_type=ContextType.RESOURCE, intent="")


def _config() -> RerankConfig:
    return RerankConfig(ak="ak", sk="sk", threshold=0.1)


def test_retriever_initializes_rerank_client(monkeypatch):
    fake_client = FakeRerankClient([0.9, 0.1])

    monkeypatch.setattr(
        "openviking.retrieve.hierarchical_retriever.RerankClient.from_config",
        lambda config: fake_client,
    )

    storage = DummyStorage()
    retriever = HierarchicalRetriever(
        storage=storage,
        embedder=DummyEmbedder(),
        rerank_config=_config(),
    )

    assert retriever._rerank_client is fake_client


def test_rerank_max_input_tokens_accepts_zero_or_at_least_128():
    assert RerankConfig(max_input_tokens=0).max_input_tokens == 0
    with pytest.raises(ValueError, match="max_input_tokens"):
        RerankConfig(max_input_tokens=127)


@pytest.mark.asyncio
async def test_retrieve_uses_rerank_scores_in_thinking_mode(monkeypatch):
    fake_client = FakeRerankClient([0.95, 0.05, 0.11, 0.95])
    monkeypatch.setattr(
        "openviking.retrieve.hierarchical_retriever.RerankClient.from_config",
        lambda config: fake_client,
    )

    storage = DummyStorage()
    retriever = HierarchicalRetriever(
        storage=storage,
        embedder=DummyEmbedder(),
        rerank_config=_config(),
    )

    result = await retriever.retrieve(_query(), ctx=_ctx(), limit=2, mode=RetrieverMode.THINKING)

    assert [ctx.uri for ctx in result.matched_contexts] == [
        "viking://resources/file-b",
        "viking://resources/file-a",
    ]
    assert fake_client.calls[0] == ("hello", ["root A", "root B"])
    assert fake_client.calls[1] == ("hello", ["child A", "child B"])
    assert storage.search_calls[0]["level"] == [0, 1]


@pytest.mark.asyncio
async def test_rerank_scores_preserves_fallbacks_for_empty_documents(monkeypatch):
    fake_client = FakeRerankClient([0.95, 0.05])
    monkeypatch.setattr(
        "openviking.retrieve.hierarchical_retriever.RerankClient.from_config",
        lambda config: fake_client,
    )

    retriever = HierarchicalRetriever(
        storage=DummyStorage(),
        embedder=DummyEmbedder(),
        rerank_config=_config(),
    )

    scores = await retriever._rerank_scores(
        "hello",
        ["root A", "", "   ", "root D"],
        [0.2, 0.8, 0.7, 0.4],
    )

    assert scores == [0.95, 0.8, 0.7, 0.05]
    assert fake_client.calls == [("hello", ["root A", "root D"])]


@pytest.mark.asyncio
async def test_rerank_scores_does_not_truncate_by_default(monkeypatch):
    oversized_document = "summary-start " + ("填充内容" * 600) + " relevant-tail"
    fake_client = FakeRerankClient([0.95])
    monkeypatch.setattr(
        "openviking.retrieve.hierarchical_retriever.RerankClient.from_config",
        lambda config: fake_client,
    )

    retriever = HierarchicalRetriever(
        storage=DummyStorage(),
        embedder=DummyEmbedder(),
        rerank_config=RerankConfig(ak="ak", sk="sk"),
    )

    await retriever._rerank_scores("query", [oversized_document], [0.2])

    assert retriever.rerank_max_input_tokens == 0
    assert fake_client.calls == [("query", [oversized_document])]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "oversized_document",
    [
        "summary-start " + ("filler " * 600) + " relevant-tail",
        "摘要开头" + ("填充内容" * 600) + "相关结论",
    ],
)
async def test_rerank_scores_bounds_oversized_documents_and_preserves_tail(
    monkeypatch, oversized_document
):
    fake_client = FakeRerankClient([0.95])
    monkeypatch.setattr(
        "openviking.retrieve.hierarchical_retriever.RerankClient.from_config",
        lambda config: fake_client,
    )

    retriever = HierarchicalRetriever(
        storage=DummyStorage(),
        embedder=DummyEmbedder(),
        rerank_config=RerankConfig(ak="ak", sk="sk", max_input_tokens=128),
    )

    scores = await retriever._rerank_scores("query", [oversized_document], [0.2])

    assert scores == [0.95]
    rerank_query, rerank_documents = fake_client.calls[0]
    bounded_document = rerank_documents[0]
    assert estimate_text_tokens(rerank_query) + estimate_text_tokens(bounded_document) <= 128
    assert "summary-start" in bounded_document or "摘要开头" in bounded_document
    assert "relevant-tail" in bounded_document or "相关结论" in bounded_document
    assert bounded_document != oversized_document


@pytest.mark.asyncio
async def test_retrieve_falls_back_to_vector_scores_when_rerank_returns_none(monkeypatch):
    class NoneRerankClient(FakeRerankClient):
        def rerank_batch(self, query: str, documents: list[str]):
            self.calls.append((query, list(documents)))
            return None

    fake_client = NoneRerankClient([])
    monkeypatch.setattr(
        "openviking.retrieve.hierarchical_retriever.RerankClient.from_config",
        lambda config: fake_client,
    )

    storage = QuickSearchStorage([
        _result("viking://resources/a/deep-a.md", 0.2, abstract="deep A"),
        _result("viking://resources/b/deep-b.md", 0.8, abstract="deep B"),
    ])
    storage.acl_manager = SimpleNamespace(is_enabled=lambda _account_id: True)

    async def no_hierarchical_children(*_args, **_kwargs):
        return []

    storage.search_children_in_tenant = no_hierarchical_children
    retriever = HierarchicalRetriever(
        storage=storage,
        embedder=DummyEmbedder(),
        rerank_config=_config(),
    )

    result = await retriever.retrieve(_query(), ctx=_ctx(), limit=2, mode=RetrieverMode.THINKING)

    assert [ctx.uri for ctx in result.matched_contexts] == [
        "viking://resources/b/deep-b.md",
        "viking://resources/a/deep-a.md",
    ]
    assert [call["level"] for call in storage.search_calls] == [[0, 1], [2]]
    assert fake_client.calls


@pytest.mark.asyncio
async def test_rerank_scores_runs_blocking_client_off_event_loop():
    class SlowRerankClient:
        def __init__(self):
            self.thread_id = None

        def rerank_batch(self, query: str, documents: list[str]):
            self.thread_id = threading.get_ident()
            time.sleep(0.2)
            return [0.9 for _ in documents]

    retriever = HierarchicalRetriever(
        storage=DummyStorage(),
        embedder=DummyEmbedder(),
        rerank_config=None,
    )
    fake_client = SlowRerankClient()
    retriever._rerank_client = fake_client

    started = time.monotonic()
    rerank_task = asyncio.create_task(retriever._rerank_scores("hello", ["doc"], [0.1]))

    ticks = 0
    while time.monotonic() - started < 0.15:
        await asyncio.sleep(0.01)
        ticks += 1

    assert await rerank_task == [0.9]
    assert fake_client.thread_id != threading.get_ident()
    assert ticks >= 3


@pytest.mark.asyncio
async def test_quick_mode_uses_single_vector_search_without_rerank_or_recursion(monkeypatch):
    fake_client = FakeRerankClient([0.05, 0.95, 0.95])
    monkeypatch.setattr(
        "openviking.retrieve.hierarchical_retriever.RerankClient.from_config",
        lambda config: fake_client,
    )
    storage = QuickSearchStorage(
        [
            _result("viking://resources/root", 0.95, level=0, abstract="root abstract"),
            _result("viking://resources/file", 0.9, abstract="file abstract"),
            _result("viking://resources/dir", 0.85, level=1, abstract="dir overview"),
        ]
    )

    retriever = HierarchicalRetriever(
        storage=storage,
        embedder=DummyEmbedder(),
        rerank_config=_config(),
    )

    result = await retriever.retrieve(_query(), ctx=_ctx(), limit=3, mode=RetrieverMode.QUICK)

    assert [ctx.uri for ctx in result.matched_contexts] == [
        "viking://resources/root/.abstract.md",
        "viking://resources/file",
        "viking://resources/dir/.overview.md",
    ]
    assert [ctx.level for ctx in result.matched_contexts] == [0, 2, 1]
    assert [ctx.score for ctx in result.matched_contexts] == [
        pytest.approx(0.95),
        pytest.approx(0.9),
        pytest.approx(0.85),
    ]
    assert len(storage.search_calls) == 1
    assert storage.search_calls[0]["limit"] == retriever.GLOBAL_SEARCH_TOPK
    assert storage.search_calls[0]["extra_filter"] is None
    assert storage.search_calls[0]["level"] is None
    assert storage.child_search_calls == []
    assert fake_client.calls == []


@pytest.mark.asyncio
async def test_quick_mode_pushes_explicit_level_filter_to_vector_search():
    storage = QuickSearchStorage(
        [
            _result("viking://resources/root", 0.99, level=0, abstract="root abstract"),
            _result("viking://resources/dir", 0.98, level=1, abstract="dir overview"),
            _result("viking://resources/file-a", 0.5, abstract="file A"),
            _result("viking://resources/file-b", 0.7, abstract="file B"),
        ]
    )
    retriever = HierarchicalRetriever(
        storage=storage,
        embedder=DummyEmbedder(),
        rerank_config=None,
    )

    result = await retriever.retrieve(
        _query(),
        ctx=_ctx(),
        limit=3,
        mode=RetrieverMode.QUICK,
        scope_dsl={"op": "must", "field": "category", "conds": ["doc"]},
        level=[2],
    )

    assert [ctx.uri for ctx in result.matched_contexts] == [
        "viking://resources/file-b",
        "viking://resources/file-a",
    ]
    assert len(storage.search_calls) == 1
    assert storage.search_calls[0]["limit"] == retriever.GLOBAL_SEARCH_TOPK
    assert storage.search_calls[0]["extra_filter"] == {
        "op": "must",
        "field": "category",
        "conds": ["doc"],
    }
    assert storage.search_calls[0]["level"] == [2]
    assert storage.child_search_calls == []


@pytest.mark.asyncio
async def test_quick_mode_threshold_uses_raw_vector_score():
    storage = QuickSearchStorage(
        [
            _result("viking://resources/high", 0.91, abstract="high"),
            _result("viking://resources/exact", 0.9, abstract="exact"),
        ]
    )
    retriever = HierarchicalRetriever(
        storage=storage,
        embedder=DummyEmbedder(),
        rerank_config=None,
    )

    strict_result = await retriever.retrieve(
        _query(),
        ctx=_ctx(),
        limit=2,
        mode=RetrieverMode.QUICK,
        score_threshold=0.9,
    )
    inclusive_result = await retriever.retrieve(
        _query(),
        ctx=_ctx(),
        limit=2,
        mode=RetrieverMode.QUICK,
        score_threshold=0.9,
        score_gte=True,
    )

    assert [ctx.uri for ctx in strict_result.matched_contexts] == ["viking://resources/high"]
    assert [ctx.uri for ctx in inclusive_result.matched_contexts] == [
        "viking://resources/high",
        "viking://resources/exact",
    ]


@pytest.mark.asyncio
async def test_quick_mode_keeps_scores_pure_when_hotness_and_propagation_configured(monkeypatch):
    monkeypatch.setattr(
        "openviking.retrieve.hierarchical_retriever.hotness_score",
        lambda *args, **kwargs: pytest.fail("hotness_score should not be called in QUICK mode"),
    )
    storage = QuickSearchStorage(
        [
            _result(
                "viking://resources/file-a",
                0.8,
                abstract="file A",
                active_count=100,
                updated_at="2026-01-01T00:00:00+00:00",
            )
        ]
    )
    retriever = HierarchicalRetriever(
        storage=storage,
        embedder=DummyEmbedder(),
        rerank_config=None,
        retrieval_config=RetrievalConfig(hotness_alpha=0.5, score_propagation_alpha=0.1),
    )

    result = await retriever.retrieve(_query(), ctx=_ctx(), limit=1, mode=RetrieverMode.QUICK)

    assert result.matched_contexts[0].score == pytest.approx(0.8)
    assert storage.child_search_calls == []


@pytest.mark.asyncio
async def test_score_propagation_alpha_uses_configured_weight():
    retriever = HierarchicalRetriever(
        storage=DummyStorage(),
        embedder=None,
        rerank_config=None,
        retrieval_config=RetrievalConfig(score_propagation_alpha=1.0),
    )

    candidates = await retriever._recursive_search(
        vector_proxy=DirectChildProxy(),
        query="hello",
        query_vector=None,
        sparse_query_vector=None,
        starting_points=[("viking://resources", 0.4)],
        limit=1,
        mode=RetrieverMode.QUICK,
    )

    assert candidates[0]["uri"] == "viking://resources/file-b"
    assert candidates[0]["_final_score"] == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_default_retrieval_config_uses_semantic_score_without_hotness(monkeypatch):
    monkeypatch.setattr(
        "openviking.retrieve.hierarchical_retriever.hotness_score",
        lambda *args, **kwargs: pytest.fail("hotness_score should not be called by default"),
    )
    retriever = HierarchicalRetriever(
        storage=DummyStorage(),
        embedder=None,
        rerank_config=None,
    )

    result = await retriever._convert_to_matched_contexts(
        [_result("viking://resources/file-a", 1.0, abstract="child A")],
        ctx=_ctx(),
    )

    assert result[0].score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_retrieval_hotness_alpha_blends_when_configured(monkeypatch):
    monkeypatch.setattr(
        "openviking.retrieve.hierarchical_retriever.hotness_score",
        lambda *args, **kwargs: 0.5,
    )
    retriever = HierarchicalRetriever(
        storage=DummyStorage(),
        embedder=None,
        rerank_config=None,
        retrieval_config=RetrievalConfig(hotness_alpha=0.2),
    )

    result = await retriever._convert_to_matched_contexts(
        [_result("viking://resources/file-a", 1.0, abstract="child A")],
        ctx=_ctx(),
    )

    assert result[0].score == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_convert_to_matched_contexts_propagates_search_tags():
    retriever = HierarchicalRetriever(
        storage=DummyStorage(),
        embedder=None,
        rerank_config=None,
    )

    result = await retriever._convert_to_matched_contexts(
        [
            _result(
                "viking://resources/file-a",
                1.0,
                abstract="child A",
                search_tags=["default", "team=infra", "bad=", "project=viking"],
            )
        ],
        ctx=_ctx(),
    )

    assert result[0].search_tags == ["team=infra", "project=viking"]


@pytest.mark.asyncio
async def test_convert_to_matched_contexts_defaults_tags_and_body_previews():
    retriever = HierarchicalRetriever(
        storage=DummyStorage(),
        embedder=None,
        rerank_config=None,
    )
    uri = "viking://resources/demo"
    metadata = {
        "source": {"kind": "http", "uri": "https://example.com/private.pdf"},
        "generated_by": {"component": "SemanticProcessor", "trigger": "ingest"},
    }
    markdown = "---\ntitle: User document\n---\n\nVisible body."

    result = await retriever._convert_to_matched_contexts(
        [
            _result(
                uri,
                1.0,
                level=int(ContextLevel.ABSTRACT),
                abstract=render_abstract_overview(
                    ContextLevel.ABSTRACT, uri, "Visible abstract.", metadata
                ),
            ),
            _result(
                uri,
                0.9,
                level=int(ContextLevel.OVERVIEW),
                abstract=render_abstract_overview(
                    ContextLevel.OVERVIEW, uri, "# Visible overview", metadata
                ),
            ),
            _result("viking://resources/demo.md", 0.8, level=2, abstract=markdown),
        ],
        ctx=_ctx(),
    )

    assert [item.search_tags for item in result] == [[], [], []]
    assert [item.abstract for item in result] == [
        "Visible abstract.",
        "# Visible overview",
        markdown,
    ]


class OrphanSubtreeStorage(DummyStorage):
    """Subtree whose intermediate directories have no indexed records.

    Mirrors the real memory tree: files live at
    ``<target>/<peer>/<topic>.md`` but neither ``<target>`` nor
    ``<target>/<peer>`` has an L0/L1 record. Recursive descent walks exact
    parent_uri links, so it dead-ends immediately; only a flat subtree
    search can reach the files.
    """

    LEAF = "viking://user/u/memories/preferences/user/pref.md"

    async def search_in_tenant(
        self,
        ctx,
        query_vector=None,
        sparse_query_vector=None,
        context_type=None,
        target_directories=None,
        extra_filter=None,
        level=None,
        limit: int = 10,
        offset: int = 0,
    ):
        self.search_calls.append({"level": level, "target_directories": target_directories})
        # No L0/L1 directory records exist anywhere in this subtree.
        if level and set(level) <= {0, 1}:
            return []
        return [_result(self.LEAF, 0.9, level=2, abstract="prefers signed commits",
                        context_type="memory")]

    async def search_children_in_tenant(self, ctx, parent_uri: str, **kwargs):
        self.child_search_calls.append({"parent_uri": parent_uri})
        return []  # dead-end: no record links target -> peer dir -> file


@pytest.mark.asyncio
async def test_thinking_mode_reaches_files_when_intermediate_dirs_are_unindexed(monkeypatch):
    """Bug B: THINKING mode must not lose results QUICK mode would return."""
    monkeypatch.setattr(
        "openviking.retrieve.hierarchical_retriever.RerankClient.from_config",
        lambda config: FakeRerankClient([0.9]),
    )
    storage = OrphanSubtreeStorage()
    retriever = HierarchicalRetriever(
        storage=storage, embedder=DummyEmbedder(), rerank_config=_config()
    )

    query = TypedQuery(
        query="hello",
        context_type=None,
        intent="",
        target_directories=["viking://user/u/memories/preferences"],
    )
    result = await retriever.retrieve(
        query, ctx=_ctx(), limit=5, mode=RetrieverMode.THINKING, score_threshold=0.0
    )

    uris = [c.uri for c in result.matched_contexts]
    assert OrphanSubtreeStorage.LEAF in uris, (
        "THINKING mode dead-ended on unindexed intermediate dirs; "
        f"got {uris}"
    )
    assert result.matched_contexts[0].context_type == ContextType.MEMORY


class ConcurrencyProbeRerankClient:
    """Records how many rerank calls are in flight at once.

    ``_rerank_scores`` dispatches through ``asyncio.to_thread``, so real
    concurrency shows up as overlapping calls on worker threads.
    """

    def __init__(self, hold_seconds: float = 0.05):
        self._hold = hold_seconds
        self._lock = threading.Lock()
        self._in_flight = 0
        self.max_in_flight = 0
        self.calls = 0

    def rerank_batch(self, query: str, documents: list[str]):
        with self._lock:
            self._in_flight += 1
            self.calls += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            time.sleep(self._hold)
            return [0.5] * len(documents)
        finally:
            with self._lock:
                self._in_flight -= 1


class WideTreeStorage(DummyStorage):
    """A root whose children are directories, each with its own children.

    Descending it makes the retriever rerank several sibling result sets in the
    same batch, which is where the calls used to serialize.
    """

    ROOTS = [f"viking://resources/dir{i}" for i in range(4)]

    async def search_in_tenant(self, ctx, level=None, **kwargs):
        if level and set(level) <= {0, 1}:
            return [_result(uri, 0.9, level=1) for uri in self.ROOTS]
        return []

    async def search_children_in_tenant(self, ctx, parent_uri: str, **kwargs):
        self.child_search_calls.append({"parent_uri": parent_uri})
        if parent_uri in self.ROOTS:
            return [_result(f"{parent_uri}/file{i}.md", 0.8, abstract="body") for i in range(3)]
        return []


@pytest.mark.asyncio
async def test_sibling_rerank_calls_run_concurrently(monkeypatch):
    """Reranks within one descent batch must overlap, not serialize.

    With a hosted reranker each call is a network round trip, so serializing
    the batch multiplies the whole request's latency by the fan-out width.
    """
    probe = ConcurrencyProbeRerankClient()
    monkeypatch.setattr(
        "openviking.retrieve.hierarchical_retriever.RerankClient.from_config",
        lambda config: probe,
    )
    retriever = HierarchicalRetriever(
        storage=WideTreeStorage(), embedder=DummyEmbedder(), rerank_config=_config()
    )

    await retriever.retrieve(
        TypedQuery(query="hello", context_type=None, intent="", target_directories=[]),
        ctx=_ctx(),
        limit=10,
        mode=RetrieverMode.THINKING,
        score_threshold=0.0,
    )

    assert probe.calls > 1, "test tree should trigger several rerank calls"
    assert probe.max_in_flight > 1, (
        "sibling rerank calls serialized; expected overlap within a descent batch "
        f"(calls={probe.calls}, max_in_flight={probe.max_in_flight})"
    )
