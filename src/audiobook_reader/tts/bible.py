"""Read Bible references aloud: "1 Кор. 13:4-7" -> "Перше Коринтян, тринадцятий розділ,
вірші з четвертого по сьомий".

Only the text sent to the speech model changes; the book on screen is untouched.
A reference is recognized only when a known book abbreviation is followed by a
chapter number, and an abbreviation written without a dot additionally needs
"chapter:verse" — so ordinary words such as "Як 5 людей…" are left alone.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .text_prep import ordinal

BOOK, EPISTLE, PSALM = "book", "epistle", "psalm"

# (abbreviations, spoken name, kind). Apostrophes are normalized to "'" before matching.
_UK_BOOKS: list[tuple[tuple[str, ...], str, str]] = [
    # Old Testament
    (("Бут", "Бт", "Буття"), "Буття", BOOK),
    (("Вих", "Вх", "Вихід"), "Вихід", BOOK),
    (("Лев", "Лв", "Левит"), "Левит", BOOK),
    (("Чис", "Чс", "Числ", "Числа"), "Числа", BOOK),
    (("Повт", "Пвт", "Втор", "Пов", "Повтор", "Второзаконня"), "Повторення Закону", BOOK),
    (("Іс. Нав", "Нав", "Ісус Навин", "Єг", "Ісус", "Ісус. Нав", "Єгошуа"), "Ісуса Навина", BOOK),
    (("Суд", "Сд", "Суддів"), "Суддів", BOOK),
    (("Рут", "Рт"), "Рут", BOOK),
    (("Сам", "Самуїла"), "Самуїла", BOOK),
    (("Цар", "Царів"), "Царів", BOOK),
    (("Хр", "Хрон", "Хронік", "Пар"), "Хронік", BOOK),
    (("Езд", "Ездри", "Ездр"), "Ездри", BOOK),
    (("Неем", "Неемії", "Неєм", "Неємії"), "Неемії", BOOK),
    (("Ест", "Естер", "Есф", "Есфир"), "Естер", BOOK),
    (("Йов", "Йв", "Йова", "Іов", "Іова"), "Йова", BOOK),
    (("Пс", "Псал", "Псалом", "Псалми"), "Псалом", PSALM),
    (("Прип", "Притч", "Приповісті", "Приповістей", "Пр"), "Приповістей", BOOK),
    (("Екл", "Еккл", "Екклезіяста"), "Екклезіяста", BOOK),
    (("Проп",), "Проповідника", BOOK),
    (("Пісн", "Пісн. Пісн", "Пісня Пісень"), "Пісні Пісень", BOOK),
    (("Іс", "Ісаї", "Ісая"), "Ісаї", BOOK),
    (("Єр", "Єрем", "Єремії"), "Єремії", BOOK),
    (("Плач", "Пл"), "Плачу Єремії", BOOK),
    (("Єз", "Єзек", "Єзк", "Єзекіїля"), "Єзекіїля", BOOK),
    (("Дан", "Дн", "Даниїла"), "Даниїла", BOOK),
    (("Ос", "Осії"), "Осії", BOOK),
    (("Йоіл", "Йоїл", "Йл", "Іоїл", "Іоіл", "Йоїла"), "Йоіла", BOOK),
    (("Ам", "Амоса"), "Амоса", BOOK),
    (("Овд", "Авд"), "Овдія", BOOK),
    (("Йона", "Йони", "Йон", "Іон", "Іона"), "Йони", BOOK),
    (("Мих", "Михея"), "Михея", BOOK),
    (("Наум", "Наума"), "Наума", BOOK),
    (("Ав", "Авв", "Авак", "Авакума"), "Авакума", BOOK),
    (("Соф", "Софонії"), "Софонії", BOOK),
    (("Ог", "Аг", "Огія", "Агг"), "Огія", BOOK),
    (("Зах", "Захарії"), "Захарії", BOOK),
    (("Мал", "Малахії"), "Малахії", BOOK),
    # Deuterocanonical
    (("Тов", "Товита"), "Товита", BOOK),
    (("Юдит", "Юдифи", "Юдиф"), "Юдити", BOOK),
    (("Мудр", "Прем"), "Премудрості", BOOK),
    (("Сир", "Сираха"), "Сираха", BOOK),
    (("Вар", "Варуха"), "Варуха", BOOK),
    (("Мак", "Макк"), "Маккавеїв", BOOK),
    # New Testament
    (("Мт", "Мат", "Матв", "Матвія", "Матф", "Мф"), "Матвія", BOOK),
    (("Мк", "Мр", "Мар", "Марка", "Марк"), "Марка", BOOK),
    (("Лк", "Лук", "Луки", "Лука"), "Луки", BOOK),
    (("Ів", "Ін", "Іван", "Івана", "Йн"), "Івана", EPISTLE),
    (("Йо", "Йоан", "Йоана"), "Йоана", EPISTLE),
    (("Іоан", "Іоанн", "Іоанна"), "Іоанна", EPISTLE),
    (("Дії", "Діян", "Діянь", "Ді", "Діяння"), "Дії", BOOK),
    (("Рим", "Рм", "Римлян"), "Римлян", EPISTLE),
    (("Кор", "Коринтян", "Коринтянам", "Корин", "Коринф"), "Коринтян", EPISTLE),
    (("Гал", "Галатів", "Гл", "Галат"), "Галатів", EPISTLE),
    (("Еф", "Ефес", "Ефесян", "Єф", "Єфес", "Єфесян"), "Ефесян", EPISTLE),
    (("Флп", "Фил", "Филп", "Филип'ян", "Филип"), "Филип'ян", EPISTLE),
    (("Кол", "Колос", "Колосян", "Колосс"), "Колосян", EPISTLE),
    (("Сол", "Солун", "Солунян", "Фес", "Фесс"), "Солунян", EPISTLE),
    (("Тим", "Тимофія", "Тимофію", "Тм", "Тимоф"), "Тимофія", EPISTLE),
    (("Тит", "Тита", "Тт"), "Тита", EPISTLE),
    (("Флм", "Филим", "Филимона"), "Филимона", EPISTLE),
    (("Євр", "Евр", "Євреїв", "Євреям"), "Євреїв", EPISTLE),
    (("Як", "Яков", "Якова", "Іак", "Іаков", "Іакова"), "Якова", EPISTLE),
    (("Пет", "Птр", "Пт", "Петра", "Петр"), "Петра", EPISTLE),
    (("Юд", "Юди"), "Юди", EPISTLE),
    (("Об", "Об'яв", "Об'явл", "Об'явлення", "Відкр", "Апок"), "Об'явлення", BOOK),
    (("Одкр", "Одкровення", "Од"), "Одкровення", BOOK),
]

_RU_BOOKS: list[tuple[tuple[str, ...], str, str]] = [
    (("Быт", "Бытие"), "Бытия", BOOK),
    (("Исх", "Исход"), "Исхода", BOOK),
    (("Лев", "Левит"), "Левит", BOOK),
    (("Чис", "Числа"), "Числа", BOOK),
    (("Втор",), "Второзакония", BOOK),
    (("Нав", "Иис. Нав"), "Иисуса Навина", BOOK),
    (("Суд", "Судей"), "Судей", BOOK),
    (("Руф", "Руфь"), "Руфь", BOOK),
    (("Цар", "Царств"), "Царств", BOOK),
    (("Пар", "Паралипоменон"), "Паралипоменон", BOOK),
    (("Езд", "Ездр", "Ездры"), "Ездры", BOOK),
    (("Неем", "Неемии"), "Неемии", BOOK),
    (("Есф", "Есфирь", "Эсф"), "Есфирь", BOOK),
    (("Иов", "Иова"), "Иова", BOOK),
    (("Пс", "Псал", "Псалом", "Псалтирь"), "Псалом", PSALM),
    (("Притч", "Прит", "Притчи"), "Притчей", BOOK),
    (("Еккл", "Екк", "Екклесиаст"), "Екклесиаста", BOOK),
    (("Песн", "Песн. Песн"), "Песни Песней", BOOK),
    (("Ис", "Исаия", "Исаии"), "Исаии", BOOK),
    (("Иер", "Иеремия", "Иеремии"), "Иеремии", BOOK),
    (("Плач",), "Плача Иеремии", BOOK),
    (("Посл. Иер",), "Послания Иеремии", BOOK),
    (("Иез", "Иезек", "Иезекииль"), "Иезекииля", BOOK),
    (("Дан", "Даниил"), "Даниила", BOOK),
    (("Ос", "Осия"), "Осии", BOOK),
    (("Иоил", "Иоиль"), "Иоиля", BOOK),
    (("Ам", "Амос"), "Амоса", BOOK),
    (("Авд", "Авдий"), "Авдия", BOOK),
    (("Ион", "Иона"), "Ионы", BOOK),
    (("Мих", "Михей"), "Михея", BOOK),
    (("Наум",), "Наума", BOOK),
    (("Авв", "Аввакум"), "Аввакума", BOOK),
    (("Соф", "Софония"), "Софонии", BOOK),
    (("Агг", "Аггей"), "Аггея", BOOK),
    (("Зах", "Захария"), "Захарии", BOOK),
    (("Мал", "Малахия"), "Малахии", BOOK),
    (("Тов", "Товит"), "Товита", BOOK),
    (("Иудиф",), "Иудифи", BOOK),
    (("Прем",), "Премудрости Соломона", BOOK),
    (("Сир", "Сирах"), "Сираха", BOOK),
    (("Вар", "Варух"), "Варуха", BOOK),
    (("Мак", "Макк"), "Маккавейская", BOOK),
    (("Мф", "Мт", "Матф", "Матфей", "Матфея"), "Матфея", BOOK),
    (("Мк", "Мр", "Мар", "Марк", "Марка"), "Марка", BOOK),
    (("Лк", "Лук", "Лука", "Луки"), "Луки", BOOK),
    (("Ин", "Иоан", "Иоанн", "Иоанна"), "Иоанна", EPISTLE),
    (("Деян", "Деяния", "Деян. Ап"), "Деяний", BOOK),
    (("Иак", "Иаков", "Иакова"), "Иакова", EPISTLE),
    (("Пет", "Петр", "Петра"), "Петра", EPISTLE),
    (("Иуд", "Иуда", "Иуды"), "Иуды", EPISTLE),
    (("Рим", "Римлянам"), "Римлянам", EPISTLE),
    (("Кор", "Коринфянам", "Коринф"), "Коринфянам", EPISTLE),
    (("Гал", "Галатам", "Галат"), "Галатам", EPISTLE),
    (("Еф", "Ефесянам", "Ефес"), "Ефесянам", EPISTLE),
    (("Флп", "Фил", "Филиппийцам", "Филип", "Филип'ийцам"), "Филиппийцам", EPISTLE),
    (("Кол", "Колоссянам", "Колос", "Колосс"), "Колоссянам", EPISTLE),
    (("Фес", "Сол", "Фессалоникийцам", "Фесс", "Фессал"), "Фессалоникийцам", EPISTLE),
    (("Тим", "Тимофею", "Тимоф"), "Тимофею", EPISTLE),
    (("Тит", "Титу"), "Титу", EPISTLE),
    (("Флм", "Филимону", "Филим"), "Филимону", EPISTLE),
    (("Евр", "Евреям"), "Евреям", EPISTLE),
    (("Откр", "Отк", "Откровение"), "Откровение", BOOK),
    (("Апок", "Апокалипсис"), "Апокалипсис", BOOK),
]

_BOOKS = {"uk": _UK_BOOKS, "ru": _RU_BOOKS}

# Numbered books: "1 Сам." -> "Перша Самуїла" (книга, feminine), "1 Кор." -> "Перше Коринтян" (послання).
_PREFIX = {
    "uk": {BOOK: ("Перша", "Друга", "Третя", "Четверта"), EPISTLE: ("Перше", "Друге", "Третє", "Четверте"),
           PSALM: ("Перший", "Другий", "Третій", "Четвертий")},
    "ru": {BOOK: ("Первая", "Вторая", "Третья", "Четвёртая"), EPISTLE: ("Первое", "Второе", "Третье", "Четвёртое"),
           PSALM: ("Первый", "Второй", "Третий", "Четвёртый")},
}
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}

# Abbreviations that also mean something else ("Гл. 5" = "глава 5", "Пр." = "приклад"):
# they are treated as a book only in the unambiguous "chapter:verse" form.
_NEEDS_VERSE = {"Гл", "Пр"}

_DASH = r"\s*[-–—]\s*"
_VERSE = r"\d+[абвгabcd]?"
_RANGE = rf"{_VERSE}(?:{_DASH}{_VERSE})?"
_VERSES = rf"{_RANGE}(?:\s*,\s*{_RANGE})*"
# chapter[:verses] [ - chapter[:verse] ]. The chapter/verse separator may be ":", "." ("5.3")
# or "," ("Мф. 5, 3" — the usual style of Orthodox literature).
_REF = rf"\d+(?:(?:\s*:\s*|\.(?=\d)|\s*,\s*){_VERSES})?(?:{_DASH}\d+(?:\s*:\s*\d+)?)?"
# Follow-up references after ";" must contain a verse ("6:1"), so "…; 2 Тим. 3:16" is not swallowed.
_MORE_REF = rf"\d+\s*:\s*{_VERSES}(?:{_DASH}\d+(?:\s*:\s*\d+)?)?"


@lru_cache(maxsize=4)
def _pattern(lang: str) -> tuple[re.Pattern, dict[str, tuple[str, str]]]:
    lookup: dict[str, tuple[str, str]] = {}
    for abbreviations, name, kind in _BOOKS[lang]:
        for abbr in abbreviations:
            lookup[_key(abbr)] = (name, kind)
    alternatives = sorted(lookup, key=len, reverse=True)
    # "Іс. Нав" may be written "Іс.Нав" or "Іс. Нав."
    body = "|".join(re.escape(a).replace(r"\.\ ", r"\.\s*").replace(r"\ ", r"\s+") for a in alternatives)
    pattern = re.compile(
        rf"(?<![\w'])(?:(?P<num>[1-4]|IV|I{{1,3}})(?:-?[аеяий])?\s*)?(?P<book>{body})(?P<dot>\.)?\s*"
        rf"(?P<ref>{_REF})(?P<more>(?:\s*;\s*{_MORE_REF})*)(?![\w:])")
    return pattern, lookup


def _key(abbr: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\.\s*", ". ", abbr)).strip()


def _ord(number: int, lang: str, case: str = "n") -> str:
    return ordinal(number, lang, case)


def _verses(spec: str, lang: str) -> str:
    """'3' -> 'третій вірш'; '3-12' -> 'вірші з третього по дванадцятий'; '3, 5' -> 'вірші третій і п'ятий'."""
    parts = [re.sub(r"(?<=\d)[абвгabcd]", "", p.strip()) for p in spec.split(",") if p.strip()]
    word_one, word_many = ("вірш", "вірші") if lang == "uk" else ("стих", "стихи")
    frm, to, conj = ("з", "по", "і") if lang == "uk" else ("с", "по", "и")
    if len(parts) == 1 and not re.search(r"[-–—]", parts[0]):
        return f"{_ord(int(parts[0]), lang)} {word_one}"
    spoken = []
    for part in parts:
        bounds = [int(x) for x in re.split(r"\s*[-–—]\s*", part)]
        if len(bounds) == 2:
            spoken.append(f"{frm} {_ord(bounds[0], lang, 'g')} {to} {_ord(bounds[1], lang)}")
        else:
            spoken.append(_ord(bounds[0], lang))
    listed = spoken[0] if len(spoken) == 1 else ", ".join(spoken[:-1]) + f" {conj} {spoken[-1]}"
    return f"{word_many} {listed}"


def _chapter(number: int, lang: str, kind: str) -> str:
    if kind == PSALM:
        return ""  # the psalm number is spoken right after the word "Псалом"
    if lang == "uk":
        return f"{_ord(number, lang)} розділ"
    return f"{_ord(number, lang, 'fn')} глава"


def _normalize_ref(ref: str) -> str:
    """Unify separators: "5, 3-12" / "5.3" -> "5:3-12"; drop verse-part letters ("3а" -> "3")."""
    ref = re.sub(r"\s+", "", ref)
    ref = re.sub(r"(?<=\d)[абвгabcd](?![\w])", "", ref)
    if ":" not in ref:
        ref = re.sub(r"^(\d+)[.,]", r"\1:", ref)
    return ref


def _reference(ref: str, lang: str, kind: str) -> str:
    ref = _normalize_ref(ref)
    # Cross-chapter range: 5:3-6:2
    cross = re.fullmatch(r"(\d+):(\d+)[-–—](\d+):(\d+)", ref)
    if cross:
        c1, v1, c2, v2 = map(int, cross.groups())
        return f"{_reference(f'{c1}:{v1}', lang, kind)} — {_reference(f'{c2}:{v2}', lang, kind)}"
    chapter_range = re.fullmatch(r"(\d+)[-–—](\d+)", ref)
    if chapter_range:
        a, b = map(int, chapter_range.groups())
        if kind == PSALM:
            word = "Псалми" if lang == "uk" else "Псалмы"
            return f"{word} {'з' if lang == 'uk' else 'с'} {_ord(a, lang, 'g')} по {_ord(b, lang)}"
        if lang == "uk":
            return f"розділи з {_ord(a, lang, 'g')} по {_ord(b, lang)}"
        return f"главы с {_ord(a, lang, 'fg')} по {_ord(b, lang, 'fa')}"
    chapter, _, verses = ref.partition(":")
    pieces = []
    if kind == PSALM:
        pieces.append(_ord(int(chapter), lang))
    else:
        pieces.append(_chapter(int(chapter), lang, kind))
    if verses:
        pieces.append(_verses(verses.replace(",", ", "), lang))
    return ", ".join(pieces)


def expand_bible_references(text: str, lang: str) -> str:
    if lang not in _BOOKS:
        return text
    pattern, lookup = _pattern(lang)

    def repl(m: re.Match) -> str:
        ref = _normalize_ref(m.group("ref"))
        book = _key(m.group("book"))
        if ":" not in ref and (not m.group("dot") or book in _NEEDS_VERSE):
            return m.group(0)  # too ambiguous without chapter:verse
        name, kind = lookup[book]
        num = m.group("num")
        if num:
            index = (_ROMAN.get(num) or int(num)) - 1
            name = f"{_PREFIX[lang][kind][index]} {name}"
        spoken = [_reference(ref, lang, kind)]
        for extra in filter(None, (s.strip() for s in (m.group("more") or "").split(";"))):
            spoken.append(_reference(extra, lang, kind))
        if kind == PSALM:
            if spoken[0].startswith(("Псалми", "Псалмы")):
                return "; ".join(spoken)
            return f"{name} " + "; ".join(spoken)
        return f"{name}, " + "; ".join(spoken)

    return pattern.sub(repl, text)

