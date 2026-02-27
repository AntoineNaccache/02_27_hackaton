import json
import os
from mistralai import Mistral
from dotenv import load_dotenv

load_dotenv()

_mistral_client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))
MISTRAL_MODEL = "mistral-large-latest"

_DOCTORS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "doctors.json")
_RULES_BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "grammar_rules")

# ---------------------------------------------------------------------------
# Tool definitions for the grammar agent
# ---------------------------------------------------------------------------

def _list_available_rule_sets(language: str) -> list[str]:
    rules_dir = os.path.join(_RULES_BASE_DIR, language)
    if not os.path.isdir(rules_dir):
        return []
    return [f[:-3] for f in os.listdir(rules_dir) if f.endswith(".md")]


def _load_rule_set(language: str, rule_set: str) -> str:
    path = os.path.join(_RULES_BASE_DIR, language, f"{rule_set}.md")
    if not os.path.isfile(path):
        return f"Rule set '{rule_set}' not found."
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _build_grammar_tools(language: str) -> list[dict]:
    available = _list_available_rule_sets(language)
    return [
        {
            "type": "function",
            "function": {
                "name": "load_rule_set",
                "description": (
                    "Load a specific grammar or vocabulary rule set to help correct "
                    "the text. Call this for each category of error you detect. "
                    f"Available rule sets: {available}."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "rule_set": {
                            "type": "string",
                            "enum": available,
                            "description": "The name of the rule set to load.",
                        }
                    },
                    "required": ["rule_set"],
                },
            },
        }
    ]


# ---------------------------------------------------------------------------
# Doctor registry
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Base processor
# ---------------------------------------------------------------------------

class BaseProcessor:
    """
    Base class for language-specific text processors.

    Subclasses must define:
      - language: ISO 639-1 code (e.g. "fr", "en") used to locate rule files.
      - punctuation_system_prompt: spoken punctuation -> symbols.
      - grammar_system_prompt: seed instructions for the grammar agent.

    Pipeline per utterance:
      1. Punctuation agent  — simple chat call.
      2. Grammar agent      — agentic loop with tool calling to load rule sets.
      3. Doctor agent       — simple chat call using doctors.json.
    """

    language: str = "en"
    punctuation_system_prompt: str = ""
    grammar_system_prompt: str = ""

    # -- Simple chat call (punctuation & doctor steps) ----------------------

    def _call_mistral(self, system_prompt: str, text: str) -> str:
        response = _mistral_client.chat.complete(
            model=MISTRAL_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
        )
        return response.choices[0].message.content.strip()

    # -- Agentic grammar call with tool use ---------------------------------

    def _call_grammar_agent(self, text: str) -> str:
        """
        Runs an agentic loop:
          - The agent inspects the text and calls load_rule_set() for each
            category of error it detects.
          - After loading all needed rule sets, it returns the corrected text.
        Falls back to a simple chat call when no rule sets exist for the language.
        """
        tools = _build_grammar_tools(self.language)
        if not tools:
            # No rule-set files for this language — skip tool use entirely
            return self._call_mistral(self.grammar_system_prompt, text)

        messages = [
            {"role": "system", "content": self.grammar_system_prompt},
            {"role": "user", "content": text},
        ]

        loaded_rules: dict[str, str] = {}

        # Agentic loop — keep going while the model wants to call tools
        while True:
            response = _mistral_client.chat.complete(
                model=MISTRAL_MODEL,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
            message = response.choices[0].message

            # No tool calls → the agent is done, return the text
            if not message.tool_calls:
                return message.content.strip()

            # Append the assistant turn (with tool_calls)
            messages.append({"role": "assistant", "content": message.content or "", "tool_calls": message.tool_calls})

            # Execute each tool call and append results
            for tool_call in message.tool_calls:
                rule_set = json.loads(tool_call.function.arguments).get("rule_set", "")
                if rule_set not in loaded_rules:
                    loaded_rules[rule_set] = _load_rule_set(self.language, rule_set)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": loaded_rules[rule_set],
                })

    # -- Step-aware pipeline (for UI inspection) ----------------------------

    def process_with_steps(self, utterance: dict) -> dict:
        """Like process(), but returns every intermediate text for diffing."""
        raw_text = utterance.get("text", "")
        after_punctuation = self._call_mistral(self.punctuation_system_prompt, raw_text)
        after_grammar = self._call_grammar_agent(after_punctuation)
        doctor_prompt = _load_doctor_system_prompt()
        after_doctor = (
            self._call_mistral(doctor_prompt, after_grammar) if doctor_prompt else after_grammar
        )
        return {
            "raw": raw_text,
            "after_punctuation": after_punctuation,
            "after_grammar": after_grammar,
            "after_doctor": after_doctor,
        }

    # -- Main pipeline ------------------------------------------------------

    def process(self, utterance: dict) -> str:
        """
        Three-step pipeline:
          1. Punctuation agent — replaces spoken punctuation words with symbols.
          2. Grammar agent    — agentic, loads rule sets on demand, then corrects.
          3. Doctor agent     — corrects doctor/hospital/location names from registry.
        """
        raw_text = utterance.get("text", "")

        # Step 1: punctuation (simple call)
        after_punctuation = self._call_mistral(self.punctuation_system_prompt, raw_text)

        # Step 2: grammar (agentic tool-calling loop)
        after_grammar = self._call_grammar_agent(after_punctuation)

        # Step 3: doctor info correction
        doctor_prompt = _load_doctor_system_prompt()
        final_text = self._call_mistral(doctor_prompt, after_grammar) if doctor_prompt else after_grammar

        return final_text
