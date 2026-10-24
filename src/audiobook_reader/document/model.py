"""Document data model shared by all format loaders."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class DocumentError(Exception):
    """A document could not be opened or contains no readable text."""


class ScannedPdfError(DocumentError):
    """The PDF consists of images without an extractable text layer."""

    def __init__(self, message: str, pages: int = 0):
        super().__init__(message)
        self.pages = pages


@dataclass(frozen=True)
class Paragraph:
    text: str
    section: int = 0
    page: int | None = None  # 1-based page number for PDFs


@dataclass(frozen=True)
class Section:
    title: str
    start: int  # index of the first paragraph of this section


@dataclass
class Document:
    path: Path
    title: str
    format: str
    paragraphs: list[Paragraph]
    sections: list[Section] = field(default_factory=list)
    page_count: int | None = None
    page_range: tuple[int, int] | None = None
    language: str | None = None
    scan_pages: list[int] = field(default_factory=list)  # image-only pages left unrecognized
    ocr_pages: int = 0  # pages whose text came from OCR

    def __post_init__(self) -> None:
        if not self.sections:
            self.sections = [Section(self.title, 0)]

    def section_of(self, paragraph_index: int) -> int:
        if not self.paragraphs:
            return 0
        return self.paragraphs[min(paragraph_index, len(self.paragraphs) - 1)].section

    def char_count(self) -> int:
        return sum(len(p.text) for p in self.paragraphs)
