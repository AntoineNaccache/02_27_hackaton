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
from audio_recorder_streamlit import audio_recorder

from modulate_client import transcribe_sync
from processors import get_processor
from formatter import format_report, generate_pdf

# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="CR Radiologique",
    page_icon="🩻",
    layout="centered",
)

st.title("🩻 Compte Rendu Radiologique")
st.caption(
    "Dictez votre compte rendu ou importez un fichier audio — "
    "le rapport PDF est généré automatiquement."
)

# ── Diff rendering ─────────────────────────────────────────────────────────────


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _word_diff_html(before: str, after: str) -> str:
    """
    Inline word-level diff rendered as HTML.
    Removed text → red strikethrough.  Added text → green bold.
    Unchanged text → plain.
    """
    # Tokenise on whitespace while keeping the whitespace tokens so that
    # joining them back reproduces the original spacing faithfully.
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
    """Expander showing the diff for one processing step."""
    changed = before.strip() != after.strip()
    icon = "✏️" if changed else "✅"
    with st.expander(f"{icon} {label}", expanded=changed):
        if changed:
            st.markdown(_word_diff_html(before, after), unsafe_allow_html=True)
            removed = sum(
                len(before_tokens)
                for op, i1, i2, _, __ in difflib.SequenceMatcher(
                    None,
                    re.split(r"\s+", before.strip()),
                    re.split(r"\s+", after.strip()),
                    autojunk=False,
                ).get_opcodes()
                if op in ("replace", "delete")
                for before_tokens in [re.split(r"\s+", before.strip())[i1:i2]]
            )
            added = sum(
                len(after_tokens)
                for op, _, __, j1, j2 in difflib.SequenceMatcher(
                    None,
                    re.split(r"\s+", before.strip()),
                    re.split(r"\s+", after.strip()),
                    autojunk=False,
                ).get_opcodes()
                if op in ("replace", "insert")
                for after_tokens in [re.split(r"\s+", after.strip())[j1:j2]]
            )
            st.caption(f"−{removed} mot(s) · +{added} mot(s)")
        else:
            st.caption("Aucune modification à cette étape.")


def display_inspection(utterance_steps: list[dict]) -> None:
    """Render the full step-by-step inspection panel."""
    st.divider()
    st.subheader("🔬 Inspection du traitement")

    for i, step in enumerate(utterance_steps):
        speaker = step.get("speaker", "?")
        lang = step.get("language", "fr").upper()
        with st.expander(
            f"Segment {i + 1} — Locuteur : {speaker} ({lang})", expanded=True
        ):
            _render_step_diff(
                "Étape 1 : Ponctuation",
                step["raw"],
                step["after_punctuation"],
            )
            _render_step_diff(
                "Étape 2 : Grammaire",
                step["after_punctuation"],
                step["after_grammar"],
            )
            _render_step_diff(
                "Étape 3 : Noms (médecins / établissements)",
                step["after_grammar"],
                step["after_doctor"],
            )


# ── Pipeline ───────────────────────────────────────────────────────────────────


def run_pipeline(
    audio_path: str, collect_steps: bool = False
) -> tuple[dict, bytes, list[dict]]:
    """
    Run the full 4-step pipeline.

    Returns (cr, pdf_bytes, utterance_steps).
    utterance_steps is populated only when collect_steps=True.
    """
    utterance_steps: list[dict] = []

    with st.status("Traitement en cours…", expanded=True) as status:

        # Step 1 — Transcription
        st.write("**[1/4]** Transcription audio via Modulate…")
        modulate_result = transcribe_sync(audio_path)
        utterances = modulate_result.get("utterances", [])
        if not utterances:
            status.update(label="Erreur de transcription", state="error")
            raise RuntimeError("Modulate n'a retourné aucun segment audio.")
        st.write(f"✅ {len(utterances)} segment(s) transcrits")

        # Step 2 — Language processing (punctuation + grammar + doctor names)
        st.write("**[2/4]** Correction linguistique…")
        processed_parts: list[str] = []
        language = "fr"
        for i, utterance in enumerate(utterances):
            language = utterance.get("language", "fr")
            processor = get_processor(language)

            if collect_steps:
                steps = processor.process_with_steps(utterance)
                utterance_steps.append(
                    {
                        "speaker": utterance.get("speaker", "?"),
                        "language": language,
                        **steps,
                    }
                )
                processed_parts.append(steps["after_doctor"])
            else:
                processed_parts.append(processor.process(utterance))

            st.write(f"  — Segment {i + 1}/{len(utterances)} corrigé")

        combined_text = "\n\n".join(processed_parts)
        st.write("✅ Correction terminée")

        # Step 3 — Formatting agent
        st.write("**[3/4]** Structuration du compte rendu…")
        cr = format_report(combined_text, language=language)
        st.write("✅ Structure JSON générée")

        # Step 4 — PDF generation (temp file → bytes → delete)
        st.write("**[4/4]** Génération du PDF…")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
            tmp_pdf_path = tmp_pdf.name
        generate_pdf(cr, tmp_pdf_path)
        with open(tmp_pdf_path, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(tmp_pdf_path)
        st.write("✅ PDF prêt")

        status.update(label="Traitement terminé !", state="complete", expanded=False)

    return cr, pdf_bytes, utterance_steps


# ── Result display ─────────────────────────────────────────────────────────────


def display_results(cr: dict, pdf_bytes: bytes, pdf_filename: str) -> None:
    st.divider()
    st.subheader("Résultat")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Patient", cr.get("patient_nom", "[Non renseigné]"))
        st.metric("Date de naissance", cr.get("patient_ddn", "[Non renseigné]"))
        st.metric("Date d'examen", cr.get("date_examen", "[Non renseigné]"))
    with col2:
        st.metric("Établissement", cr.get("etablissement", "[Non renseigné]"))
        st.metric("Ville", cr.get("ville", "[Non renseigné]"))
        st.metric("Médecin", cr.get("medecin", "[Non renseigné]"))

    with st.expander("Résultats de l'examen", expanded=True):
        st.text(cr.get("resultats", "[Non renseigné]"))

    st.download_button(
        label="⬇️ Télécharger le PDF",
        data=pdf_bytes,
        file_name=pdf_filename,
        mime="application/pdf",
        type="primary",
        use_container_width=True,
    )


# ── Tabs ───────────────────────────────────────────────────────────────────────

tab_file, tab_record = st.tabs(["📂 Fichier audio", "🎙️ Enregistrement en direct"])

# ── Tab 1: File upload (with optional inspection mode) ─────────────────────────

with tab_file:
    uploaded = st.file_uploader(
        "Déposez votre fichier audio (MP3, WAV, M4A…)",
        type=["mp3", "wav", "m4a", "ogg"],
    )

    if uploaded:
        st.audio(uploaded)

        inspect = st.toggle(
            "🔬 Mode inspection — afficher les modifications étape par étape",
            value=False,
        )

        if st.button("Lancer le traitement", key="btn_file", type="primary", use_container_width=True):
            suffix = os.path.splitext(uploaded.name)[1] or ".mp3"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(uploaded.read())
                tmp_path = tmp.name
            try:
                cr, pdf_bytes, utterance_steps = run_pipeline(tmp_path, collect_steps=inspect)
                pdf_name = os.path.splitext(uploaded.name)[0] + "_CR.pdf"
                if inspect and utterance_steps:
                    display_inspection(utterance_steps)
                display_results(cr, pdf_bytes, pdf_name)
            except Exception as e:
                st.error(f"Erreur : {e}")
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

# ── Tab 2: Live recording ──────────────────────────────────────────────────────

with tab_record:
    st.info(
        "Appuyez sur le bouton microphone pour démarrer l'enregistrement, "
        "puis à nouveau pour l'arrêter."
    )

    audio_bytes = audio_recorder(
        text="",
        recording_color="#e74c3c",
        neutral_color="#2e86c1",
        icon_name="microphone",
        icon_size="2x",
        pause_threshold=60.0,
    )

    if audio_bytes:
        st.audio(audio_bytes, format="audio/wav")
        if st.button("Lancer le traitement", key="btn_record", type="primary", use_container_width=True):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            try:
                cr, pdf_bytes, _ = run_pipeline(tmp_path)
                display_results(cr, pdf_bytes, "enregistrement_CR.pdf")
            except Exception as e:
                st.error(f"Erreur : {e}")
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
