"""
Main pipeline: MP3 → Modulate → language processing → formatting → PDF.

Usage:
    python pipeline.py <audio_file.mp3> [output.pdf]
"""

import os
import sys
from modulate_client import transcribe_sync
from processors import get_processor
from formatter import format_report, generate_pdf


def run(audio_file_path: str, pdf_output_path: str | None = None) -> dict:
    """
    Full pipeline:
      1. Transcribe audio via Modulate.
      2. Per-utterance: punctuation → grammar → doctor correction.
      3. Formatting agent: restructure into standard CR JSON.
      4. PDF export.

    Returns the structured CR dict.
    """
    # ── Step 1: Transcription ────────────────────────────────────────────────
    print(f"[1/4] Transcribing: {audio_file_path}")
    modulate_result = transcribe_sync(audio_file_path)

    utterances = modulate_result.get("utterances", [])
    if not utterances:
        raise RuntimeError("Modulate returned no utterances.")

    # ── Step 2: Language processing (punctuation + grammar + doctor) ─────────
    processed_parts = []
    language = "fr"  # default; overridden by first detected language

    for i, utterance in enumerate(utterances):
        language = utterance.get("language", "fr")
        speaker = utterance.get("speaker", "?")
        emotion = utterance.get("emotion", "")
        accent = utterance.get("accent", "")

        print(
            f"[2/4] Utterance {i + 1}/{len(utterances)} — "
            f"lang={language}, speaker={speaker}, emotion={emotion}, accent={accent}"
        )

        processor = get_processor(language)
        processed_text = processor.process(utterance)
        processed_parts.append(processed_text)

    combined_text = "\n\n".join(processed_parts)

    # ── Step 3: Formatting agent ─────────────────────────────────────────────
    print("[3/4] Formatting compte rendu...")
    cr = format_report(combined_text, language=language)

    # ── Step 4: PDF export ───────────────────────────────────────────────────
    if pdf_output_path is None:
        base = os.path.splitext(os.path.basename(audio_file_path))[0]
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "local")
        os.makedirs(output_dir, exist_ok=True)
        pdf_output_path = os.path.join(output_dir, f"{base}_CR.pdf")

    print(f"[4/4] Generating PDF...")
    generate_pdf(cr, pdf_output_path)

    return cr


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <audio_file.mp3> [output.pdf]")
        sys.exit(1)

    audio_path = sys.argv[1]
    pdf_path = sys.argv[2] if len(sys.argv) > 2 else None

    cr_data = run(audio_path, pdf_path)

    print("\n" + "=" * 60)
    print("STRUCTURED COMPTE RENDU")
    print("=" * 60)
    import json
    print(json.dumps(cr_data, ensure_ascii=False, indent=2))
