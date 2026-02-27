import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("MODULATE_API_KEY")
MODULATE_URL = "https://modulate-developer-apis.com/api/velma-2-stt-batch"


async def transcribe(audio_file_path: str) -> dict:
    """Send an audio file to Modulate and return the full API response."""
    data = aiohttp.FormData()
    data.add_field(
        "upload_file",
        open(audio_file_path, "rb"),
        filename=audio_file_path,
        content_type="application/octet-stream",
    )
    data.add_field("speaker_diarization", "true")
    data.add_field("emotion_signal", "true")
    data.add_field("accent_signal", "true")
    data.add_field("pii_phi_tagging", "false")

    async with aiohttp.ClientSession() as session:
        async with session.post(
            MODULATE_URL,
            headers={"X-API-Key": API_KEY},
            data=data,
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Modulate API error {resp.status}: {await resp.text()}")
            return await resp.json()


def transcribe_sync(audio_file_path: str) -> dict:
    return asyncio.run(transcribe(audio_file_path))
