"""Dialog that asks whether (and in which language) to recognize the text of a PDF.

A custom QDialog rather than QMessageBox: on recent macOS QMessageBox is shown as a native
alert, which drops any widgets added to it (the language selector) and shows the Python icon.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from ..storage.settings import RESOURCE_ROOT

LANGUAGES = (("uk", "Українська"), ("ru", "Русский"))
LANGUAGE_NAMES = dict(LANGUAGES)


def _muted(label: QLabel) -> QLabel:
    palette = label.palette()
    color = palette.color(palette.ColorRole.WindowText)
    color.setAlpha(150)
    palette.setColor(palette.ColorRole.WindowText, color)
    label.setPalette(palette)
    return label


def _plural_pages(n: int) -> str:
    return f"{n} стор."


class OcrDialog(QDialog):
    """``scan_pages``: pages without a text layer; ``recognized``: (pages, language) when the document
    is already recognized; ``can_all``: offer recognizing every page. After ``exec()``:
    ``mode`` is "scans", "all" or None (cancelled) and ``language`` is "uk" or "ru"."""

    def __init__(self, scan_pages: int, language: str, note: str, page_time: str,
                 recognized: tuple[int, str | None] | None = None, recognized_mode: str | None = None,
                 can_all: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Розпізнавання тексту")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.mode: str | None = None

        # Title and explanation, depending on the state of the document.
        if recognized:
            pages, old_language = recognized
            title = "Розпізнати текст заново?"
            old = f", мова: {LANGUAGE_NAMES[old_language]}" if old_language in LANGUAGE_NAMES else ""
            text = (f"Документ уже розпізнано ({_plural_pages(pages)}{old}). Якщо мову вибрано неправильно, "
                    f"виберіть правильну — сторінки буде розпізнано заново.")
        elif scan_pages and not can_all:
            title = "Розпізнати текст у скані?"
            text = f"Цей PDF — скан без текстового шару ({_plural_pages(scan_pages)})."
        elif scan_pages:
            title = "Розпізнати текст у цьому PDF?"
            text = (f"Сторінок без текстового шару: {scan_pages}. Можна розпізнати лише їх або всі сторінки "
                    "(якщо вбудований текст пошкоджений).")
        else:
            title = "Розпізнати всі сторінки?"
            text = ("У цьому PDF є текстовий шар. Розпізнавання всіх сторінок допоможе, якщо вбудований "
                    "текст пошкоджений або читається з помилками.")

        logo = QLabel()
        pixmap = QPixmap(str(RESOURCE_ROOT / "assets" / "icon.png"))
        if not pixmap.isNull():
            ratio = self.devicePixelRatioF()
            pixmap = pixmap.scaled(int(64 * ratio), int(64 * ratio), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pixmap.setDevicePixelRatio(ratio)
            logo.setPixmap(pixmap)
        logo.setAlignment(Qt.AlignTop)

        title_label = QLabel(title)
        font = title_label.font()
        font.setPointSizeF(font.pointSizeF() + 3)
        font.setBold(True)
        title_label.setFont(font)
        title_label.setWordWrap(True)
        text_label = QLabel(text)
        text_label.setWordWrap(True)

        self.language_combo = QComboBox()
        for code, name in LANGUAGES:
            self.language_combo.addItem(name, code)
        self.language_combo.setCurrentIndex(max(self.language_combo.findData(language), 0))
        language_row = QHBoxLayout()
        language_row.addWidget(QLabel("Мова тексту:"))
        language_row.addWidget(self.language_combo)
        language_row.addStretch(1)

        note_label = _muted(QLabel(f"{note} Орієнтовно {page_time} на сторінку."))
        note_label.setWordWrap(True)
        small = note_label.font()
        small.setPointSizeF(small.pointSizeF() - 1)
        note_label.setFont(small)

        content = QVBoxLayout()
        content.setSpacing(10)
        content.addWidget(title_label)
        content.addWidget(text_label)
        content.addSpacing(2)
        content.addLayout(language_row)
        content.addWidget(note_label)

        top = QHBoxLayout()
        top.setSpacing(16)
        top.addWidget(logo, 0, Qt.AlignTop)
        top.addLayout(content, 1)

        # Buttons: Cancel on the left, the main action (default) on the right.
        buttons = QHBoxLayout()
        cancel = QPushButton("Скасувати")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        actions: list[tuple[str, str]] = []
        if recognized:
            actions.append(("Розпізнати заново", recognized_mode or "scans"))
        else:
            if scan_pages:
                actions.append(("Лише сторінки без тексту" if can_all else "Розпізнати", "scans"))
            if can_all:
                actions.append(("Усі сторінки", "all"))
        # The first action is the main one: it goes rightmost and is the default (Enter).
        self.action_buttons: dict[str, QPushButton] = {}
        for index, (label, mode) in reversed(list(enumerate(actions))):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, m=mode: self._choose(m))
            button.setAutoDefault(index == 0)
            button.setDefault(index == 0)
            buttons.addWidget(button)
            self.action_buttons[mode] = button
        cancel.setAutoDefault(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 16)
        layout.setSpacing(18)
        layout.addLayout(top)
        layout.addLayout(buttons)

    @property
    def language(self) -> str:
        return self.language_combo.currentData()

    def _choose(self, mode: str) -> None:
        self.mode = mode
        self.accept()
