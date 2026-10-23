import httpx
import pytest

from later import policy


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("SERPAPI_KEY", "k")


def client_returning(status: int, body: dict, seen: list):
    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(status, json=body)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_sends_irish_query_and_passes_snippets(monkeypatch):
    seen, got = [], {}

    async def fake_reader(org, snippets, client=None):
        got.update(org=org, snippets=snippets)
        return 28

    monkeypatch.setattr(policy, "read_return_policy", fake_reader)
    body = {"organic_results": [{"snippet": "Return within 28 days"}, {"title": "no snippet"}]}
    days = await policy.lookup_return_days("Boots", http=client_returning(200, body, seen))
    q = seen[0].url.params
    assert str(seen[0].url).startswith("https://serpapi.com/search.json")
    assert q["q"] == "Boots return policy Ireland" and q["gl"] == "ie" and q["num"] == "5"
    assert days == 28 and got["snippets"] == ["Return within 28 days"]


async def test_no_results_is_none(monkeypatch):
    async def never(*a, **k):
        raise AssertionError("should not read")
    monkeypatch.setattr(policy, "read_return_policy", never)
    assert await policy.lookup_return_days("Boots", http=client_returning(200, {}, [])) is None


async def test_rate_limited_is_none():
    assert await policy.lookup_return_days("Boots", http=client_returning(429, {}, [])) is None


async def test_no_key_is_none(monkeypatch):
    monkeypatch.delenv("SERPAPI_KEY")
    assert await policy.lookup_return_days("Boots", http=client_returning(200, {}, [])) is None
