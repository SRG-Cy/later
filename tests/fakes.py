"""Fake OpenAI-compatible client: returns canned completions in order and records calls."""

from types import SimpleNamespace


class FakeLLM:
    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls = 0
        self.last_model = None
        self.last_messages = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, *, model, messages, **kw):
        self.calls += 1
        self.last_model, self.last_messages = model, messages
        content = self.replies.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
        )
