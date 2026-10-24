"""Lightweight Ukrainian / Russian language detection based on distinctive letters."""

from __future__ import annotations

from collections.abc import Iterable

UKRAINIAN = "uk"
RUSSIAN = "ru"

# Letters that exist in only one of the two alphabets.
_UK_ONLY = set("іїєґІЇЄҐ")
_RU_ONLY = set("ыэёъЫЭЁЪ")
# Frequent short words that differ between the languages.
_UK_WORDS = {"і", "та", "що", "це", "як", "але", "його", "вона", "від", "він", "ми", "й", "до", "не"}
_RU_WORDS = {"и", "что", "это", "как", "но", "его", "она", "от", "он", "мы", "не", "до", "был", "была"}


def detect_language(texts: Iterable[str], sample_chars: int = 50_000) -> str | None:
    """Return "uk", "ru" or None when the text has (almost) no Cyrillic."""
    uk = ru = cyrillic = 0
    seen = 0
    for text in texts:
        for ch in text:
            if ch in _UK_ONLY:
                uk += 3
            elif ch in _RU_ONLY:
                ru += 3
            if "Ѐ" <= ch <= "ӿ":
                cyrillic += 1
        for word in text.lower().split():
            word = word.strip(".,;:!?«»\"'()—-")
            if word in _UK_WORDS and word not in _RU_WORDS:
                uk += 1
            elif word in _RU_WORDS and word not in _UK_WORDS:
                ru += 1
        seen += len(text)
        if seen >= sample_chars:
            break
    if cyrillic < 20:
        return None
    return UKRAINIAN if uk >= ru else RUSSIAN
