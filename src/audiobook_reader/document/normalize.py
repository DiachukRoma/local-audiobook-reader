"""Whitespace and typography cleanup that does not change the meaning of text."""

from __future__ import annotations

import re
import unicodedata

_INVISIBLE = dict.fromkeys(map(ord, "­​‌‍⁠﻿"), None)
_SPACES = re.compile(r"[ \t  -   　]+")
# A word broken by a hyphen at the end of a line: "сло-\nво" -> "слово".
_LINE_HYPHEN = re.compile(r"(\w)[-‐­]\s*\n\s*(?=[a-zа-яіїєґё])")
_NEWLINES = re.compile(r"\s*\n\s*")
_SPACE_BEFORE_PUNCT = re.compile(r" +([,.;:!?»)\]])")
_SPACE_AFTER_OPEN = re.compile(r"([«(\[]) +")


def normalize_text(text: str) -> str:
    """Normalize one paragraph: unify whitespace and rejoin hyphenated line breaks.

    Letters, digits and punctuation are preserved; only invisible characters and
    redundant whitespace are removed.
    """
    text = unicodedata.normalize("NFC", text).translate(_INVISIBLE)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _LINE_HYPHEN.sub(r"\1", text)
    text = _NEWLINES.sub(" ", text)
    text = _SPACES.sub(" ", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = _SPACE_AFTER_OPEN.sub(r"\1", text)
    return text.strip()


def is_readable(text: str) -> bool:
    """True if the text contains something worth reading aloud (letters or digits)."""
    return any(ch.isalnum() for ch in text)
