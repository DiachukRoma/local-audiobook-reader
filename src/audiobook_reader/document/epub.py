"""EPUB loader: follows the spine order and skips navigation documents."""

from __future__ import annotations

import posixpath
import warnings
from pathlib import Path

from .model import Document, DocumentError, Paragraph, Section
from .normalize import is_readable, normalize_text

_BLOCK_TAGS = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "dt", "dd", "td"]
_HEADINGS = {"h1", "h2", "h3"}
_SKIP_TAGS = ["script", "style", "nav", "head", "svg", "math", "sup"]


def _toc_titles(book) -> dict[str, str]:
    """Map document href -> title from the EPUB table of contents."""
    titles: dict[str, str] = {}

    def walk(entries):
        for entry in entries:
            if isinstance(entry, tuple):
                section, children = entry
                href = getattr(section, "href", "") or ""
                if href:
                    titles.setdefault(href.split("#")[0], section.title)
                walk(children)
            else:
                href = getattr(entry, "href", "") or ""
                if href:
                    titles.setdefault(href.split("#")[0], entry.title)

    walk(book.toc or [])
    return titles


def _extract_blocks(html: bytes) -> list[tuple[str, str]]:
    """Return (tag, text) for the leaf block elements of an XHTML document, in order."""
    from bs4 import BeautifulSoup
    from bs4 import XMLParsedAsHTMLWarning

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html, "lxml")
    body = soup.body or soup
    for tag in body.find_all(_SKIP_TAGS):
        tag.decompose()
    for tag in body.find_all(attrs={"epub:type": ["footnote", "noteref", "pagebreak", "toc"]}):
        tag.decompose()
    for br in body.find_all("br"):
        br.replace_with("\n")

    blocks: list[tuple[str, str]] = []
    found = body.find_all(_BLOCK_TAGS)
    leafs = [el for el in found if not el.find(_BLOCK_TAGS)]
    if leafs:
        for el in leafs:
            text = normalize_text(el.get_text(" "))
            if text:
                blocks.append((el.name, text))
    else:
        # Some books use only <div>s: fall back to text lines.
        for line in body.get_text("\n").split("\n"):
            text = normalize_text(line)
            if text:
                blocks.append(("p", text))
    return blocks


def load_epub(path: Path) -> Document:
    import ebooklib
    from ebooklib import epub

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            book = epub.read_epub(str(path), options={"ignore_ncx": False})
    except Exception as exc:
        raise DocumentError(f"Не вдалося відкрити EPUB: {exc}") from exc

    toc = _toc_titles(book)
    title_meta = book.get_metadata("DC", "title")
    title = (title_meta[0][0] if title_meta else "").strip() or path.stem

    paragraphs: list[Paragraph] = []
    sections: list[Section] = []
    for idref, _linear in book.spine:
        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        if isinstance(item, epub.EpubNav) or "nav" in (getattr(item, "properties", None) or []):
            continue
        blocks = [(tag, text) for tag, text in _extract_blocks(item.get_content()) if is_readable(text)]
        if not blocks:
            continue
        href = posixpath.normpath(item.get_name())
        section_title = toc.get(item.get_name()) or toc.get(href)
        if not section_title:
            section_title = next((text for tag, text in blocks if tag in _HEADINGS), None)
        if not section_title:
            section_title = f"Частина {len(sections) + 1}"
        sections.append(Section(section_title[:200], len(paragraphs)))
        section_index = len(sections) - 1
        paragraphs.extend(Paragraph(text, section=section_index) for _, text in blocks)

    if not paragraphs:
        raise DocumentError("EPUB не містить тексту для читання.")
    return Document(path=path, title=title, format="epub", paragraphs=paragraphs, sections=sections)
