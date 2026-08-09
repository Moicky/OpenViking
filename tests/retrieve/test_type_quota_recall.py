# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0

import asyncio
from types import SimpleNamespace

from openviking.retrieve.type_quota_recall import search_type_quota_recall
from openviking.server.identity import RequestContext, Role
from openviking_cli.session.user_id import UserIdentifier


class _FakeFindResult:
    def __init__(self, memories=None):
        self.memories = memories or []


async def test_independent_type_searches_start_concurrently():
    started_targets: list[str] = []
    all_started = asyncio.Event()

    async def fake_find(**kwargs):
        started_targets.append(kwargs["target_uri"])
        if len(started_targets) == 4:
            all_started.set()
        await all_started.wait()
        return _FakeFindResult()

    service = SimpleNamespace(
        search=SimpleNamespace(find=fake_find),
        fs=SimpleNamespace(),
    )
    ctx = RequestContext(
        user=UserIdentifier.the_default_user("test_user"),
        role=Role.USER,
        actor_peer_id="current",
    )

    result = await asyncio.wait_for(
        search_type_quota_recall(
            service=service,
            ctx=ctx,
            query="parallel recall",
            peer_scope="actor",
            quotas={
                "events": 1,
                "entities": 1,
                "preferences": 0,
                "experiences": 0,
            },
        ),
        timeout=1.0,
    )

    assert set(started_targets) == {
        "viking://user/test_user/memories/events",
        "viking://user/test_user/peers/current/memories/events",
        "viking://user/test_user/memories/entities",
        "viking://user/test_user/peers/current/memories/entities",
    }
    assert result.stats["searched"] == {
        "events": 0,
        "entities": 0,
        "preferences": 0,
        "experiences": 0,
    }


async def test_parallel_search_preserves_type_order():
    async def fake_find(**kwargs):
        target_uri = kwargs["target_uri"]
        memory_type = target_uri.rsplit("/", 1)[-1]
        if memory_type == "events":
            await asyncio.sleep(0.02)
        if "/peers/" in target_uri:
            return _FakeFindResult()
        return _FakeFindResult(
            [
                {
                    "uri": f"{target_uri}/{memory_type}.md",
                    "score": 0.9,
                    "abstract": f"{memory_type} abstract",
                }
            ]
        )

    async def fake_read(uri, **kwargs):
        del kwargs
        return f"content for {uri}"

    service = SimpleNamespace(
        search=SimpleNamespace(find=fake_find),
        fs=SimpleNamespace(read=fake_read),
    )
    ctx = RequestContext(
        user=UserIdentifier.the_default_user("test_user"),
        role=Role.USER,
        actor_peer_id="current",
    )

    result = await search_type_quota_recall(
        service=service,
        ctx=ctx,
        query="deterministic recall",
        peer_scope="actor",
        quotas={
            "events": 1,
            "entities": 1,
            "preferences": 0,
            "experiences": 0,
        },
    )

    assert [entry.type for entry in result.entries] == ["events", "entities"]
    assert [entry.rank for entry in result.entries] == [1, 1]


async def test_recall_hides_persisted_memory_fields_metadata():
    memory_uri = "viking://user/test_user/memories/events/example.md"
    raw_memory = """Visible memory body

<!-- MEMORY_FIELDS
{
  "event_name": "internal-event",
  "user_id": "test_user",
  "memory_type": "events"
}
-->"""

    async def fake_find(**kwargs):
        if kwargs["target_uri"].endswith("/events") and "/peers/" not in kwargs["target_uri"]:
            return _FakeFindResult([{"uri": memory_uri, "score": 0.9}])
        return _FakeFindResult()

    async def fake_read(uri, **kwargs):
        del kwargs
        assert uri == memory_uri
        return raw_memory

    service = SimpleNamespace(
        search=SimpleNamespace(find=fake_find),
        fs=SimpleNamespace(read=fake_read),
    )
    ctx = RequestContext(
        user=UserIdentifier.the_default_user("test_user"),
        role=Role.USER,
        actor_peer_id="current",
    )

    result = await search_type_quota_recall(
        service=service,
        ctx=ctx,
        query="visible memory",
        peer_scope="actor",
        quotas={"events": 1, "entities": 0, "preferences": 0, "experiences": 0},
        max_chars=10_000,
    )

    assert len(result.entries) == 1
    assert result.entries[0].content == "Visible memory body"
    assert "Visible memory body" in result.rendered
    assert "MEMORY_FIELDS" not in result.rendered
    assert "internal-event" not in result.rendered


async def test_missing_memory_type_directory_does_not_abort_recall():
    """Bug A: a never-created memory-type dir must yield [] for that type only.

    search.find raises NotFoundError for type dirs that have never been written.
    Previously asyncio.gather ran without return_exceptions, so that single
    failure aborted the whole recall -- including types that would have matched.
    """
    from openviking_cli.exceptions import NotFoundError

    hit = {
        "uri": "viking://user/test_user/memories/preferences/user/pref.md",
        "abstract": "user prefers signed commits",
        "score": 0.9,
    }

    async def fake_find(**kwargs):
        target = kwargs["target_uri"]
        if "/preferences" in target:
            return _FakeFindResult([hit])
        raise NotFoundError(target, "file")

    service = SimpleNamespace(search=SimpleNamespace(find=fake_find), fs=SimpleNamespace())
    ctx = RequestContext(
        user=UserIdentifier.the_default_user("test_user"),
        role=Role.USER,
        actor_peer_id="current",
    )

    result = await search_type_quota_recall(
        service=service,
        ctx=ctx,
        query="commit preferences",
        peer_scope="actor",
        quotas={"events": 1, "entities": 1, "preferences": 1, "experiences": 1},
        min_score=0.0,
    )

    rendered = str(result.context_block if hasattr(result, "context_block") else result)
    assert "pref.md" in rendered or "signed commits" in rendered


async def test_unrelated_search_errors_still_propagate():
    """Only missing-target errors are swallowed; real failures must surface."""

    async def fake_find(**kwargs):
        raise RuntimeError("vector store exploded")

    service = SimpleNamespace(search=SimpleNamespace(find=fake_find), fs=SimpleNamespace())
    ctx = RequestContext(
        user=UserIdentifier.the_default_user("test_user"),
        role=Role.USER,
        actor_peer_id="current",
    )

    try:
        await search_type_quota_recall(
            service=service,
            ctx=ctx,
            query="anything",
            peer_scope="actor",
            quotas={"preferences": 1},
            min_score=0.0,
        )
    except RuntimeError as e:
        assert "exploded" in str(e)
    else:
        raise AssertionError("unrelated errors must not be swallowed")
