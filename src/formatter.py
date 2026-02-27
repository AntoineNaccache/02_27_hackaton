"""
Compte Rendu formatter.

Two steps:
  1. Formatting agent (Mistral) — reads internal guidelines and restructures the
     processed text into a standard CR JSON schema.
  2. PDF generator (fpdf2)      — renders the structured CR to a PDF file.
"""

import json
import os
from datetime import date
from mistralai import Mistral
from fpdf import FPDF
from dotenv import load_dotenv

load_dotenv()

_mistral_client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))
MISTRAL_MODEL = "mistral-large-latest"

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# ---------------------------------------------------------------------------
# Guidelines loader
# ---------------------------------------------------------------------------

_GUIDELINES_FILES = {
    "fr": "cr_guidelines_fr.md",
}


def _load_guidelines(language: str) -> str:
    filename = _GUIDELINES_FILES.get(language, _GUIDELINES_FILES.get("fr"))
    path = os.path.join(_DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# CR JSON schema
# ---------------------------------------------------------------------------

_CR_SCHEMA = {
    "etablissement": "string — hospital/clinic name, or '[Non renseigné]'",
    "ville": "string — city, or '[Non renseigné]'",
    "date_examen": "string — exam date (e.g. '27 février 2022'), use today's date if not found in text",
    "patient_nom": "string — patient full name, or '[Non renseigné]'",
    "patient_ddn": "string — date of birth, or '[Non renseigné]'",
    "resultats": "string — the input text reproduced verbatim, without any modification",
    "medecin": "string — signing doctor full name with title (e.g. 'Docteur Philippe Naccache')",
    "lieu_signature": "string — signing location, or '[Non renseigné]'",
    "date_signature": "string — signing date, or '[Non renseigné]'",
}

_SYSTEM_PROMPT_TEMPLATE = """
Tu es un expert en mise en forme de comptes rendus radiologiques français.

Tu reçois un texte de compte rendu déjà corrigé grammaticalement. Ton rôle est de le restructurer en JSON valide en respectant scrupuleusement les directives internes ci-dessous.

DIRECTIVES INTERNES :
{guidelines}

SCHÉMA JSON ATTENDU (retourne UNIQUEMENT ce JSON, sans balises markdown, sans explication) :
{schema}

Règles absolues :
- Si une information n'est pas présente dans le texte source, utilise "[Non renseigné]".
- Ne modifie pas les chiffres, dates, noms propres ou mesures.
- Le champ "resultats" doit être le texte d'entrée reproduit mot pour mot, sans aucune modification.
""".strip()


# ---------------------------------------------------------------------------
# Formatting agent
# ---------------------------------------------------------------------------

def format_report(processed_text: str, language: str = "fr") -> dict:
    """
    Call Mistral to restructure the processed text into a CR JSON dict
    following the internal formatting guidelines.
    """
    guidelines = _load_guidelines(language)
    schema_str = json.dumps(_CR_SCHEMA, ensure_ascii=False, indent=2)

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        guidelines=guidelines,
        schema=schema_str,
    )

    response = _mistral_client.chat.complete(
        model=MISTRAL_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": processed_text},
        ],
    )

    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences if the model wrapped the JSON
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------

# fpdf2 built-in fonts only cover Latin-1 (ISO 8859-1).
# Map common Unicode typography produced by Mistral to Latin-1 equivalents.
_LATIN1_MAP = str.maketrans({
    "\u2014": "-",    # em dash  —
    "\u2013": "-",    # en dash  –
    "\u2018": "'",    # left single quote  '
    "\u2019": "'",    # right single quote  '
    "\u201c": '"',    # left double quote  "
    "\u201d": '"',    # right double quote  "
    "\u2026": "...",  # ellipsis  …
    "\u0153": "oe",   # ligature  œ
    "\u0152": "OE",   # ligature  Œ
    "\u2012": "-",    # figure dash
    "\u00b7": ".",    # middle dot  ·
})


def _l1(text: str) -> str:
    """Sanitize a string to Latin-1 safe characters for fpdf2 built-in fonts."""
    return text.translate(_LATIN1_MAP)


def _strip_markdown(text: str) -> str:
    """Remove markdown emphasis markers that Mistral may add (**, *, __)."""
    import re
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
    return text


# ---------------------------------------------------------------------------
# PDF generator
# ---------------------------------------------------------------------------

class _CRDocument(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 6, "COMPTE RENDU D'EXAMEN RADIOLOGIQUE - DOCUMENT CONFIDENTIEL", align="C")
        self.ln(4)
        self.set_draw_color(180, 180, 180)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()} - Genere le {date.today().strftime('%d/%m/%Y')}", align="C")


def _section_title(pdf: FPDF, title: str):
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(30, 80, 160)
    pdf.cell(0, 7, _l1(title.upper()), ln=True)
    pdf.set_draw_color(30, 80, 160)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(3)
    pdf.set_text_color(0, 0, 0)


_LABEL_W = 50   # mm — fixed label column width
_VALUE_W = 120  # mm — A4 usable width (170) minus label column


def _field_row(pdf: FPDF, label: str, value: str):
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(_LABEL_W, 6, _l1(f"{label} :"), ln=False)
    pdf.set_x(pdf.l_margin + _LABEL_W)
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(_VALUE_W, 6, _l1(value))
    pdf.set_x(pdf.l_margin)


def _body_text(pdf: FPDF, text: str):
    pdf.set_font("Helvetica", "", 10)
    for paragraph in _strip_markdown(text).split("\n"):
        paragraph = paragraph.strip()
        if paragraph:
            pdf.multi_cell(0, 6, _l1(paragraph))
            pdf.ln(2)


def generate_pdf(cr: dict, output_path: str) -> None:
    """Render a CR dict (from format_report) to a PDF file."""
    pdf = _CRDocument()
    pdf.set_margins(20, 20, 20)
    pdf.add_page()

    # ── Main title ──────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 10, "COMPTE RENDU D'EXAMEN RADIOLOGIQUE", align="C", ln=True)
    pdf.ln(2)

    # ── Établissement block ─────────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 5, _l1(f"{cr.get('etablissement', '[Non renseigné]')}  -  {cr.get('ville', '')}"), align="C", ln=True)
    pdf.cell(0, 5, _l1(f"Date de l'examen : {cr.get('date_examen', '[Non renseigné]')}"), align="C", ln=True)
    pdf.ln(6)
    pdf.set_text_color(0, 0, 0)

    # ── Patient ─────────────────────────────────────────────────────────────
    _section_title(pdf, "Informations patient")
    _field_row(pdf, "Nom", cr.get("patient_nom", "[Non renseigné]"))
    _field_row(pdf, "Date de naissance", cr.get("patient_ddn", "[Non renseigné]"))
    pdf.ln(4)

    # ── Résultats ────────────────────────────────────────────────────────────
    _section_title(pdf, "Résultats")
    _body_text(pdf, cr.get("resultats", "[Non renseigné]"))
    pdf.ln(6)

    # ── Signature ────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(50, 50, 50)
    signature_lines = [
        cr.get("medecin", "[Non renseigné]"),
        cr.get("lieu_signature", ""),
        f"Le {cr.get('date_signature', '')}",
    ]
    for line in signature_lines:
        if line.strip():
            pdf.cell(0, 5, _l1(line), align="R", ln=True)

    pdf.output(output_path)
    print(f"[PDF] Saved to: {output_path}")
