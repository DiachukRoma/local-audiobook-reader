"""Split paragraphs into sentences and synthesis-sized segments.

Segments never cut a word in half and keep every character of the source
paragraph: joining the segments with single spaces reproduces the paragraph.
"""

from __future__ import annotations

import re

DEFAULT_MAX_CHARS = 200

# Abbreviations after which a period does not end a sentence (lowercase, without the dot).
_ABBREVIATIONS = {
    # Ukrainian
    "т", "д", "п", "ін", "ім", "див", "напр", "вул", "просп", "пров", "м", "р", "рр",
    "ст", "стор", "с", "тис", "млн", "млрд", "грн", "коп", "проф", "акад", "доц", "канд",
    "зав", "вид", "обл", "р-н", "пл", "буд", "кв", "св", "гр", "зб", "т.зв", "зв", "розд",
    "табл", "рис", "мал", "прим", "ред", "упор", "пер", "див", "ч", "кн", "вип", "н", "е",
    # Russian
    "др", "пр", "см", "напр", "ул", "г", "гг", "в", "вв", "руб", "тыс", "стр", "гл",
    "рис", "изд", "т.е", "т.д", "т.п", "и.о", "им", "проф", "акад", "доц", "канд", "наб",
    # Latin
    "mr", "mrs", "ms", "dr", "prof", "vs", "etc", "e.g", "i.e", "no", "vol", "p", "pp",
}

# Candidate sentence end: terminal punctuation, optional closing quotes/brackets, whitespace.
_SENTENCE_END = re.compile(r"([.!?…]+[»\"”’')\]]*)(\s+)")
# Abbreviations that usually end a sentence when followed by a capital letter.
_FINAL_ABBREVIATION = re.compile(r"(?:\bт\.\s?(?:д|п|ін|е)|\b(?:др|etc|пр))$", re.IGNORECASE)
_SHORT_CAPITALIZED = re.compile(r"(?<![\w'])[A-ZА-ЯЁІЇЄҐ][\w']{0,9}$")
_CLAUSE_BREAK = re.compile(r"[;:,]\s+|\s[—–-]\s")


def _is_abbreviation(before: str) -> bool:
    match = re.search(r"(\S+)$", before)
    if not match:
        return False
    word = match.group(1).lower().lstrip("«\"„“(")
    if word.endswith("."):
        word = word[:-1]
    # Initials such as "Т." in "Т. Шевченко".
    if len(word) == 1 and word.isalpha():
        return True
    return word in _ABBREVIATIONS


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences; abbreviations and initials do not end a sentence."""
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        end = match.end(1)
        punct = match.group(1)
        following = text[match.end():match.end() + 1]
        if punct.startswith(".") and len(punct.rstrip("»\"”’')]")) == 1:
            before = text[start:match.start(1)]
            ends_sentence = following.isupper() and _FINAL_ABBREVIATION.search(before)
            if not ends_sentence and _is_abbreviation(before):
                continue
            # "3. 5" or a lowercase continuation is unlikely to be a new sentence.
            if following and following.islower():
                continue
            # A short capitalized abbreviation before a number is a reference: "Мт. 5:3", "1 Кор. 13:4".
            if following.isdigit() and _SHORT_CAPITALIZED.search(before):
                continue
        sentence = text[start:end].strip()
        if sentence:
            sentences.append(sentence)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _split_long(sentence: str, max_chars: int) -> list[str]:
    """Split an over-long sentence at clause boundaries, then at word boundaries."""
    if len(sentence) <= max_chars:
        return [sentence]
    pieces: list[str] = []
    rest = sentence
    while len(rest) > max_chars:
        window = rest[: max_chars + 1]
        cut = -1
        for match in _CLAUSE_BREAK.finditer(window):
            if match.start() >= max_chars // 3:
                cut = match.end()
        if cut <= 0:
            cut = window.rfind(" ")
        if cut <= 0:
            # A single "word" longer than max_chars (e.g. a URL): cut at the next space.
            nxt = rest.find(" ", max_chars)
            cut = nxt if nxt > 0 else len(rest)
        piece = rest[:cut].strip()
        if piece:
            pieces.append(piece)
        rest = rest[cut:].strip()
    if rest:
        pieces.append(rest)
    return pieces


def split_segments(paragraph: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """Group sentences of a paragraph into segments of at most ``max_chars`` characters.

    A sentence is only split further when it alone exceeds ``max_chars``.
    """
    segments: list[str] = []
    current = ""
    for sentence in split_sentences(paragraph):
        for piece in _split_long(sentence, max_chars):
            if current and len(current) + 1 + len(piece) > max_chars:
                segments.append(current)
                current = piece
            else:
                current = f"{current} {piece}" if current else piece
    if current:
        segments.append(current)
    return segments
