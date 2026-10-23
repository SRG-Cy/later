"""The only place the model is called. Any OpenAI-compatible endpoint works (DigitalOcean by default)."""

import base64
import json
import os
from datetime import date

from openai import AsyncOpenAI
from pydantic import ValidationError

from later.models import Facts
from later.prompts import EXTRACT_SYSTEM, POLICY_SYSTEM


def make_client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])


def _mime(image: bytes) -> str:
    if image.startswith(b"\x89PNG"):
        return "image/png"
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _user_message(text: str | None, image: bytes | None) -> dict:
    if image is None:
        return {"role": "user", "content": text or ""}
    url = f"data:{_mime(image)};base64,{base64.b64encode(image).decode()}"
    parts = [{"type": "text", "text": text or "Here is the photo."},
             {"type": "image_url", "image_url": {"url": url}}]
    return {"role": "user", "content": parts}


def _json_object(raw: str):
    """Gemma 4 on Google AI Studio always thinks out loud first and may fence its JSON.
    Skip the <thought> block and return the last complete top-level JSON value."""
    text = raw.rsplit("</thought>", 1)[-1]
    decoder, found, i = json.JSONDecoder(), None, 0
    while (i := text.find("{", i)) != -1:
        try:
            found, end = decoder.raw_decode(text, i)
            i = end
        except ValueError:
            i += 1
    if found is None:
        return json.loads(text.strip().strip("`"))  # e.g. a bare [] or null: let the caller reject it
    return found


def _clean(raw: str) -> dict:
    data = _json_object(raw)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    # A bare YYYY-MM-DD must stay a date, not become a midnight datetime.
    due = data.get("explicit_due")
    if isinstance(due, str) and len(due) == 10:
        data["explicit_due"] = date.fromisoformat(due)
    return data


async def _complete(client, model: str, messages: list[dict]) -> str:
    # No response_format: Google's JSON mode for Gemma 4 returns 500s, and the parser copes without it.
    resp = await client.chat.completions.create(model=model, messages=messages, temperature=0)
    return resp.choices[0].message.content or ""


async def extract_facts(text: str | None, image: bytes | None, today: date,
                        client: AsyncOpenAI | None = None) -> Facts | None:
    client = client or make_client()
    model = os.environ["LLM_VISION_MODEL" if image is not None else "LLM_MODEL"]
    messages = [{"role": "system", "content": EXTRACT_SYSTEM.format(today=today.isoformat())},
                _user_message(text, image)]
    for attempt in range(2):
        raw = await _complete(client, model, messages)
        try:
            return Facts.model_validate(_clean(raw))
        except (ValueError, ValidationError) as e:  # JSONDecodeError is a ValueError
            if attempt == 0:
                messages += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": f"That was invalid: {e}. Reply with corrected JSON only."}]
    return None


async def read_return_policy(org: str, snippets: list[str], client: AsyncOpenAI | None = None) -> int | None:
    client = client or make_client()
    messages = [{"role": "system", "content": POLICY_SYSTEM},
                {"role": "user", "content": f"Shop: {org}\n\n" + "\n".join(f"- {s}" for s in snippets)}]
    try:
        data = _json_object(await _complete(client, os.environ["LLM_MODEL"], messages))
    except ValueError:
        return None
    days = data.get("days") if isinstance(data, dict) else None
    ok = isinstance(days, int) and not isinstance(days, bool) and 1 <= days <= 365
    return days if ok else None
