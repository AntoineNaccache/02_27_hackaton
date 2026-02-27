"""
Modulate Streaming STT client.

Connects to wss://modulate-developer-apis.com/api/velma-2-stt-streaming,
streams raw PCM-16 mono 16 kHz audio chunks, and emits transcript events.

Thread-safe: start() / send_audio() / stop() / pop_events() can be called
from any thread (including WebRTC audio-processor callbacks).
"""

import asyncio
import json
import os
import queue
import threading

import websockets
from dotenv import load_dotenv

load_dotenv()

_STREAMING_BASE = "wss://modulate-developer-apis.com/api/velma-2-stt-streaming"

_END = None  # sentinel that signals end-of-stream in the audio queue


class ModulateStreamingClient:
    """
    Usage::

        client = ModulateStreamingClient()
        client.start()

        # from your audio capture loop:
        client.send_audio(pcm_bytes)          # raw PCM-16 mono 16 kHz

        # from your UI update loop:
        for ev in client.pop_events():
            # ev = {"text": str, "is_final": bool}  or  {"error": str}
            ...

        client.stop()                          # blocks until WS is closed
        full_text = client.get_full_transcript()
    """

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.getenv("MODULATE_API_KEY", "")
        self._audio_q: queue.Queue[bytes | None] = queue.Queue()
        self._event_q: queue.Queue[dict] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._final_parts: list[str] = []
        self._partial: str = ""

    # ── Public interface ───────────────────────────────────────────────────────

    def start(self) -> None:
        """Open the WebSocket in a background daemon thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def send_audio(self, pcm: bytes) -> None:
        """Queue a raw PCM-16 mono 16 kHz chunk to be forwarded to Modulate."""
        self._audio_q.put(pcm)

    def stop(self) -> None:
        """Signal end-of-stream and wait for the WebSocket to close (max 15 s)."""
        self._audio_q.put(_END)
        if self._thread:
            self._thread.join(timeout=15)

    def pop_events(self) -> list[dict]:
        """
        Drain and return all pending transcript events (non-blocking).
        Each event is one of:
          {"text": str, "is_final": bool}
          {"error": str}
        """
        events: list[dict] = []
        while True:
            try:
                events.append(self._event_q.get_nowait())
            except queue.Empty:
                break
        return events

    def get_full_transcript(self) -> str:
        """All final segments joined, available after stop() returns."""
        return " ".join(self._final_parts)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._ws_session())
        except Exception as exc:
            self._event_q.put({"error": str(exc)})
        finally:
            loop.close()

    async def _ws_session(self) -> None:
        # Pass the API key as a query parameter — many WS endpoints require this
        # because browsers cannot set custom headers on WebSocket upgrade requests.
        url = f"{_STREAMING_BASE}?api_key={self._api_key}"
        try:
            async with websockets.connect(url) as ws:
                await asyncio.gather(
                    self._send_loop(ws),
                    self._recv_loop(ws),
                )
        except Exception as exc:
            self._event_q.put({"error": str(exc)})

    async def _send_loop(self, ws) -> None:
        loop = asyncio.get_event_loop()
        while True:
            # run_in_executor so we don't block the event loop while waiting
            chunk = await loop.run_in_executor(None, self._audio_q.get)
            if chunk is _END:
                try:
                    await ws.send(json.dumps({"type": "end_of_stream"}))
                except Exception:
                    pass
                await ws.close()
                return
            await ws.send(chunk)

    async def _recv_loop(self, ws) -> None:
        async for raw in ws:
            try:
                data = json.loads(raw) if isinstance(raw, str) else {}
            except json.JSONDecodeError:
                continue
            text = data.get("text", "")
            is_final = bool(data.get("is_final", False))
            if text:
                if is_final:
                    self._final_parts.append(text)
                    self._partial = ""
                else:
                    self._partial = text
                self._event_q.put({"text": text, "is_final": is_final})
