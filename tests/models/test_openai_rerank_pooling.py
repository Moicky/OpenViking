"""Rerank client must reuse one connection pool across calls."""
import threading
from openviking.models.rerank.openai_rerank import OpenAIRerankClient

def test_session_is_reused_and_pool_is_sized_for_fanout():
    c = OpenAIRerankClient(api_key="k", api_base="https://example.com/rerank", model_name="m")
    s1 = c._session
    assert s1 is c._session, "session must be stable across calls"
    ad = s1.get_adapter("https://example.com/rerank")
    assert ad._pool_maxsize >= 16, f"pool too small for fan-out: {ad._pool_maxsize}"

def test_concurrent_calls_share_one_pool():
    c = OpenAIRerankClient(api_key="k", api_base="https://example.com/rerank", model_name="m")
    seen, lock = set(), threading.Lock()
    def grab():
        with lock:
            seen.add(id(c._session))
    ts = [threading.Thread(target=grab) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(seen) == 1, "each thread must share the same pooled session"
