"""Local OCR for scanned PDF pages using Apple's Vision framework (built into macOS).

Pages are rendered with PyMuPDF and recognized on-device by ``VNRecognizeTextRequest``;
nothing leaves the computer. Results are cached per document so a scanned book is
recognized only once.
"""

from __future__ import annotations

import json
import logging
import os
import re
import statistics
import sys
import threading
from pathlib import Path

log = logging.getLogger(__name__)

OCR_DPI = 300
LANGUAGE_CODES = {"uk": "uk-UA", "ru": "ru-RU"}

# Latin letters that look like Cyrillic ones; OCR sometimes mixes them into Cyrillic words.
_HOMOGLYPHS = str.maketrans({
    "a": "а", "c": "с", "e": "е", "i": "і", "o": "о", "p": "р", "x": "х", "y": "у",
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "I": "І", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х",
})
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_FOREIGN_IN_CYRILLIC = re.compile(r"[Ā-ɏḀ-ỿ̀-ͯ]")
_WORD = re.compile(r"\S+")


class OcrUnavailableError(Exception):
    """Apple Vision text recognition is not available on this system."""


class OcrCancelled(Exception):
    pass


def clean_ocr_text(text: str) -> str:
    """Fix typical OCR artefacts in Cyrillic text without touching genuine Latin words."""
    def fix(match: re.Match) -> str:
        word = match.group(0)
        if not _CYRILLIC.search(word):
            return word
        word = _FOREIGN_IN_CYRILLIC.sub("", word)
        letters = [ch for ch in word if ch.isalpha()]
        cyrillic = sum(1 for ch in letters if _CYRILLIC.match(ch))
        if letters and cyrillic / len(letters) >= 0.5:
            word = word.translate(_HOMOGLYPHS)
        return word

    return _WORD.sub(fix, text).strip()


def is_available() -> bool:
    if sys.platform != "darwin":
        return False
    import importlib.util
    return importlib.util.find_spec("Vision") is not None  # pyobjc-framework-Vision


def group_lines(lines: list[tuple[float, float, float, float, str]]) -> list[tuple[float, float, str]]:
    """Group OCR lines (top, bottom, left, right, text — normalized, top-left origin)
    into paragraphs: (top, bottom, text with line breaks)."""
    if not lines:
        return []
    heights = [b - t for t, b, _l, _r, _ in lines if b > t]
    line_h = statistics.median(heights) if heights else 0.015
    lefts = [left for _t, _b, left, _r, _ in lines]
    margin = statistics.median(lefts)
    rights = sorted(r for *_x, r, _ in lines)
    full_right = rights[int(len(rights) * 0.8)] if rights else 1.0

    paragraphs: list[list] = []
    prev = None
    for top, bottom, left, right, text in lines:
        new = prev is None
        if prev is not None:
            p_top, p_bottom, p_left, p_right, p_text = prev
            gap = top - p_bottom
            indented = left - margin > 0.02 and abs(p_left - margin) < 0.015
            short_prev = p_right < full_right - 0.08 and p_text.rstrip().endswith((".", "!", "?", "…", "»", ":", '"'))
            new = gap > 0.9 * line_h or gap < -0.5 * line_h or indented or short_prev
        if new:
            paragraphs.append([top, bottom, [text]])
        else:
            paragraphs[-1][1] = bottom
            paragraphs[-1][2].append(text)
        prev = (top, bottom, left, right, text)
    return [(top, bottom, "\n".join(texts)) for top, bottom, texts in paragraphs]


class VisionOcr:
    """Recognizes PDF pages; results are cached in ``cache_dir/<fingerprint>.json``."""

    def __init__(self, languages: tuple[str, ...] = ("uk", "ru"), cache_dir: Path | None = None,
                 fingerprint: str | None = None):
        if not is_available():
            raise OcrUnavailableError(
                "Розпізнавання тексту Apple Vision недоступне (потрібні macOS 13+ і пакет pyobjc-framework-Vision).")
        self.languages = [LANGUAGE_CODES[lang] for lang in languages if lang in LANGUAGE_CODES] or ["uk-UA", "ru-RU"]
        self._cache_path = (Path(cache_dir) / f"{fingerprint}.json") if cache_dir and fingerprint else None
        self._lock = threading.Lock()
        self._cache = self._load_cache()
        self._dirty = 0

    # ------------------------------------------------------------- cache
    def _cache_tag(self) -> str:
        return f"vision-{OCR_DPI}-{','.join(self.languages)}"

    def _load_cache(self) -> dict:
        if self._cache_path is None:
            return {}
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict) or data.get("tag") != self._cache_tag():
            return {}
        return data.get("pages", {})

    def flush(self) -> None:
        if self._cache_path is None or not self._dirty:
            return
        with self._lock:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_name(self._cache_path.name + ".tmp")
            tmp.write_text(json.dumps({"tag": self._cache_tag(), "pages": self._cache}, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, self._cache_path)
            self._dirty = 0

    def cached(self, page_number: int) -> bool:
        return str(page_number) in self._cache

    # ------------------------------------------------------------- OCR
    def recognize_page(self, page) -> list[tuple[float, float, str]]:
        """Return paragraph blocks (top, bottom, text) for a PyMuPDF page."""
        key = str(page.number + 1)
        if key in self._cache:
            return [tuple(block) for block in self._cache[key]]
        png = page.get_pixmap(dpi=OCR_DPI).tobytes("png")
        lines = self._recognize_png(png)
        blocks = group_lines(lines)
        self._cache[key] = [list(b) for b in blocks]
        self._dirty += 1
        if self._dirty >= 10:
            self.flush()
        return blocks

    def _recognize_png(self, png: bytes) -> list[tuple[float, float, float, float, str]]:
        import Foundation
        import objc
        import Vision

        with objc.autorelease_pool():
            data = Foundation.NSData.dataWithBytes_length_(png, len(png))
            handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
            request = Vision.VNRecognizeTextRequest.alloc().init()
            request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
            request.setRecognitionLanguages_(self.languages)
            request.setUsesLanguageCorrection_(True)
            ok, error = handler.performRequests_error_([request], None)
            if not ok:
                raise RuntimeError(f"Помилка розпізнавання Vision: {error}")
            lines = []
            for observation in request.results() or []:
                candidates = observation.topCandidates_(1)
                if not candidates:
                    continue
                text = clean_ocr_text(str(candidates[0].string()))
                if not text:
                    continue
                box = observation.boundingBox()  # normalized, origin bottom-left
                top = 1.0 - box.origin.y - box.size.height
                bottom = 1.0 - box.origin.y
                lines.append((top, bottom, box.origin.x, box.origin.x + box.size.width, text))
        return lines
