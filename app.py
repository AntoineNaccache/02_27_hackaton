"""
Streamlit front-end — Compte Rendu Radiologique pipeline.

Run with:
    streamlit run app.py
"""

import difflib
import os
import re
import sys
import tempfile

# Make src/ importable regardless of working directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import streamlit as st

from modulate_client import transcribe_sync
from processors import get_processor
from formatter import format_report, generate_pdf

# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="CR Radiologique",
    page_icon="🩻",
    layout="centered",
)

st.title("🩻 Radiology Report Generator")
st.caption("Upload an audio file — the structured PDF report is generated automatically.")

# ── Diff rendering utilities ───────────────────────────────────────────────────


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _word_diff_html(before: str, after: str) -> str:
    """Inline word-level diff: removals in red strikethrough, additions in green bold."""
    before_tokens = re.split(r"(\s+)", before)
    after_tokens = re.split(r"(\s+)", after)
    matcher = difflib.SequenceMatcher(None, before_tokens, after_tokens, autojunk=False)
    parts: list[str] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            parts.append(_escape("".join(before_tokens[i1:i2])))
        elif op in ("replace", "delete"):
            removed = _escape("".join(before_tokens[i1:i2]))
            parts.append(
                f'<span style="background:#fee2e2;color:#dc2626;'
                f'text-decoration:line-through;padding:0 2px;border-radius:3px">'
                f"{removed}</span>"
            )
            if op == "replace":
                added = _escape("".join(after_tokens[j1:j2]))
                parts.append(
                    f'<span style="background:#dcfce7;color:#16a34a;'
                    f'font-weight:700;padding:0 2px;border-radius:3px">'
                    f"{added}</span>"
                )
        elif op == "insert":
            added = _escape("".join(after_tokens[j1:j2]))
            parts.append(
                f'<span style="background:#dcfce7;color:#16a34a;'
                f'font-weight:700;padding:0 2px;border-radius:3px">'
                f"{added}</span>"
            )
    html = "".join(parts).replace("\n", "<br>")
    return (
        f'<div style="font-family:monospace;font-size:13px;line-height:1.9;'
        f'background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px">'
        f"{html}</div>"
    )


def _render_step_diff(label: str, before: str, after: str) -> None:
    changed = before.strip() != after.strip()
    icon = "✏️" if changed else "✅"
    with st.expander(f"{icon} {label}", expanded=changed):
        if changed:
            st.markdown(_word_diff_html(before, after), unsafe_allow_html=True)
            tokens_before = re.split(r"\s+", before.strip())
            tokens_after = re.split(r"\s+", after.strip())
            removed = sum(
                i2 - i1
                for op, i1, i2, *_ in difflib.SequenceMatcher(
                    None, tokens_before, tokens_after, autojunk=False
                ).get_opcodes()
                if op in ("replace", "delete")
            )
            added = sum(
                j2 - j1
                for op, *_, j1, j2 in difflib.SequenceMatcher(
                    None, tokens_before, tokens_after, autojunk=False
                ).get_opcodes()
                if op in ("replace", "insert")
            )
            st.caption(f"−{removed} mot(s) · +{added} mot(s)")
        else:
            st.caption("Aucune modification à cette étape.")


def display_inspection(utterance_steps: list[dict]) -> None:
    st.divider()
    st.subheader("🔬 Inspection du traitement")
    for i, step in enumerate(utterance_steps):
        speaker = step.get("speaker", "?")
        lang = step.get("language", "fr").upper()
        with st.expander(
            f"Segment {i + 1} — Locuteur : {speaker} ({lang})", expanded=True
        ):
            _render_step_diff("Étape 1 : Ponctuation", step["raw"], step["after_punctuation"])
            _render_step_diff("Étape 2 : Grammaire", step["after_punctuation"], step["after_grammar"])
            _render_step_diff(
                "Étape 3 : Noms (médecins / établissements)",
                step["after_grammar"],
                step["after_doctor"],
            )


# ── Pipeline ───────────────────────────────────────────────────────────────────


def _dominant_language(utterances: list[dict], fallback: str) -> str:
    """Return the most frequent language detected by Modulate across utterances."""
    from collections import Counter
    langs = [u.get("language") for u in utterances if u.get("language")]
    if not langs:
        return fallback
    return Counter(langs).most_common(1)[0][0]


def run_pipeline(
    audio_path: str,
    collect_steps: bool = False,
    language: str = "fr",
) -> tuple[dict, bytes, list[dict], str]:
    """
    Full 4-step pipeline from audio file.
    Returns (cr, pdf_bytes, utterance_steps, detected_language).

    `language` is the UI fallback used when Modulate does not tag an utterance.
    The dominant language detected by Modulate across all utterances is used
    for format_report() and generate_pdf(), and returned to the caller.
    """
    utterance_steps: list[dict] = []

    with st.status("Processing…", expanded=True) as status:

        st.write("**[1/4]** Transcribing audio via Modulate…")
        modulate_result = transcribe_sync(audio_path)
        utterances = modulate_result.get("utterances", [])
        if not utterances:
            status.update(label="Transcription error", state="error")
            raise RuntimeError("Modulate returned no audio segments.")

        # Leverage Modulate's language detection; UI selection is the fallback
        detected_lang = _dominant_language(utterances, fallback=language)
        lang_label = "🇫🇷 French" if detected_lang == "fr" else "🇬🇧 English"
        st.write(f"✅ {len(utterances)} segment(s) transcribed — language detected: **{lang_label}**")

        st.write("**[2/4]** Language processing…")
        processed_parts: list[str] = []
        for i, utterance in enumerate(utterances):
            uttr_lang = utterance.get("language", detected_lang)
            processor = get_processor(uttr_lang)
            if collect_steps:
                steps = processor.process_with_steps(utterance)
                utterance_steps.append(
                    {"speaker": utterance.get("speaker", "?"), "language": uttr_lang, **steps}
                )
                processed_parts.append(steps["after_doctor"])
            else:
                processed_parts.append(processor.process(utterance))
            st.write(f"  — Segment {i + 1}/{len(utterances)} done")
        combined_text = "\n\n".join(processed_parts)
        st.write("✅ Correction complete")

        st.write("**[3/4]** Structuring the report…")
        cr = format_report(combined_text, language=detected_lang)
        st.write("✅ JSON structure generated")

        st.write("**[4/4]** Generating PDF…")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
            tmp_pdf_path = tmp_pdf.name
        generate_pdf(cr, tmp_pdf_path, language=detected_lang)
        with open(tmp_pdf_path, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(tmp_pdf_path)
        st.write("✅ PDF ready")

        status.update(label="Done!", state="complete", expanded=False)

    return cr, pdf_bytes, utterance_steps, detected_lang


# ── Result display ─────────────────────────────────────────────────────────────


_RESULT_LABELS = {
    "fr": {
        "heading":    "Résultat",
        "patient":    "Patient",
        "dob":        "Date de naissance",
        "exam_date":  "Date d'examen",
        "institution":"Établissement",
        "city":       "Ville",
        "doctor":     "Médecin",
        "results":    "Résultats de l'examen",
        "download":   "⬇️ Télécharger le PDF",
        "na":         "[Non renseigné]",
    },
    "en": {
        "heading":    "Result",
        "patient":    "Patient",
        "dob":        "Date of birth",
        "exam_date":  "Exam date",
        "institution":"Institution",
        "city":       "City",
        "doctor":     "Physician",
        "results":    "Examination results",
        "download":   "⬇️ Download PDF",
        "na":         "[Not provided]",
    },
}


def display_results(cr: dict, pdf_bytes: bytes, pdf_filename: str, language: str = "fr") -> None:
    lbl = _RESULT_LABELS.get(language, _RESULT_LABELS["fr"])
    na = lbl["na"]
    st.divider()
    st.subheader(lbl["heading"])
    col1, col2 = st.columns(2)
    with col1:
        st.metric(lbl["patient"],    cr.get("patient_nom",   na))
        st.metric(lbl["dob"],        cr.get("patient_ddn",   na))
        st.metric(lbl["exam_date"],  cr.get("date_examen",   na))
    with col2:
        st.metric(lbl["institution"],cr.get("etablissement", na))
        st.metric(lbl["city"],       cr.get("ville",         na))
        st.metric(lbl["doctor"],     cr.get("medecin",       na))
    with st.expander(lbl["results"], expanded=True):
        st.text(cr.get("resultats", na))
    st.download_button(
        label=lbl["download"],
        data=pdf_bytes,
        file_name=pdf_filename,
        mime="application/pdf",
        type="primary",
        use_container_width=True,
    )


# ── File upload ────────────────────────────────────────────────────────────────

uploaded = st.file_uploader(
    "Drop your audio file (MP3, WAV, M4A…)",
    type=["mp3", "wav", "m4a", "ogg"],
)

if uploaded:
    st.audio(uploaded)

    col_lang, col_inspect = st.columns([1, 2])
    with col_lang:
        language = st.radio(
            "Report language",
            options=["fr", "en"],
            format_func=lambda x: "🇫🇷 Français" if x == "fr" else "🇬🇧 English",
            horizontal=True,
            help="Fallback language when Modulate does not detect one. "
                 "Modulate's per-utterance detection takes priority.",
        )
    with col_inspect:
        inspect = st.toggle("🔬 Inspection mode — show step-by-step changes", value=False)

    if st.button("Process audio", type="primary", use_container_width=True):
        suffix = os.path.splitext(uploaded.name)[1] or ".mp3"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(uploaded.read())
            tmp_path = tmp.name
        try:
            cr, pdf_bytes, utterance_steps, detected_lang = run_pipeline(
                tmp_path, collect_steps=inspect, language=language
            )
            pdf_name = os.path.splitext(uploaded.name)[0] + "_CR.pdf"
            if inspect and utterance_steps:
                display_inspection(utterance_steps)
            display_results(cr, pdf_bytes, pdf_name, language=detected_lang)
        except Exception as e:
            st.error(f"Error: {e}")
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
