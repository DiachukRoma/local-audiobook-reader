from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

UK_PARAGRAPHS = [
    "Розділ перший",
    "Тиха ранкова година. Сонце підіймалося над рікою, і птахи співали — «Доброго ранку!»",
    "Марія відкрила вікно; повітря пахло м'ятою та ґрунтом. Чи прийде сьогодні їжак?",
]
RU_PARAGRAPHS = [
    "Глава первая",
    "Тихий утренний час. Солнце поднималось над рекой, и птицы пели — «Доброе утро!»",
    "Мария открыла окно; воздух пах мятой и землёй. Придёт ли сегодня ёжик?",
]

# A system font with Cyrillic glyphs, used only to build PDF fixtures.
CYRILLIC_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/times.ttf",
]


def cyrillic_font() -> str:
    for font in CYRILLIC_FONTS:
        if Path(font).is_file():
            return font
    pytest.skip("No Cyrillic system font available for building PDF fixtures")


def make_pdf(path: Path, pages: list[list[str]], header: str | None = None, footer_numbers: bool = False,
             toc: list | None = None) -> Path:
    import pymupdf

    font = cyrillic_font()
    doc = pymupdf.open()
    for number, paragraphs in enumerate(pages, start=1):
        page = doc.new_page(width=595, height=842)
        page.insert_font(fontname="cyr", fontfile=font)
        if header:
            page.insert_text((72, 40), header, fontname="cyr", fontsize=9)
        y = 120
        for para in paragraphs:
            rect = pymupdf.Rect(72, y, 523, y + 160)
            page.insert_textbox(rect, para, fontname="cyr", fontsize=12)
            y += 170
        if footer_numbers:
            page.insert_text((290, 815), str(number), fontname="cyr", fontsize=9)
    if toc:
        doc.set_toc(toc)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def uk_paragraphs():
    return list(UK_PARAGRAPHS)


@pytest.fixture
def ru_paragraphs():
    return list(RU_PARAGRAPHS)


def make_scanned_pdf(source: Path, target: Path, dpi: int = 200, keep_text_pages: tuple[int, ...] = ()) -> Path:
    """Rasterize pages of ``source`` into an image-only PDF (simulates a scanned book).
    Pages listed in ``keep_text_pages`` (1-based) keep their text layer."""
    import pymupdf

    src = pymupdf.open(str(source))
    out = pymupdf.open()
    for number, page in enumerate(src, start=1):
        if number in keep_text_pages:
            out.insert_pdf(src, from_page=number - 1, to_page=number - 1)
            continue
        pix = page.get_pixmap(dpi=dpi)
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, pixmap=pix)
    out.save(str(target))
    return target
