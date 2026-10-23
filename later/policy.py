"""Find a shop's return window when the receipt doesn't print one."""

import os

import httpx

from later.llm import read_return_policy

SERPAPI_URL = "https://serpapi.com/search.json"


async def lookup_return_days(org: str, http: httpx.AsyncClient | None = None) -> int | None:
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        return None
    params = {"q": f"{org} return policy Ireland", "gl": "ie", "num": 5, "api_key": key}
    http = http or httpx.AsyncClient(timeout=15)
    try:
        resp = await http.get(SERPAPI_URL, params=params)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    snippets = [r["snippet"] for r in resp.json().get("organic_results", []) if r.get("snippet")]
    if not snippets:
        return None
    return await read_return_policy(org, snippets)
