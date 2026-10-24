import pytest

from audiobook_reader.document.chunking import split_segments, split_sentences
from audiobook_reader.storage.settings import Settings
from audiobook_reader.tts.bible import expand_bible_references as bible
from audiobook_reader.tts.text_prep import prepare_for_tts


@pytest.mark.parametrize("text,expected", [
    ("Мт. 5:3", "Матвія, п'ятий розділ, третій вірш"),
    ("Мк 1:15", "Марка, перший розділ, п'ятнадцятий вірш"),
    ("Лк. 15", "Луки, п'ятнадцятий розділ"),
    ("Ів. 3:16", "Івана, третій розділ, шістнадцятий вірш"),
    ("Мт. 5:3-12", "Матвія, п'ятий розділ, вірші з третього по дванадцятий"),
    ("2 Тим. 3:16, 17", "Друге Тимофія, третій розділ, вірші шістнадцятий і сімнадцятий"),
    ("1 Кор. 13:4–7", "Перше Коринтян, тринадцятий розділ, вірші з четвертого по сьомий"),
    ("1Кор.13:4", "Перше Коринтян, тринадцятий розділ, четвертий вірш"),
    ("II Цар. 2:11", "Друга Царів, другий розділ, одинадцятий вірш"),
    ("Мт. 5–7", "Матвія, розділи з п'ятого по сьомий"),
    ("Пс. 22:1", "Псалом двадцять другий, перший вірш"),
    ("Пс. 23", "Псалом двадцять третій"),
    ("Іс. Нав. 1:9", "Ісуса Навина, перший розділ, дев'ятий вірш"),
    ("Іс. 53:5", "Ісаї, п'ятдесят третій розділ, п'ятий вірш"),
    ("Об'явлення 21:4", "Об'явлення, двадцять перший розділ, четвертий вірш"),
    ("Мт. 5:3; 6:1", "Матвія, п'ятий розділ, третій вірш; шостий розділ, перший вірш"),
])
def test_ukrainian_references(text, expected):
    assert bible(text, "uk") == expected


@pytest.mark.parametrize("text,expected", [
    ("Мф. 5:3", "Матфея, пятая глава, третий стих"),
    ("Ин. 3:16", "Иоанна, третья глава, шестнадцатый стих"),
    ("1 Кор. 13:4-7", "Первое Коринфянам, тринадцатая глава, стихи с четвёртого по седьмой"),
    ("Мф. 5-7", "Матфея, главы с пятой по седьмую"),
    ("Пс. 50:3", "Псалом пятидесятый, третий стих"),
    ("Деян. 2:4", "Деяний, вторая глава, четвёртый стих"),
    ("3 Цар. 19:12", "Третья Царств, девятнадцатая глава, двенадцатый стих"),
])
def test_russian_references(text, expected):
    assert bible(text, "ru") == expected


@pytest.mark.parametrize("text", [
    "Як 5 людей прийшли.",       # "Як" (James) without a dot needs chapter:verse
    "Ів 5 разів повторив.",
    "Дії 2 тижні тривали.",
    "Мама 5:3 виграла матч.",    # not a book
    "і т. ін. 5",
])
def test_ordinary_words_are_not_treated_as_references(text):
    assert bible(text, "uk") == text


def test_reference_followed_by_other_book_is_not_swallowed():
    assert bible("Іс. 53:5; 2 Тим. 3:16", "uk") == (
        "Ісаї, п'ятдесят третій розділ, п'ятий вірш; Друге Тимофія, третій розділ, шістнадцятий вірш")


def test_bible_option_and_full_pipeline():
    text = "Як написано (Мт. 5:3), блаженні вбогі духом."
    assert prepare_for_tts(text, "uk") == "Як написано (Матвія, п'ятий розділ, третій вірш), блаженні вбогі духом."
    assert prepare_for_tts(text, "uk", bible=False) == "Як написано (Мт. п'ять:три), блаженні вбогі духом."


def test_custom_abbreviations():
    entries = (("св. Миколая", "святого Миколая", "uk"), ("ап.", "апостол", "all"),
               ("Св. Дух", "Святий Дух", "uk"), ("Св. Дух", "Святой Дух", "ru"))
    assert prepare_for_tts("Свято св. Миколая; ап. Павло; Св.Дух.", "uk", custom=entries) == \
        "Свято святого Миколая; апостол Павло; Святий Дух."
    assert prepare_for_tts("Св. Дух", "ru", custom=entries) == "Святой Дух"
    # Case-sensitive and whole-word only.
    assert prepare_for_tts("Сап. Ап. капітан", "uk", custom=entries) == "Сап. Ап. капітан"


def test_default_church_abbreviations_in_settings():
    entries = Settings().abbreviation_tuples()
    assert prepare_for_tts("Св. Письмо, 33 р. по Р. Х.", "uk", custom=entries) == \
        "Святе Письмо, тридцять три р. по Різдва Христового"
    assert prepare_for_tts("Св. Писание", "ru", custom=entries) == "Священное Писание"


def test_references_are_not_split_into_separate_sentences():
    para = "Блаженні вбогі духом (Мт. 5:3). Див. також 1 Кор. 13:4 і Рим. 8:28. Далі."
    assert split_sentences(para) == [
        "Блаженні вбогі духом (Мт. 5:3).", "Див. також 1 Кор. 13:4 і Рим. 8:28.", "Далі."]
    assert all("Кор." not in s or "13:4" in s for s in split_segments(para, max_chars=60))


@pytest.mark.parametrize("lang", ["uk", "ru"])
def test_every_listed_abbreviation_is_expanded(lang):
    from audiobook_reader.tts.bible import _BOOKS

    for abbreviations, _name, _kind in _BOOKS[lang]:
        for abbr in abbreviations:
            for text in (f"{abbr}. 5:3", f"{abbr} 5:3"):
                assert bible(text, lang) != text, text


@pytest.mark.parametrize("text,expected", [
    ("(Мф. 5, 3)", "(Матвія, п'ятий розділ, третій вірш)"),
    ("(Мт 5, 3-12)", "(Матвія, п'ятий розділ, вірші з третього по дванадцятий)"),
    ("Мт. 5.3", "Матвія, п'ятий розділ, третій вірш"),
    ("Мт. 5:3а", "Матвія, п'ятий розділ, третій вірш"),
    ("Єф. 2:8-9", "Ефесян, другий розділ, вірші з восьмого по дев'ятий"),
    ("1 Іоан. 4:8", "Перше Іоанна, четвертий розділ, восьмий вірш"),
    ("Петр. 1:3", "Петра, перший розділ, третій вірш"),
    ("Ів. 3", "Івана, третій розділ"),
    ("Гл. 5:1", "Галатів, п'ятий розділ, перший вірш"),
])
def test_alternative_formats_and_variants(text, expected):
    assert bible(text, "uk") == expected


def test_ambiguous_abbreviations_need_chapter_and_verse():
    assert bible("Гл. 5", "uk") == "Гл. 5"      # "глава 5"
    assert bible("Пр. 3", "uk") == "Пр. 3"


def test_russian_orthodox_comma_style():
    assert bible("(Мф. 5, 3); Ефес. 2, 8-9", "ru") == (
        "(Матфея, пятая глава, третий стих); Ефесянам, вторая глава, стихи с восьмого по девятый")
