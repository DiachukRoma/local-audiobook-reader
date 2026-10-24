from audiobook_reader.document.chunking import split_segments, split_sentences
from audiobook_reader.document.language import detect_language
from audiobook_reader.document.normalize import normalize_text


def _words(text):
    return text.split()


def test_ukrainian_sentences_and_punctuation(uk_paragraphs):
    para = uk_paragraphs[1]
    sentences = split_sentences(para)
    assert sentences == [
        "Тиха ранкова година.",
        "Сонце підіймалося над рікою, і птахи співали — «Доброго ранку!»",
    ]
    # Joining back reproduces the paragraph exactly (punctuation and quotes kept).
    assert " ".join(sentences) == para


def test_russian_sentences(ru_paragraphs):
    sentences = split_sentences(ru_paragraphs[2])
    assert sentences == ["Мария открыла окно; воздух пах мятой и землёй.", "Придёт ли сегодня ёжик?"]


def test_abbreviations_and_initials_do_not_split():
    text = "Вірш написав Т. Г. Шевченко у 1840 р. на засланні, див. с. 5 і т. д. Далі буде."
    assert split_sentences(text) == [
        "Вірш написав Т. Г. Шевченко у 1840 р. на засланні, див. с. 5 і т. д.",
        "Далі буде.",
    ]
    ru = "См. гл. 3, т. е. начало. Конец."
    assert split_sentences(ru) == ["См. гл. 3, т. е. начало.", "Конец."]


def test_segments_never_split_words_and_respect_limit():
    sentence = "Дуже " + " ".join(f"слово{i}" for i in range(200)) + "."
    segments = split_segments(sentence, max_chars=120)
    assert all(len(s) <= 120 for s in segments)
    assert _words(" ".join(segments)) == _words(sentence)


def test_long_sentence_prefers_clause_boundaries():
    clause = "і довго йшов дощ над полями та лісами"
    sentence = ", ".join([clause] * 12) + "."
    segments = split_segments(sentence, max_chars=150)
    assert len(segments) > 1
    assert all(s.endswith((",", ".")) for s in segments)
    assert " ".join(segments) == sentence


def test_segments_group_short_sentences():
    para = "Так. Ні. Можливо. Побачимо завтра."
    assert split_segments(para, max_chars=200) == [para]


def test_empty_and_whitespace():
    assert split_segments("") == []
    assert split_sentences("   ") == []
    assert normalize_text("  \t\n ") == ""


def test_normalize_whitespace_and_hyphenation():
    raw = "Це  дуже довге   сло-\nво,\nщо   переноситься ."
    assert normalize_text(raw) == "Це дуже довге слово, що переноситься."
    # Real hyphens and apostrophes inside words are preserved.
    assert normalize_text("м'ята, будь-ласка, сім'я") == "м'ята, будь-ласка, сім'я"


def test_unicode_cyrillic_preserved():
    text = "Ґанок, їжак, Єва, ёлка, съезд, ʼ — «лапки» „інші“ … №5"
    assert normalize_text(text) == text


def test_language_detection(uk_paragraphs, ru_paragraphs):
    assert detect_language(uk_paragraphs) == "uk"
    assert detect_language(ru_paragraphs) == "ru"
    assert detect_language(["Hello world, plain English text."]) is None
