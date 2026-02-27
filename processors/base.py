import json
import os
from mistralai import Mistral
from dotenv import load_dotenv

load_dotenv()

_mistral_client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))
MISTRAL_MODEL = "mistral-large-latest"

_DOCTORS_FILE = os.path.join(os.path.dirname(__file__), "..", "doctors.json")


def _load_doctor_system_prompt() -> str:
    try:
        with open(_DOCTORS_FILE, "r", encoding="utf-8") as f:
            doctors = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        doctors = []

    if not doctors:
        return ""

    lines = []
    for d in doctors:
        parts = [f"- Name: {d.get('name', '')}"]
        if d.get("specialty"):
            parts.append(f"  Specialty: {d['specialty']}")
        if d.get("hospital"):
            parts.append(f"  Hospital: {d['hospital']}")
        if d.get("location"):
            parts.append(f"  Location: {d['location']}")
        lines.append("\n".join(parts))

    doctor_list = "\n\n".join(lines)

    return f"""
You are a medical transcription corrector. You receive a partially corrected radiology report.

Your only role is to fix doctor names, hospital names, and location names using the verified registry below.
The transcription may have misspelled or phonetically approximated these proper nouns — correct them to exactly match the registry.

Do not modify any other part of the text.

Known doctors registry:
{doctor_list}

Return only the corrected text, without any explanation.
""".strip()


class BaseProcessor:
    """
    Base class for language-specific text processors.

    Subclasses must define:
      - punctuation_system_prompt: spoken punctuation → symbols.
      - grammar_system_prompt: grammar, agreement, medical terms.

    A third doctor-correction step is applied automatically using doctors.json.
    """

    punctuation_system_prompt: str = ""
    grammar_system_prompt: str = ""

    def _call_mistral(self, system_prompt: str, text: str) -> str:
        response = _mistral_client.chat.complete(
            model=MISTRAL_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
        )
        return response.choices[0].message.content.strip()

    def process(self, utterance: dict) -> str:
        """
        Three-step pipeline:
          1. Punctuation agent — replaces spoken punctuation words with symbols.
          2. Grammar agent    — corrects grammar, spelling and medical terms.
          3. Doctor agent     — corrects doctor/hospital/location names from registry.
        Returns the final cleaned string.
        """
        raw_text = utterance.get("text", "")

        # Step 1: punctuation
        after_punctuation = self._call_mistral(self.punctuation_system_prompt, raw_text)

        # Step 2: grammar
        after_grammar = self._call_mistral(self.grammar_system_prompt, after_punctuation)

        # Step 3: doctor info correction (shared across all languages)
        doctor_prompt = _load_doctor_system_prompt()
        if doctor_prompt:
            final_text = self._call_mistral(doctor_prompt, after_grammar)
        else:
            final_text = after_grammar

        return final_text
