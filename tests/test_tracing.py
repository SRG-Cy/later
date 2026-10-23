import sentry_sdk

from later.tracing import init_tracing


def test_no_dsn_is_a_noop(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_tracing() is False
    assert not sentry_sdk.get_client().is_active()


def test_prompts_never_sent(monkeypatch):
    seen = {}
    monkeypatch.setenv("SENTRY_DSN", "https://key@o0.ingest.sentry.io/0")
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: seen.update(kw))
    assert init_tracing() is True
    assert seen["send_default_pii"] is False and seen["traces_sample_rate"] == 1.0
    openai_int = [i for i in seen["integrations"] if type(i).__name__ == "OpenAIIntegration"][0]
    assert openai_int.include_prompts is False
