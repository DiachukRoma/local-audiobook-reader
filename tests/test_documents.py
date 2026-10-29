import time

import pytest

from audiobook_reader.document import DocumentError, ScannedPdfError, load_document
from conftest import make_pdf


def test_txt_utf8_ukrainian(tmp_path, uk_paragraphs):
    path = tmp_path / "книга.txt"
    path.write_text("\n\n".join(uk_paragraphs), encoding="utf-8")
    doc = load_document(path)
    assert [p.text for p in doc.paragraphs] == uk_paragraphs
    assert doc.language == "uk"
    assert doc.title == "книга"


def test_txt_cp1251_russian_line_paragraphs(tmp_path, ru_paragraphs):
    path = tmp_path / "book.txt"
    path.write_bytes("\r\n".join(ru_paragraphs).encode("cp1251"))
    doc = load_document(path)
    assert [p.text for p in doc.paragraphs] == ru_paragraphs
    assert doc.language == "ru"


def test_txt_wrapped_lines_are_joined(tmp_path):
    path = tmp_path / "wrapped.txt"
    path.write_text("Перший рядок абзацу\nпродовження абзацу.\n\nДругий абзац.", encoding="utf-8")
    doc = load_document(path)
    assert [p.text for p in doc.paragraphs] == ["Перший рядок абзацу продовження абзацу.", "Другий абзац."]


def test_empty_documents(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    with pytest.raises(DocumentError):
        load_document(empty)
    blank = tmp_path / "blank.txt"
    blank.write_text("\n \n\t\n", encoding="utf-8")
    with pytest.raises(DocumentError):
        load_document(blank)
    with pytest.raises(DocumentError):
        load_document(tmp_path / "missing.txt")
    unsupported = tmp_path / "file.xyz"
    unsupported.write_text("текст", encoding="utf-8")
    with pytest.raises(DocumentError):
        load_document(unsupported)


def test_large_txt_document(tmp_path):
    para = "Це синтетичне речення для перевірки великих книжок, у ньому є кома й крапка."
    path = tmp_path / "large.txt"
    path.write_text("\n\n".join(f"{i}. {para}" for i in range(30_000)), encoding="utf-8")  # ~2.4 MB
    started = time.perf_counter()
    doc = load_document(path)
    assert len(doc.paragraphs) == 30_000
    assert doc.paragraphs[-1].text.startswith("29999.")
    assert time.perf_counter() - started < 10


def test_docx_headings_become_sections(tmp_path, uk_paragraphs):
    import docx

    d = docx.Document()
    d.add_paragraph("Вступний текст перед заголовком.")
    d.add_heading("Розділ 1", level=1)
    d.add_paragraph(uk_paragraphs[1])
    d.add_heading("Розділ 2", level=1)
    d.add_paragraph(uk_paragraphs[2])
    path = tmp_path / "doc.docx"
    d.save(path)
    doc = load_document(path)
    texts = [p.text for p in doc.paragraphs]
    assert texts == ["Вступний текст перед заголовком.", "Розділ 1", uk_paragraphs[1], "Розділ 2", uk_paragraphs[2]]
    assert [s.title for s in doc.sections][1:] == ["Розділ 1", "Розділ 2"]
    assert [p.section for p in doc.paragraphs] == [0, 1, 1, 2, 2]


def _make_epub(path, chapters, spine_order):
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title("Тестова книга")
    book.set_language("uk")
    items = []
    for i, (title, body) in enumerate(chapters):
        item = epub.EpubHtml(title=title, file_name=f"chap_{i:02d}.xhtml", lang="uk")
        item.content = f"<html><body><h1>{title}</h1>{''.join(f'<p>{p}</p>' for p in body)}" \
                       f"<p><sup>1</sup></p></body></html>"
        book.add_item(item)
        items.append(item)
    ordered = [items[i] for i in spine_order]
    book.toc = tuple(epub.Link(it.file_name, it.title, it.file_name) for it in ordered)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *ordered]
    epub.write_epub(str(path), book)


def test_epub_chapter_order_follows_spine(tmp_path):
    chapters = [("Розділ А", ["Текст розділу А."]), ("Розділ Б", ["Текст розділу Б.", "Ще абзац Б."]),
                ("Розділ В", ["Текст розділу В."])]
    path = tmp_path / "book.epub"
    _make_epub(path, chapters, spine_order=[2, 0, 1])  # spine order differs from file order
    doc = load_document(path)
    assert doc.title == "Тестова книга"
    assert [s.title for s in doc.sections] == ["Розділ В", "Розділ А", "Розділ Б"]
    assert [p.text for p in doc.paragraphs] == [
        "Розділ В", "Текст розділу В.", "Розділ А", "Текст розділу А.", "Розділ Б", "Текст розділу Б.", "Ще абзац Б."]
    # Navigation document (table of contents) is not read aloud.
    assert all("chap_" not in p.text for p in doc.paragraphs)
    assert doc.sections[2].start == 4
    assert doc.language == "uk"


def test_pdf_extraction_removes_headers_and_joins_pages(tmp_path):
    pages = [
        ["Перша сторінка. Початок історії про подорож, яка тривала", ],
        ["довго і цікаво. Кінець першого абзацу.", "Другий абзац на другій сторінці."],
        ["Третя сторінка має власний абзац."],
        ["Четверта сторінка завершує книжку."],
    ]
    path = make_pdf(tmp_path / "book.pdf", pages, header="Назва книжки — колонтитул", footer_numbers=True,
                    toc=[[1, "Початок", 1], [1, "Третя частина", 3]])
    doc = load_document(path)
    texts = [p.text for p in doc.paragraphs]
    assert texts[0] == "Перша сторінка. Початок історії про подорож, яка тривала довго і цікаво. Кінець першого абзацу."
    assert "Другий абзац на другій сторінці." in texts
    assert not any("колонтитул" in t for t in texts)
    assert not any(t.strip().isdigit() for t in texts)
    assert doc.page_count == 4
    assert doc.paragraphs[-1].page == 4
    assert [s.title for s in doc.sections] == ["Початок", "Третя частина"]
    assert doc.paragraphs[texts.index("Третя сторінка має власний абзац.")].section == 1


def test_pdf_page_range(tmp_path):
    pages = [[f"Сторінка номер {w}."] for w in ("один", "два", "три", "чотири", "п'ять")]
    path = make_pdf(tmp_path / "range.pdf", pages)
    doc = load_document(path, page_range=(2, 3))
    assert [p.text for p in doc.paragraphs] == ["Сторінка номер два.", "Сторінка номер три."]
    assert [p.page for p in doc.paragraphs] == [2, 3]
    assert doc.page_range == (2, 3)
    # Numbers count from the start of the book, not from the first page of the range.
    assert doc.paragraph_offset == 1
    assert doc.total_paragraphs == 5
    assert [doc.paragraph_number(i) for i in range(2)] == [2, 3]


def test_pdf_page_range_keeps_paragraph_running_into_it(tmp_path):
    pages = [["Перший абзац.", "Цей абзац починається на першій сторінці і"],
             ["продовжується на другій сторінці.", "Другий абзац другої сторінки."]]
    path = make_pdf(tmp_path / "running.pdf", pages)
    doc = load_document(path, page_range=(2, 2))
    assert [p.text for p in doc.paragraphs] == [
        "Цей абзац починається на першій сторінці і продовжується на другій сторінці.",
        "Другий абзац другої сторінки."]
    assert doc.paragraph_number(0) == 2
    assert doc.total_paragraphs == 3


def test_pdf_without_range_numbers_from_one(tmp_path):
    path = make_pdf(tmp_path / "full.pdf", [["Один."], ["Два."]])
    doc = load_document(path)
    assert doc.paragraph_offset == 0
    assert doc.total_paragraphs == 2
    assert doc.paragraph_number(1) == 2


def test_scanned_pdf_detected(tmp_path):
    import pymupdf

    doc = pymupdf.open()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), False)
    pix.clear_with(200)
    for _ in range(2):
        page = doc.new_page()
        page.insert_image(page.rect, pixmap=pix)
    path = tmp_path / "scan.pdf"
    doc.save(str(path))
    with pytest.raises(ScannedPdfError):
        load_document(path)


def test_russian_pdf(tmp_path, ru_paragraphs):
    path = make_pdf(tmp_path / "ru.pdf", [ru_paragraphs])
    doc = load_document(path)
    assert [p.text for p in doc.paragraphs] == ru_paragraphs
    assert doc.language == "ru"


def _ocr_page(number, header, body, footer=None):
    """Blocks as OCR returns them: (top, bottom, text), normalized; running line below the 9 % margin."""
    blocks = [(0.12, 0.135, header)] if header else []
    y = 0.2
    for text in body:
        blocks.append((y, y + 0.06, text))
        y += 0.1
    if footer:
        blocks.append((0.86, 0.875, footer))
    return number, blocks


def test_running_headers_from_ocr_are_skipped():
    from audiobook_reader.document.pdf import _build_paragraphs

    pages = []
    for n in range(1, 13):
        chapter = "РОЗДІЛ ПЕРШИЙ. ДОРОГА" if n <= 6 else "Розділ другий. Повернення"
        # Even pages: book title with OCR noise; odd pages: chapter title; page number in the footer.
        header = (f"{n} ТИХА РІКА" if n % 4 else f"{n} ТИХA РIКА.") if n % 2 == 0 else f"{chapter} {n}"
        pages.append(_ocr_page(n, header, [f"Абзац сторінки {n}.\nДругий рядок абзацу."], footer=f"— {n} —"))
    # The opening page of chapter two: a large heading at the top is part of the text.
    pages[6] = (7, [(0.12, 0.17, "Розділ другий. Повернення")] + pages[6][1][1:])

    paragraphs, _ = _build_paragraphs(pages)
    texts = [p.text for p in paragraphs]
    assert not any("РІКА" in t.upper().replace("I", "І").replace("A", "А") for t in texts)
    assert not any("ПЕРШИЙ" in t for t in texts)
    assert texts.count("Розділ другий. Повернення") == 1
    assert not any("—" in t for t in texts)
    assert len([t for t in texts if t.startswith("Абзац")]) == 12


def test_running_headers_in_short_ocr_range_of_long_book():
    from audiobook_reader.document.pdf import _build_paragraphs

    # 4 recognized pages inside a 100-page scan: the other pages have no text.
    pages = [(n, []) for n in range(1, 101)]
    for n in range(40, 44):
        pages[n - 1] = _ocr_page(n, "Тиха ріка", [f"Абзац сторінки {n}."])
    texts = [p.text for p in _build_paragraphs(pages)[0]]
    assert texts == [f"Абзац сторінки {n}." for n in range(40, 44)]


def test_similar_first_lines_of_ordinary_pages_are_kept():
    from audiobook_reader.document.pdf import _build_paragraphs

    # One-line first blocks in the top zone that differ from page to page are text, not headers.
    first_lines = ["Ранок почався з дощу.", "Він мовчав.", "Наступного дня все змінилось.",
                   "Мати чекала біля воріт.", "Ніхто не знав відповіді."]
    pages = [_ocr_page(n, first_lines[n - 1], ["Ще абзац."]) for n in range(1, 6)]
    texts = [p.text for p in _build_paragraphs(pages)[0]]
    assert texts[::2] == first_lines
