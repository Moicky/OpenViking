# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""One rerank client per config, so its HTTP connection pool is reused.

A retriever is constructed per search and builds its rerank client in
__init__; without caching, every search discarded the pool and paid a cold
TCP+TLS handshake on every rerank call.
"""

import threading

from openviking.models.rerank import RerankClient
from openviking_cli.utils.config import RerankConfig


def _cfg(**over) -> RerankConfig:
    base = dict(
        provider="openai",
        api_key="k",
        api_base="https://example.com/rerank",
        model="some-model",
    )
    base.update(over)
    return RerankConfig(**base)


def test_same_config_returns_the_same_client():
    a = RerankClient.from_config(_cfg())
    b = RerankClient.from_config(_cfg())
    assert a is not None
    assert a is b, "a repeated config must reuse the client (and its pool)"
    assert a._session is b._session


def test_changed_config_returns_a_new_client():
    a = RerankClient.from_config(_cfg())
    b = RerankClient.from_config(_cfg(model="other-model"))
    c = RerankClient.from_config(_cfg(api_base="https://elsewhere.com/rerank"))
    assert a is not b and a is not c, "config changes must not be served from cache"


def test_concurrent_construction_yields_one_shared_client():
    cfg_kwargs = dict(model="race-model")
    seen, lock = [], threading.Lock()

    def build():
        client = RerankClient.from_config(_cfg(**cfg_kwargs))
        with lock:
            seen.append(client)

    threads = [threading.Thread(target=build) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len({id(c) for c in seen}) == 1, "racing builders must converge on one client"
