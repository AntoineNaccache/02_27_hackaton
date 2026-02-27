"""
Grammar correction quality test.

Reads the erroneous French text from grammar_test_input.txt,
runs it through the French grammar agent only (step 2 of the pipeline),
then prints a side-by-side diff so the correction quality can be assessed.
"""

import io
import os
import sys
import difflib

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Allow imports from src/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from processors.fr import FrenchProcessor

INPUT_FILE = os.path.join(os.path.dirname(__file__), "grammar_test_input.txt")

REFERENCE_TEXT = """Pour parler sans ambiguïté, ce dîner à Sainte-Adresse, près du Havre, malgré les effluves embaumés de la mer, malgré les vins de très bons crus, les cuisseaux de veau et les cuissots de chevreuil prodigués par l'amphitryon, fut un vrai guêpier.

Quelles que soient, et quelqu'exiguës qu'aient pu paraître, à côté de la somme due, les arrhes qu'étaient censés avoir données la douairière et le marguillier, il était infâme d'en vouloir pour cela à ces fusiliers jumeaux et mal bâtis, et de leur infliger une raclée, alors qu'ils ne songeaient qu'à prendre des rafraîchissements avec leurs coreligionnaires.

Quoi qu'il en soit, c'est bien à tort que la douairière, par un contresens exorbitant, s'est laissé entraîner à prendre un râteau et qu'elle s'est crue obligée de frapper l'exigeant marguillier sur son omoplate vieillie. Deux alvéoles furent brisés ; une dysenterie se déclara suivie d'une phtisie, et l'imbécillité du malheureux s'accrut.

— Par saint Martin ! quelle hémorragie ! s'écria ce bélître.

À cet événement, saisissant son goupillon, ridicule excédent de bagage, il la poursuivit dans l'église tout entière."""


def print_diff(original: str, corrected: str, label: str) -> None:
    print(f"\n{'-' * 60}")
    print(f"  {label}")
    print(f"{'-' * 60}")
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        corrected.splitlines(keepends=True),
        fromfile="input (with errors)",
        tofile="output (corrected)",
        lineterm="",
    )
    result = "".join(diff)
    print(result if result else "  (no differences)")


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        erroneous_text = f.read()

    print("=" * 60)
    print("GRAMMAR CORRECTION QUALITY TEST")
    print("=" * 60)
    print("\n[INPUT — text with injected errors]\n")
    print(erroneous_text)

    processor = FrenchProcessor()
    # Call only the grammar agent directly (skip punctuation step)
    corrected = processor._call_grammar_agent(erroneous_text)

    print("\n[OUTPUT — after grammar agent]\n")
    print(corrected)

    print_diff(erroneous_text, corrected, "Diff: errors -> grammar agent output")
    print_diff(corrected, REFERENCE_TEXT, "Diff: grammar agent output -> reference")

    print(f"\n{'=' * 60}")


if __name__ == "__main__":
    main()
