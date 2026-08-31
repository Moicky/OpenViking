# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Memory access tracking: URI classification, storage rollup, and reporting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from openviking.observability.events import ObservabilityEvent
from openviking.observability.memory_access import memory_category_for_uri
from openviking.observability.usage_audit.api_service import UsageAuditQueryService
from openviking.observability.usage_audit.sqlite_store import SQLiteUsageAuditStore
from openviking.server.identity import RequestContext, Role
from openviking_cli.session.user_id import UserIdentifier

UTC = timezone.utc

USER_MEMORY = "viking://user/opencode/memories/entities/software_project/openviking.md"
PEER_MEMORY = "viking://user/opencode/peers/lenz/memories/events/2026/08/11/plan.md"
LOOSE_MEMORY = "viking://user/opencode/memories/cases/some-case.md"
SKILL = "viking://user/opencode/skills/deploy/SKILL.md"
RESOURCE = "viking://resources/some-repo/src/main.py"
RESOURCE_SKILL_DIR = "viking://resources/some-repo/skills/thing.md"


def _access_event(
    entries: list[dict],
    *,
    source: str = "injected",
    ts: datetime | None = None,
    user_id: str = "user-1",
) -> ObservabilityEvent:
    return ObservabilityEvent(
        event_name="memory.access",
        payload={"source": source, "entries": entries},
        timestamp=ts or datetime(2026, 8, 31, 10, 0, 0, tzinfo=UTC),
        account_id="acct-1",
        user_id=user_id,
    )


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        (USER_MEMORY, "entities"),
        (PEER_MEMORY, "events"),
        (LOOSE_MEMORY, "memories"),
        (SKILL, "skills"),
        (RESOURCE, None),
        # A repo that happens to ship a `skills/` directory is still an ingest.
        (RESOURCE_SKILL_DIR, None),
        ("", None),
        ("viking://user/opencode/sessions/abc", None),
    ],
)
def test_memory_category_for_uri(uri, expected):
    assert memory_category_for_uri(uri) == expected


async def _store(tmp_path) -> SQLiteUsageAuditStore:
    store = SQLiteUsageAuditStore(tmp_path / "usage_audit.sqlite3")
    await store.initialize()
    return store


@pytest.mark.asyncio
async def test_memory_access_rolls_up_per_uri_and_source(tmp_path):
    store = await _store(tmp_path)
    try:
        await store.record_batch(
            [
                _access_event([{"uri": USER_MEMORY, "category": "entities"}]),
                _access_event(
                    [
                        {"uri": USER_MEMORY, "category": "entities"},
                        {"uri": PEER_MEMORY, "category": "events"},
                        # Resources never reach the table, whatever the caller says.
                        {"uri": RESOURCE, "category": "resources"},
                    ]
                ),
                _access_event([{"uri": USER_MEMORY}], source="read"),
                _access_event([{"uri": PEER_MEMORY}], source="found"),
                # An unknown source is bookkeeping noise, not an access.
                _access_event([{"uri": PEER_MEMORY}], source="hallucinated"),
            ]
        )

        rows = {row["uri"]: row for row in await store.get_memory_usage(account_id="acct-1")}
        assert set(rows) == {USER_MEMORY, PEER_MEMORY}
        assert rows[USER_MEMORY]["injected"] == 2
        assert rows[USER_MEMORY]["read"] == 1
        assert rows[USER_MEMORY]["total"] == 3
        assert rows[USER_MEMORY]["found"] == 0
        assert rows[USER_MEMORY]["category"] == "entities"
        assert rows[PEER_MEMORY]["total"] == 2
        assert rows[PEER_MEMORY]["injected"] == 1
        assert rows[PEER_MEMORY]["found"] == 1
        assert rows[PEER_MEMORY]["read"] == 0
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_memory_access_window_and_user_scope(tmp_path):
    store = await _store(tmp_path)
    now = datetime.now(UTC)
    try:
        await store.record_batch(
            [
                _access_event([{"uri": USER_MEMORY}], ts=now),
                _access_event([{"uri": PEER_MEMORY}], ts=now - timedelta(days=40)),
                _access_event([{"uri": SKILL}], ts=now, user_id="user-2"),
            ]
        )

        recent = {row["uri"] for row in await store.get_memory_usage(account_id="acct-1", days=7)}
        assert recent == {USER_MEMORY, SKILL}

        everything = {
            row["uri"] for row in await store.get_memory_usage(account_id="acct-1", days=0)
        }
        assert everything == {USER_MEMORY, PEER_MEMORY, SKILL}

        scoped = {
            row["uri"]
            for row in await store.get_memory_usage(account_id="acct-1", user_id="user-1", days=0)
        }
        assert scoped == {USER_MEMORY, PEER_MEMORY}
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_memory_access_survives_delete_user_data(tmp_path):
    store = await _store(tmp_path)
    try:
        await store.record_batch([_access_event([{"uri": USER_MEMORY}])])
        await store.delete_user_data(account_id="acct-1", user_id="user-1")
        assert await store.get_memory_usage(account_id="acct-1", days=0) == []
    finally:
        await store.close()


class _StubInventory:
    def __init__(self, records):
        self._records = records

    async def get_counts(self, ctx):  # pragma: no cover - unused here
        return {}

    async def list_memory_records(self, ctx):
        return self._records


def _ctx(role: Role = Role.ADMIN) -> RequestContext:
    return RequestContext(
        user=UserIdentifier(account_id="acct-1", user_id="user-1"),
        role=role,
    )


@pytest.mark.asyncio
async def test_memory_usage_report_splits_used_from_unused(tmp_path):
    store = await _store(tmp_path)
    try:
        await store.record_batch(
            [
                _access_event([{"uri": USER_MEMORY}]),
                _access_event([{"uri": USER_MEMORY}]),
                _access_event([{"uri": PEER_MEMORY}], source="read"),
            ]
        )
        service = UsageAuditQueryService(
            store=store,
            inventory=_StubInventory(
                [
                    {"uri": USER_MEMORY, "category": "entities", "created_at": "2026-01-01"},
                    {"uri": PEER_MEMORY, "category": "events", "created_at": "2026-02-01"},
                    {"uri": SKILL, "category": "skills", "created_at": "2026-03-01"},
                    {"uri": LOOSE_MEMORY, "category": "memories", "created_at": "2026-04-01"},
                ]
            ),
            timezone_name="UTC",
        )

        report = await service.memory_usage(ctx=_ctx(), days=30, limit=10)

        assert [item["uri"] for item in report["top"]] == [USER_MEMORY, PEER_MEMORY]
        assert [item["uri"] for item in report["unused"]] == [SKILL, LOOSE_MEMORY]
        assert report["totals"] == {
            "inventory": 4,
            "used": 2,
            "unused": 2,
            "deleted_but_used": 0,
            "injections": 2,
            "found": 0,
            "reads": 1,
            "accesses": 3,
        }
        assert report["by_category"] == {"entities": 2, "events": 1}
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_publish_reaches_the_store_through_the_real_worker(tmp_path):
    """End-to-end: publish -> event bus -> subscriber -> worker -> SQLite."""
    from openviking.observability.events import (
        register_event_subscriber,
        unregister_event_subscriber,
    )
    from openviking.observability.memory_access import publish_memory_access
    from openviking.observability.usage_audit.subscriber import UsageAuditSubscriber
    from openviking.observability.usage_audit.worker import UsageAuditWorker

    store = await _store(tmp_path)
    worker = UsageAuditWorker(store, flush_interval_seconds=0.1)
    await worker.start()
    register_event_subscriber("test-usage-audit", UsageAuditSubscriber(worker))
    try:
        publish_memory_access(
            source="injected",
            entries=[
                {"uri": USER_MEMORY, "category": "entities"},
                {"uri": RESOURCE, "category": "resources"},
            ],
            account_id="acct-1",
            user_id="user-1",
        )
        publish_memory_access(
            source="read", entries=[{"uri": SKILL}], account_id="acct-1", user_id="user-1"
        )
        # A resources-only call must not even reach the bus.
        publish_memory_access(
            source="injected",
            entries=[{"uri": RESOURCE}],
            account_id="acct-1",
            user_id="user-1",
        )
        await worker.flush()
    finally:
        unregister_event_subscriber("test-usage-audit")
        await worker.close(timeout_seconds=2.0)

    rows = {row["uri"]: row for row in await store.get_memory_usage(account_id="acct-1", days=0)}
    await store.close()
    assert set(rows) == {USER_MEMORY, SKILL}
    assert rows[USER_MEMORY]["injected"] == 1
    assert rows[SKILL]["read"] == 1
    assert rows[SKILL]["category"] == "skills"


def test_search_router_records_only_self_learned_hits():
    """The `find` path is how pre-context-assembly plugins build their block."""
    from openviking.observability.events import (
        register_event_subscriber,
        unregister_event_subscriber,
    )
    from openviking.server.routers.search import _record_found_memories

    seen = []
    register_event_subscriber("test-memory-access", seen.append)
    try:
        _record_found_memories(
            {
                "memories": [{"uri": USER_MEMORY}, {"uri": LOOSE_MEMORY}],
                "skills": [{"uri": SKILL}],
                # A resource search must never enter memory usage accounting.
                "resources": [{"uri": RESOURCE}],
                "total": 4,
            },
            _ctx(),
        )
        _record_found_memories({"memories": [], "skills": [], "resources": []}, _ctx())
        _record_found_memories("not a dict", _ctx())
    finally:
        unregister_event_subscriber("test-memory-access")

    events = [event for event in seen if event.event_name == "memory.access"]
    assert len(events) == 1
    assert events[0].payload["source"] == "found"
    assert {entry["uri"] for entry in events[0].payload["entries"]} == {
        USER_MEMORY,
        LOOSE_MEMORY,
        SKILL,
    }


@pytest.mark.asyncio
async def test_console_endpoint_serves_real_store_over_http(tmp_path):
    """Full read path: HTTP -> console router -> query service -> SQLite."""
    import httpx
    from fastapi import FastAPI

    from openviking.observability.usage_audit.api_service import UsageAuditQueryService
    from openviking.server.auth import get_request_context
    from openviking.server.routers.console import router as console_router

    store = await _store(tmp_path)
    await store.record_batch(
        [
            _access_event([{"uri": USER_MEMORY}]),
            _access_event([{"uri": USER_MEMORY}], source="found"),
            _access_event([{"uri": PEER_MEMORY}], source="read"),
        ]
    )

    app = FastAPI()
    app.include_router(console_router)
    app.dependency_overrides[get_request_context] = lambda: _ctx()
    app.state.usage_audit_runtime = type(
        "Runtime",
        (),
        {
            "api_service": UsageAuditQueryService(
                store=store,
                inventory=_StubInventory(
                    [
                        {"uri": USER_MEMORY, "category": "entities"},
                        {"uri": PEER_MEMORY, "category": "events"},
                        {"uri": SKILL, "category": "skills"},
                    ]
                ),
                timezone_name="UTC",
            )
        },
    )()

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(
                "/api/v1/console/memory-usage", params={"days": "30", "limit": "5"}
            )
    finally:
        await store.close()

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["days"] == 30
    assert result["totals"]["injections"] == 1
    assert result["totals"]["found"] == 1
    assert result["totals"]["reads"] == 1
    assert result["totals"]["unused"] == 1
    assert result["top"][0]["uri"] == USER_MEMORY
    assert result["top"][0]["total"] == 2
    assert [item["uri"] for item in result["unused"]] == [SKILL]
