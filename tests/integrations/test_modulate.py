import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("MODULATE_API_KEY")
AUDIO_FILE = "samples\input_audios\CR_Fr.mp3"

async def transcribe():
    data = aiohttp.FormData()
    data.add_field(
        "upload_file",
        open(AUDIO_FILE, "rb"),
        filename=AUDIO_FILE,
        content_type="application/octet-stream",
    )
    data.add_field("speaker_diarization", "true")
    data.add_field("emotion_signal", "true")
    data.add_field("accent_signal", "false")
    data.add_field("pii_phi_tagging", "false")

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://modulate-developer-apis.com/api/velma-2-stt-batch",
            headers={"X-API-Key": API_KEY},
            data=data,
        ) as resp:
            if resp.status != 200:
                print(f"Error {resp.status}: {await resp.text()}")
                return

            result = await resp.json()

    #print(f"Transcript: {result['text']}")
    #print(f"Audio duration: {result['duration_ms']}ms")
    #print(f"Utterances: {len(result['utterances'])}")

    for u in result["utterances"]:
        #print(
            #f"  [{u['speaker']}] ({u['language']}) "
            #f"{u['start_ms']}-{u['start_ms'] + u['duration_ms']}ms: "
            #f"{u['text']}"
        #)
        print(u)

        

asyncio.run(transcribe())