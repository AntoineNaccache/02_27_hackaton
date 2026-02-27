"""
Main pipeline: MP3 → Modulate → language detection → text processing → output.

Usage:
    python pipeline.py <audio_file.mp3>
"""

import sys
from modulate_client import transcribe_sync
from processors import get_processor


def run(audio_file_path: str) -> str:
    print(f"[1/3] Transcribing: {audio_file_path}")
    modulate_result = transcribe_sync(audio_file_path)

    utterances = modulate_result.get("utterances", [])
    if not utterances:
        raise RuntimeError("Modulate returned no utterances.")

    processed_parts = []

    for i, utterance in enumerate(utterances):
        language = utterance.get("language", "en")
        speaker = utterance.get("speaker", "?")
        emotion = utterance.get("emotion", "")
        accent = utterance.get("accent", "")

        print(
            f"[2/3] Utterance {i + 1}/{len(utterances)} — "
            f"lang={language}, speaker={speaker}, emotion={emotion}, accent={accent}"
        )

        processor = get_processor(language)
        processed_text = processor.process(utterance)
        processed_parts.append(processed_text)

    final_report = "\n\n".join(processed_parts)

    print("[3/3] Processing complete.")
    return final_report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <audio_file.mp3>")
        sys.exit(1)

    audio_path = sys.argv[1]
    report = run(audio_path)

    print("\n" + "=" * 60)
    print("FINAL REPORT")
    print("=" * 60)
    print(report)
