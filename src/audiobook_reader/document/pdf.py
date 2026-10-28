"""PDF loader based on PyMuPDF.

* blocks are read in reading order (top-to-bottom, column-aware sort),
* repeated running headers/footers and bare page numbers are removed,
* paragraphs broken by a page boundary are re-joined,
* scanned PDFs (no text layer) are detected and reported.
"""

from __future__ import annotations

import re
import threading
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from .model import Document, DocumentError, Paragraph, ScannedPdfError, Section
from .normalize import is_readable, normalize_text

_MARGIN = 0.09  # fraction of page height treated as header/footer zone
_PAGE_NUMBER = re.compile(r"^[\s\-–—]*(?:\d{1,4}|[ivxlcdm]{1,6})[\s\-–—]*$", re.IGNORECASE)
_DIGITS = re.compile(r"\d+")
_SENTENCE_TERMINATORS = tuple(".!?…:»\"”)")


def _signature(text: str) -> str:
    return _DIGITS.sub("#", text.lower()).strip()


def _page_blocks(page) -> list[tuple[float, float, str]]:
    """Return (y0, y1, text) for every text block of a page in reading order."""
    height = page.rect.height or 1
    blocks = []
    for x0, y0, x1, y1, text, _no, block_type in page.get_text("blocks", sort=True):
        if block_type != 0:
            continue
        cleaned = text.strip()
        if cleaned:
            blocks.append((y0 / height, y1 / height, cleaned))
    return blocks


def _should_join(previous: str, following: str) -> bool:
    """A paragraph continues on the next page when it has no terminal punctuation
    and the next block starts with a lowercase letter."""
    if not previous or not following:
        return False
    if previous.rstrip().endswith(_SENTENCE_TERMINATORS):
        return False
    first = following.lstrip("«\"„(—– ")[:1]
    return first.islower() or previous.endswith(("-", ","))


def _needs_ocr(page, blocks: list) -> bool:
    """A page is a scan when it has (almost) no text layer but contains images."""
    return sum(len(t) for *_, t in blocks) < 20 and bool(page.get_images(full=False))


def load_pdf(path: Path, page_range: tuple[int, int] | None = None, ocr=None, ocr_all: bool = False,
             progress: Callable[[int, int], None] | None = None, cancel: threading.Event | None = None) -> Document:
    """Load a PDF. With ``ocr`` (a PageOcr), scanned pages — or all pages when ``ocr_all`` —
    are recognized locally; otherwise a mostly scanned PDF raises ScannedPdfError."""
    import pymupdf

    try:
        pdf = pymupdf.open(str(path))
    except Exception as exc:
        raise DocumentError(f"Не вдалося відкрити PDF: {exc}") from exc

    ocr_pages = 0
    with pdf:
        if pdf.needs_pass:
            raise DocumentError("PDF захищений паролем.")
        page_count = pdf.page_count
        first, last = page_range or (1, page_count)
        first = max(1, min(first, page_count))
        last = max(first, min(last, page_count))

        pages: list[tuple[int, list[tuple[float, float, str]]]] = []
        scan_pages: list[int] = []
        for number in range(first, last + 1):
            page = pdf.load_page(number - 1)
            blocks = _page_blocks(page)
            if _needs_ocr(page, blocks):
                scan_pages.append(number)
            pages.append((number, blocks))

        if ocr is not None:
            todo = [n for n, _ in pages] if ocr_all else list(scan_pages)
            try:
                for done, number in enumerate(todo, start=1):
                    if cancel is not None and cancel.is_set():
                        from .ocr import OcrCancelled
                        raise OcrCancelled()
                    blocks = ocr.recognize_page(pdf.load_page(number - 1))
                    pages[number - first] = (number, blocks)
                    if progress:
                        progress(done, len(todo))
            finally:
                ocr.flush()
            ocr_pages = len(todo)
            scan_pages = []

        # Pages outside the range are read too (text layer only, no OCR) so that paragraph numbers,
        # header/footer detection and a paragraph running into the range match the whole book.
        all_pages = pages
        if page_range:
            before = [(n, _page_blocks(pdf.load_page(n - 1))) for n in range(1, first)]
            after = [(n, _page_blocks(pdf.load_page(n - 1))) for n in range(last + 1, page_count + 1)]
            all_pages = before + pages + after

        toc = pdf.get_toc(simple=True)
        metadata_title = (pdf.metadata or {}).get("title", "").strip()

    if ocr is None and scan_pages and len(scan_pages) * 2 > len(pages):
        raise ScannedPdfError(
            "Цей PDF складається зі сканованих зображень і не містить текстового шару. "
            "Для читання потрібне розпізнавання тексту (OCR).", pages=len(scan_pages))

    book, last_pages = _build_paragraphs(all_pages)
    # Paragraphs of the range, including one that starts on an earlier page and runs into it.
    selected = [i for i, para in enumerate(book) if last_pages[i] >= first and (para.page or 0) <= last]
    paragraphs = [book[i] for i in selected]
    if not paragraphs:
        raise DocumentError("У вибраному діапазоні сторінок немає тексту.")

    sections = _sections_from_toc(toc, paragraphs)
    if sections:
        section_index = 0
        updated = []
        for i, para in enumerate(paragraphs):
            while section_index + 1 < len(sections) and sections[section_index + 1].start <= i:
                section_index += 1
            updated.append(Paragraph(para.text, section_index, para.page))
        paragraphs = updated

    return Document(
        path=path,
        title=metadata_title or path.stem,
        format="pdf",
        paragraphs=paragraphs,
        sections=sections,
        page_count=page_count,
        page_range=(first, last) if page_range else None,
        scan_pages=scan_pages,
        ocr_pages=ocr_pages,
        paragraph_offset=selected[0],
        book_paragraph_count=len(book),
    )


def _build_paragraphs(pages: list[tuple[int, list[tuple[float, float, str]]]]) -> tuple[list[Paragraph], list[int]]:
    """Turn page blocks into paragraphs; also return the last page each paragraph reaches."""
    # Running headers/footers: texts in the margin zones repeated on many pages.
    margin_counts: Counter[str] = Counter()
    for _, blocks in pages:
        seen = {_signature(t) for y0, y1, t in blocks if y1 <= _MARGIN or y0 >= 1 - _MARGIN}
        margin_counts.update(seen)
    threshold = max(3, int(len(pages) * 0.3))
    repeated = {sig for sig, count in margin_counts.items() if count >= threshold}

    paragraphs: list[Paragraph] = []
    last_pages: list[int] = []
    for number, blocks in pages:
        first_kept = True
        for y0, y1, raw in blocks:
            in_margin = y1 <= _MARGIN or y0 >= 1 - _MARGIN
            if in_margin and (_signature(raw) in repeated or _PAGE_NUMBER.match(raw)):
                continue
            text = normalize_text(raw)
            if not is_readable(text):
                continue
            # The first kept block of a page may continue the last paragraph of the previous page.
            is_first, first_kept = first_kept, False
            if (is_first and paragraphs and paragraphs[-1].page == number - 1
                    and _should_join(paragraphs[-1].text, text)):
                prev = paragraphs[-1]
                joined = re.sub(r"(\w)-$", r"\1", prev.text)
                sep = "" if joined != prev.text else " "
                paragraphs[-1] = Paragraph(joined + sep + text, prev.section, prev.page)
                last_pages[-1] = number
                continue
            paragraphs.append(Paragraph(text, 0, number))
            last_pages.append(number)
    return paragraphs, last_pages


def _sections_from_toc(toc: list, paragraphs: list[Paragraph]) -> list[Section]:
    """Turn the PDF outline (top two levels) into sections starting at the first
    paragraph of the referenced page."""
    first_on_page: dict[int, int] = {}
    for i, para in enumerate(paragraphs):
        first_on_page.setdefault(para.page or 0, i)
    sections: list[Section] = []
    for level, title, page in toc:
        if level > 2 or page < 1:
            continue
        candidates = [idx for pg, idx in first_on_page.items() if pg >= page]
        if not candidates:
            continue
        start = min(candidates)
        if sections and sections[-1].start == start:
            continue
        sections.append(Section(normalize_text(title)[:200] or f"Сторінка {page}", start))
    if sections and sections[0].start > 0:
        sections.insert(0, Section("Початок", 0))
    return sections
