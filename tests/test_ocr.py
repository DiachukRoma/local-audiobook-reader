import difflib
import threading

import pytest

from audiobook_reader.document import ScannedPdfError, load_document
from audiobook_reader.document.ocr import (OcrCancelled, clean_ocr_text, create_ocr, group_lines, is_available,
                                           merge_fragments)
from conftest import UK_PARAGRAPHS, make_pdf, make_scanned_pdf

needs_ocr = pytest.mark.skipif(not is_available(), reason="OCR engine not available")

UK_BODY = [
    "Розділ перший",
    "Тиха ранкова година. Сонце підіймалося над рікою, і птахи співали над полем.",
    "Марія відкрила вікно; повітря пахло м'ятою та ґрунтом. Чи прийде сьогодні їжак?",
]
RU_BODY = [
    "Глава первая",
    "Тихий утренний час. Солнце поднималось над рекой, и птицы пели над полем.",
    "Мария открыла окно; воздух пах мятой и землёй. Придёт ли сегодня ёжик?",
]


def _similar(a: str, b: str) -> float:
    norm = lambda t: t.replace("ʼ", "'").replace("’", "'")  # noqa: E731
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


# ------------------------------------------------------------ pure functions
def test_clean_ocr_text_fixes_artifacts():
    assert clean_ocr_text("ранкуạẠồị") == "ранку"
    assert clean_ocr_text("пiдiймалося") == "підіймалося"  # Latin i -> Cyrillic і
    assert clean_ocr_text("Cонце i небо") == "Сонце i небо"  # lone Latin "i" word kept
    assert clean_ocr_text("Python та C++") == "Python та C++"  # real Latin words untouched
    assert clean_ocr_text("Ёжик, їжак, ґанок") == "Ёжик, їжак, ґанок"


def test_group_lines_into_paragraphs():
    h = 0.015
    lines = [
        (0.10, 0.10 + h, 0.12, 0.40, "Розділ перший"),
        (0.15, 0.15 + h, 0.15, 0.88, "Перший рядок абзацу з відступом, який"),
        (0.167, 0.167 + h, 0.12, 0.88, "продовжується на другому рядку і за-"),
        (0.184, 0.184 + h, 0.12, 0.50, "кінчується тут."),
        (0.201, 0.201 + h, 0.15, 0.88, "Новий абзац починається з відступу."),
    ]
    blocks = group_lines(lines)
    assert [b[2] for b in blocks] == [
        "Розділ перший",
        "Перший рядок абзацу з відступом, який\nпродовжується на другому рядку і за-\nкінчується тут.",
        "Новий абзац починається з відступу.",
    ]
    assert group_lines([]) == []


def test_merge_fragments_joins_split_lines_and_sorts():
    h = 0.015
    lines = [
        (0.20, 0.20 + h, 0.12, 0.50, "Другий рядок"),
        (0.10, 0.10 + h, 0.55, 0.88, "розбитий детектором"),
        (0.101, 0.10 + h, 0.12, 0.54, "Перший рядок,"),
        (0.20, 0.20 + h, 0.80, 0.95, "далека колонка"),  # same row, far away: a separate line
    ]
    assert [line[4] for line in merge_fragments(lines)] == [
        "Перший рядок, розбитий детектором", "Другий рядок", "далека колонка"]


# ------------------------------------------------------------ real OCR (Vision or RapidOCR)
@pytest.fixture(scope="module")
def scanned(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("scan")
    text_pdf = make_pdf(tmp / "text.pdf", [UK_BODY, RU_BODY, UK_PARAGRAPHS])
    return text_pdf, make_scanned_pdf(text_pdf, tmp / "scan.pdf")


@needs_ocr
def test_scanned_pdf_requires_ocr_then_reads_ukrainian_and_russian(scanned, tmp_path):
    _text_pdf, scan = scanned
    with pytest.raises(ScannedPdfError) as info:
        load_document(scan)
    assert info.value.pages == 3

    progress = []
    ocr = create_ocr(("uk", "ru"), cache_dir=tmp_path, fingerprint="book")
    doc = load_document(scan, ocr=ocr, progress=lambda done, total: progress.append((done, total)))
    assert progress[-1] == (3, 3)
    assert doc.ocr_pages == 3 and doc.scan_pages == []
    texts = [p.text for p in doc.paragraphs]
    for expected in UK_BODY + RU_BODY:
        best = max(_similar(expected, t) for t in texts)
        assert best > 0.93, (expected, best)
    assert [p.page for p in doc.paragraphs if p.text.startswith("Глава")] == [2]


@needs_ocr
def test_ocr_results_are_cached(scanned, tmp_path, monkeypatch):
    _text_pdf, scan = scanned
    first_ocr = create_ocr(cache_dir=tmp_path, fingerprint="fp")
    first = load_document(scan, ocr=first_ocr)
    assert (tmp_path / "fp.json").is_file()

    def boom(self, pix):
        raise AssertionError("OCR should not run again")

    monkeypatch.setattr(type(first_ocr), "_recognize_pixmap", boom)
    second = load_document(scan, ocr=create_ocr(cache_dir=tmp_path, fingerprint="fp"))
    assert [p.text for p in second.paragraphs] == [p.text for p in first.paragraphs]


@needs_ocr
def test_mixed_pdf_only_scanned_pages_are_recognized(tmp_path):
    text_pdf = make_pdf(tmp_path / "text.pdf", [UK_BODY, RU_BODY, ["Третя сторінка з текстовим шаром."]])
    mixed = make_scanned_pdf(text_pdf, tmp_path / "mixed.pdf", keep_text_pages=(1, 3))
    plain = load_document(mixed)  # mostly text: opens without OCR, scanned page reported
    assert plain.scan_pages == [2]
    assert not any(p.page == 2 for p in plain.paragraphs)

    doc = load_document(mixed, ocr=create_ocr(cache_dir=tmp_path, fingerprint="m"))
    assert doc.ocr_pages == 1
    assert any(p.page == 2 and _similar(RU_BODY[2], p.text) > 0.93 for p in doc.paragraphs)
    assert doc.paragraphs[-1].text == "Третя сторінка з текстовим шаром."

    everything = load_document(mixed, ocr=create_ocr(cache_dir=tmp_path, fingerprint="m2"), ocr_all=True)
    assert everything.ocr_pages == 3


@needs_ocr
def test_ocr_can_be_cancelled(scanned, tmp_path):
    _text_pdf, scan = scanned
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(OcrCancelled):
        load_document(scan, ocr=create_ocr(cache_dir=tmp_path, fingerprint="c"), cancel=cancel)


@needs_ocr
def test_ocr_text_feeds_speech_pipeline(scanned, tmp_path):
    from audiobook_reader.document.chunking import split_segments

    _text_pdf, scan = scanned
    doc = load_document(scan, ocr=create_ocr(cache_dir=tmp_path, fingerprint="s"))
    assert doc.language == "uk"
    for para in doc.paragraphs:
        segments = split_segments(para.text)
        assert segments and " ".join(segments).split() == para.text.split()
