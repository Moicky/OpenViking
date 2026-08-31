# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Access accounting for self-learned context.

Recall injects memories into an agent session without anyone asking for them by
name, so nothing in the request log says which memory earned its slot. This
module carries the one event both the recall pipeline and the explicit read APIs
publish, and the URI rule that decides what counts as self-learned at all.

Indexed resources are excluded on purpose: a repo ingest would swamp the signal
that tells a maintainer which learned knowledge is worth keeping.
"""

from __future__ import annotations

from typing import Any, Iterable

from openviking.observability.events import try_publish_event

EVENT_NAME = "memory.access"

MEMORY_ACCESS_CATEGORIES: frozenset[str] = frozenset(
    ("events", "entities", "preferences", "experiences", "memories", "skills")
)
# `injected` is the server assembling a context block; `found` is a search hit
# handed back to a caller that assembles client-side (older harness plugins) or
# to an agent that ran `find` itself; `read` is an explicit content fetch.
MEMORY_ACCESS_SOURCES: frozenset[str] = frozenset(("injected", "found", "read"))
OTHER_MEMORY_ACCESS_CATEGORY = "memories"


def memory_category_for_uri(uri: Any) -> str | None:
    """Category a self-learned URI reports as, or ``None`` when it is not one."""
    text = str(uri or "")
    if not text:
        return None
    parts = [part for part in text.split("://")[-1].split("/") if part]
    for index, part in enumerate(parts):
        if part == "resources":
            # A repo may well ship its own `skills/` or `memories/` directory;
            # anything below a resources root is an ingest, not learned.
            return None
        if part == "memories":
            nxt = parts[index + 1] if index + 1 < len(parts) else ""
            if nxt in MEMORY_ACCESS_CATEGORIES and nxt != "skills":
                return nxt
            return OTHER_MEMORY_ACCESS_CATEGORY
        if part == "skills":
            return "skills"
    return None


def normalize_memory_category(category: Any, uri: Any) -> str | None:
    """Trust a caller-supplied category only when it names a self-learned one."""
    text = str(category or "")
    if text in MEMORY_ACCESS_CATEGORIES:
        return text
    if text:
        # An explicit non-memory category (`resources`) is a rejection, not a
        # gap to fill in from the URI.
        return None
    return memory_category_for_uri(uri)


def publish_memory_access(
    *,
    source: str,
    entries: Iterable[Any],
    account_id: Any = None,
    user_id: Any = None,
) -> None:
    """Publish one access event covering every self-learned entry in a call.

    `entries` accepts anything carrying `uri` and optionally `category` —
    assembled context entries, search hits, or plain dicts. Non-memory entries
    are dropped here so a resource read never reaches the event bus at all.
    """
    if source not in MEMORY_ACCESS_SOURCES:
        return
    payload_entries: list[dict[str, str]] = []
    for entry in entries:
        if isinstance(entry, dict):
            uri, category = entry.get("uri"), entry.get("category")
        else:
            uri, category = getattr(entry, "uri", None), getattr(entry, "category", None)
        resolved = normalize_memory_category(category, uri)
        if not uri or resolved is None:
            continue
        payload_entries.append({"uri": str(uri), "category": resolved})
    if not payload_entries:
        return
    try_publish_event(
        EVENT_NAME,
        {
            "source": source,
            "entries": payload_entries,
            "account_id": account_id,
            "user_id": user_id,
        },
    )
