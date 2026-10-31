"""Text normalization: the one function grounding and the scorers both use (CLAUDE.md)."""

import re
import unicodedata

_PUNCTUATION_VARIANTS = str.maketrans(
    {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "‐": "-", "‑": "-"}
)
_DECIMAL_POINT = "\x00"  # stands in for "." between digits while other punctuation goes


def normalize_text(text: str) -> str:
    """Lowercase words separated by single spaces, with numbers kept intact.

    - Unicode is folded (NFKC: ligatures, full-width forms) and curly quotes and dashes
      straightened.
    - A word hyphenated across a line break is rejoined ("abate-\\nment" -> "abatement").
    - A thousands comma goes (1,000 -> 1000); a decimal point stays, so "1.5" never equals
      "15", and a decimal comma ("1,5", bilingual tenders) or a list ("1,2") stays apart too.
    - Every other punctuation mark becomes a space ("10%" == "10 %").
    """
    text = unicodedata.normalize("NFKC", text).translate(_PUNCTUATION_VARIANTS)
    text = re.sub(r"(\w)-[ \t]*\n\s*(\w)", r"\1\2", text).lower()
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)  # thousands only: "1,5" is French 1.5
    text = re.sub(r"(?<=\d)\.(?=\d)", _DECIMAL_POINT, text)
    text = re.sub(rf"[^\w\s{_DECIMAL_POINT}]|_", " ", text)
    return " ".join(text.replace(_DECIMAL_POINT, ".").split())
