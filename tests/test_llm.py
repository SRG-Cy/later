import json
from datetime import date

import pytest

from later.llm import extract_facts, read_return_policy
from tests.fakes import FakeLLM

TODAY = date(2026, 10, 23)


def reply(**kw) -> str:
    base = dict(kind="return_window", title="Zara jacket", action="Return the jacket to Zara",
                anchor_date="2026-10-20", explicit_due=None, window_days=30, window_months=None,
                org="Zara", evidence="Refunds within 30 days", confidence=0.9)
    base.update(kw)
    return json.dumps(base)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "gemma-text")
    monkeypatch.setenv("LLM_VISION_MODEL", "gemma-vision")


async def test_parses_valid_json():
    f = await extract_facts("Zara receipt 20/10/2026, 30 day returns", None, TODAY, client=FakeLLM(reply()))
    assert f.kind == "return_window" and f.window_days == 30 and f.anchor_date == date(2026, 10, 20)


async def test_invalid_json_retries_once_then_none():
    c = FakeLLM("not json", "still not json")
    assert await extract_facts("x", None, TODAY, client=c) is None
    assert c.calls == 2


async def test_retry_succeeds_on_second_reply():
    c = FakeLLM("not json", reply())
    assert (await extract_facts("x", None, TODAY, client=c)).org == "Zara"


async def test_relative_date_string_rejected():
    bad = reply(kind="bill", explicit_due="next Tuesday")
    c = FakeLLM(bad, bad)
    assert await extract_facts("pay by next tue", None, TODAY, client=c) is None


async def test_date_only_string_stays_a_date():
    f = await extract_facts("ESB bill due 28/10/2026", None, TODAY,
                            client=FakeLLM(reply(kind="bill", explicit_due="2026-10-28", window_days=None)))
    assert type(f.explicit_due) is date


async def test_text_uses_text_model_and_includes_today():
    c = FakeLLM(reply())
    await extract_facts("hello", None, TODAY, client=c)
    assert c.last_model == "gemma-text"
    assert "2026-10-23" in json.dumps(c.last_messages)


async def test_image_uses_vision_model_and_data_url():
    c = FakeLLM(reply())
    await extract_facts(None, b"\x89PNG\r\n\x1a\n...", TODAY, client=c)
    assert c.last_model == "gemma-vision"
    parts = c.last_messages[-1]["content"]
    assert any(p.get("type") == "image_url" and p["image_url"]["url"].startswith("data:image/png;base64,") for p in parts)


async def test_read_return_policy_days():
    c = FakeLLM('{"days": 28}')
    assert await read_return_policy("Boots", ["Return within 28 days with receipt"], client=c) == 28


async def test_read_return_policy_unknown_is_none():
    c = FakeLLM('{"days": null}')
    assert await read_return_policy("Boots", ["Opening hours"], client=c) is None
