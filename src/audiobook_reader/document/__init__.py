"""Document import: detect the format and return a normalized Document."""

from __future__ import annotations

from pathlib import Path

from .language import detect_language
from .model import Document, DocumentError, Paragraph, ScannedPdfError, Section

SUPPORTED_EXTENSIONS = {".pdf": "pdf", ".epub": "epub", ".txt": "txt", ".text": "txt", ".docx": "docx"}

__all__ = ["Document", "DocumentError", "Paragraph", "ScannedPdfError", "Section",
           "SUPPORTED_EXTENSIONS", "load_document"]


def load_document(path: str | Path, page_range: tuple[int, int] | None = None, ocr=None, ocr_all: bool = False,
                  progress=None, cancel=None) -> Document:
    """Open a document. ``ocr``/``ocr_all``/``progress``/``cancel`` apply to PDFs only (see load_pdf)."""
    path = Path(path)
    if not path.is_file():
        raise DocumentError(f"Файл не знайдено: {path}")
    kind = SUPPORTED_EXTENSIONS.get(path.suffix.lower())
    if kind is None:
        raise DocumentError(f"Непідтримуваний формат «{path.suffix}». Підтримуються: PDF, EPUB, TXT, DOCX.")
    if path.stat().st_size == 0:
        raise DocumentError("Файл порожній.")

    if kind == "pdf":
        from .pdf import load_pdf
        doc = load_pdf(path, page_range, ocr=ocr, ocr_all=ocr_all, progress=progress, cancel=cancel)
    elif kind == "epub":
        from .epub import load_epub
        doc = load_epub(path)
    elif kind == "docx":
        from .text_formats import load_docx
        doc = load_docx(path)
    else:
        from .text_formats import load_txt
        doc = load_txt(path)

    doc.language = detect_language(p.text for p in doc.paragraphs)
    return doc
