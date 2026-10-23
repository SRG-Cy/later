import os

from elevenlabs.client import AsyncElevenLabs

STT_MODEL = "scribe_v2"


async def transcribe(audio: bytes, mime: str) -> str:
    client = AsyncElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    result = await client.speech_to_text.convert(model_id=STT_MODEL, file=("voice", audio, mime))
    return result.text
