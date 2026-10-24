"""Prepare a text segment for speech synthesis.

This only changes what is *sent to the TTS model*; the document shown to the user
is never modified. Supertonic 3 reads multi-digit numbers (especially years)
unreliably in Ukrainian and Russian, so numbers are spelled out with num2words,
and a small set of unambiguous abbreviations is expanded.
"""

from __future__ import annotations

import re
from functools import lru_cache

from num2words import num2words

# Characters the model does not support, mapped to supported equivalents.
_CHAR_MAP = str.maketrans({
    "ʼ": "'",   # MODIFIER LETTER APOSTROPHE (official Ukrainian apostrophe)
    "’": "'",
    "‘": "'",
    "`": "'",
    "„": "«",   # „
    "“": "»",   # “ (closing quote in „…“ pairs)
    "″": '"',
    "[": "(",
    "]": ")",
    "|": ",",
    "_": " ",
    "#": " ",
    "\\": " ",
    "@": " ",
})

_ABBREVIATIONS = {
    "uk": [
        (r"\bі т\.\s?д\.", "і так далі"),
        (r"\bі т\.\s?ін\.", "і таке інше"),
        (r"\bі т\.\s?п\.", "і тому подібне"),
        (r"\bт\.\s?зв\.", "так званий"),
        (r"\bдив\.", "дивіться"),
        (r"\bнапр\.", "наприклад"),
        (r"(?<=\d) ?тис\.", " тисяч"),
        (r"(?<=\d) ?млн\b\.?", " мільйонів"),
        (r"(?<=\d) ?млрд\b\.?", " мільярдів"),
        (r"(?<=\d) ?грн\b\.?", " гривень"),
        (r"(?<=\d) ?коп\.", " копійок"),
        (r"\s*₴", " гривень"),
        (r"№\s*", "номер "),
        (r"§\s*", "параграф "),
    ],
    "ru": [
        (r"\bи т\.\s?д\.", "и так далее"),
        (r"\bи т\.\s?п\.", "и тому подобное"),
        (r"\bт\.\s?е\.", "то есть"),
        (r"\bт\.\s?н\.", "так называемый"),
        (r"\bсм\.", "смотри"),
        (r"\bнапр\.", "например"),
        (r"(?<=\d) ?тыс\.", " тысяч"),
        (r"(?<=\d) ?млн\b\.?", " миллионов"),
        (r"(?<=\d) ?млрд\b\.?", " миллиардов"),
        (r"(?<=\d) ?руб\.", " рублей"),
        (r"(?<=\d) ?коп\.", " копеек"),
        (r"\s*₽", " рублей"),
        (r"№\s*", "номер "),
        (r"§\s*", "параграф "),
    ],
}

_PERCENT_FORMS = {"uk": ("відсоток", "відсотки", "відсотків"), "ru": ("процент", "процента", "процентов")}
_DECIMAL = re.compile(r"(?<![\d.,])(\d+)[,.](\d+)(?![\d]|[.,]\d)")
_GROUPED = re.compile(r"(?<!\d)(\d{1,3})(?:[   ](\d{3}))+(?!\d)")
_INTEGER = re.compile(r"\d+")

# Years: (preposition)? YEAR (year word) — the year word determines the case.
_YEAR_UK = re.compile(
    r"(?P<prep>\b[уУвВ]\s+)?(?P<year>\b\d{3,4})\s*(?P<word>році|року|рік|роком|р\.|рр\.|роки|років)(?!\w)")
_YEAR_RU = re.compile(
    r"(?P<prep>\b[вВ]\s+)?(?P<year>\b\d{3,4})\s*(?P<word>году|года|год|годом|г\.|гг\.|годы|годов)(?!\w)")
_ORDINAL_SUFFIX = re.compile(r"\b(\d+)-(ого|ому|ий|ій|го|му|ої|ми|ых|ая|ой|й|а|я|ї|х|м)\b")


def _plural_form(number: int, forms: tuple[str, str, str]) -> str:
    n = abs(number) % 100
    if 11 <= n <= 14:
        return forms[2]
    n %= 10
    if n == 1:
        return forms[0]
    if 2 <= n <= 4:
        return forms[1]
    return forms[2]


@lru_cache(maxsize=4096)
def cardinal(number: int, lang: str) -> str:
    if number >= 10**15:
        return " ".join(cardinal(int(d), lang) for d in str(number))
    words = num2words(number, lang=lang)
    if lang == "uk" and words.startswith("одна тисяча"):
        words = words[len("одна "):]
    elif lang == "ru" and words.startswith("одна тысяча"):
        words = words[len("одна "):]
    return words


def _inflect_uk_ordinal(words: str, case: str) -> str:
    """Inflect the last word of a Ukrainian masculine ordinal ("перший", "третій")."""
    head, _, last = words.rpartition(" ")
    if last.endswith("ій"):  # soft stem: третій
        stem = last[:-2]
        endings = {"n": "ій", "g": "ього", "l": "ьому", "d": "ьому", "i": "ім", "fn": "я", "fg": "ьої", "pn": "і", "pg": "іх"}
    else:  # hard stem: перший
        stem = last[:-2]
        endings = {"n": "ий", "g": "ого", "l": "ому", "d": "ому", "i": "им", "fn": "а", "fg": "ої", "pn": "і", "pg": "их"}
    inflected = stem + endings.get(case, endings["n"])
    return f"{head} {inflected}" if head else inflected


@lru_cache(maxsize=4096)
def ordinal(number: int, lang: str, case: str = "n") -> str:
    """Ordinal number. ``case``: n, g, d, l (locative), i, fn/fg/fa (feminine), pn/pg (plural)."""
    if lang == "uk":
        words = num2words(number, lang="uk", to="ordinal")
        if words.startswith("одна тисяча"):
            words = words[len("одна "):]
        return _inflect_uk_ordinal(words, case)
    ru_case = {"l": "p", "fn": "n", "fg": "g", "fa": "a", "pn": "n", "pg": "g"}.get(case, case)
    kwargs: dict = {"case": ru_case}
    if case in ("fn", "fg", "fa"):
        kwargs["gender"] = "f"
    if case in ("pn", "pg"):
        kwargs["plural"] = True
    try:
        words = num2words(number, lang="ru", to="ordinal", **kwargs)
    except Exception:
        words = num2words(number, lang="ru", to="ordinal")
    if words.startswith("одна тысяча"):
        words = words[len("одна "):]
    return words


_UK_YEAR_CASE = {"році": "l", "року": "g", "рік": "n", "роком": "i", "роки": "pn", "років": "pg"}
_RU_YEAR_CASE = {"году": "l", "года": "g", "год": "n", "годом": "i", "годы": "pn", "годов": "pg"}


def _expand_years(text: str, lang: str) -> str:
    if lang == "uk":
        pattern, cases = _YEAR_UK, _UK_YEAR_CASE
        # abbreviation -> (word after a preposition, word otherwise)
        abbrev = {"р.": ("році", "року"), "рр.": ("років", "років")}
    else:
        pattern, cases = _YEAR_RU, _RU_YEAR_CASE
        abbrev = {"г.": ("году", "года"), "гг.": ("годов", "годов")}

    def repl(m: re.Match) -> str:
        prep = m.group("prep") or ""
        word = m.group("word")
        if word in abbrev:
            word = abbrev[word][0 if prep else 1]
        return f"{prep}{ordinal(int(m.group('year')), lang, cases[word])} {word}"

    return pattern.sub(repl, text)


_UK_SUFFIX_CASE = {"ий": "n", "ій": "n", "й": "n", "го": "g", "ого": "g", "му": "l", "ому": "l",
                   "а": "fn", "я": "fn", "ї": "fg", "ої": "fg", "х": "pg", "ми": "i", "м": "i"}
_RU_SUFFIX_CASE = {"й": "n", "ий": "n", "го": "g", "ого": "g", "му": "d", "ому": "d", "м": "l",
                   "я": "fn", "ая": "fn", "ой": "fg", "х": "pg", "ых": "pg"}


def _expand_ordinal_suffixes(text: str, lang: str) -> str:
    table = _UK_SUFFIX_CASE if lang == "uk" else _RU_SUFFIX_CASE

    def repl(m: re.Match) -> str:
        case = table.get(m.group(2))
        if case is None:
            return m.group(0)
        return ordinal(int(m.group(1)), lang, case)

    return _ORDINAL_SUFFIX.sub(repl, text)


def _expand_numbers(text: str, lang: str) -> str:
    text = _GROUPED.sub(lambda m: m.group(0).replace(" ", "").replace(" ", "").replace(" ", ""), text)
    text = _expand_years(text, lang)
    text = _expand_ordinal_suffixes(text, lang)

    def percent(m: re.Match) -> str:
        number = int(m.group(1))
        return f"{cardinal(number, lang)} {_plural_form(number, _PERCENT_FORMS[lang])}"

    text = re.sub(r"(\d+)\s*%", percent, text)

    def decimal(m: re.Match) -> str:
        whole, frac = m.group(1), m.group(2)
        sep = " кома " if lang == "uk" else " целых "
        return f"{cardinal(int(whole), lang)}{sep}{cardinal(int(frac), lang)}"

    text = _DECIMAL.sub(decimal, text)

    def integer(m: re.Match) -> str:
        digits = m.group(0)
        if len(digits) > 1 and digits.startswith("0"):
            return " ".join(cardinal(int(d), lang) for d in digits)
        return cardinal(int(digits), lang)

    return _INTEGER.sub(integer, text)


Abbreviation = tuple[str, str, str]  # (written form, spoken form, "all" | "uk" | "ru")


@lru_cache(maxsize=32)
def _custom_pattern(entries: tuple[Abbreviation, ...], lang: str) -> tuple[re.Pattern, dict[str, str]] | None:
    table: dict[str, str] = {}
    for written, spoken, entry_lang in entries:
        written = written.translate(_CHAR_MAP).strip()
        if written and spoken.strip() and entry_lang in ("all", lang):
            table[_custom_key(written)] = spoken.strip()
    if not table:
        return None
    alternatives = []
    for written in sorted(table, key=len, reverse=True):
        body = re.escape(written).replace(r"\.\ ", r"\.\s*").replace(r"\ ", r"\s+")
        tail = "" if written.endswith(".") else r"(?!\w)"
        alternatives.append(body + tail)
    return re.compile(r"(?<![\w])(?:" + "|".join(alternatives) + ")"), table


def _custom_key(written: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\.\s*(?=\S)", ". ", written)).strip()


def expand_custom(text: str, lang: str, entries: tuple[Abbreviation, ...]) -> str:
    """Replace the user's own abbreviations (case-sensitive, whole words only)."""
    compiled = _custom_pattern(tuple(entries), lang)
    if compiled is None:
        return text
    pattern, table = compiled
    return pattern.sub(lambda m: table.get(_custom_key(m.group(0)), m.group(0)), text)


def prepare_for_tts(text: str, lang: str, expand: bool = True, bible: bool = True,
                    custom: tuple[Abbreviation, ...] = ()) -> str:
    """Return the text that should be synthesized for a segment."""
    text = text.translate(_CHAR_MAP)
    if expand and lang in _ABBREVIATIONS:
        if custom:
            text = expand_custom(text, lang, custom)
        if bible:
            from .bible import expand_bible_references
            text = expand_bible_references(text, lang)
        for pattern, replacement in _ABBREVIATIONS[lang]:
            text = re.sub(pattern, replacement, text)
        text = _expand_numbers(text, lang)
    return re.sub(r"\s+", " ", text).strip()
