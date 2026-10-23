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


def _clean(raw: str) -> dict:
    data = json.loads(raw)
    # A bare YYYY-MM-DD must stay a date, not become a midnight datetime.
    due = data.get("explicit_due")
    if isinstance(due, str) and len(due) == 10:
        data["explicit_due"] = date.fromisoformat(due)
    return data


async def _complete(client, model: str, messages: list[dict]) -> str:
    resp = await client.chat.completions.create(
        model=model, messages=messages, temperature=0, response_format={"type": "json_object"},
    )
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
        days = json.loads(await _complete(client, os.environ["LLM_MODEL"], messages)).get("days")
    except ValueError:
        return None
    return days if isinstance(days, int) and days > 0 else None
