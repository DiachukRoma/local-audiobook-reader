"""Ctrl+F search bar for the paragraph list."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QStyle, QToolButton, QWidget

_APOSTROPHES = str.maketrans({"ʼ": "'", "’": "'", "`": "'", "‘": "'"})
_SPACES = re.compile(r"\s+")


def normalize_for_search(text: str) -> str:
    """Case, apostrophe variants and line breaks do not matter when searching."""
    return _SPACES.sub(" ", text.translate(_APOSTROPHES).casefold())


def find_paragraphs(normalized: list[str], query: str) -> list[int]:
    """Indexes of the paragraphs (already passed through normalize_for_search) that contain ``query``."""
    needle = normalize_for_search(query).strip()
    if not needle:
        return []
    return [i for i, text in enumerate(normalized) if needle in text]


class _SearchEdit(QLineEdit):
    """Enter, Shift+Enter and Ctrl+Enter as separate signals."""

    next_requested = Signal()
    previous_requested = Signal()
    activate_requested = Signal()

    def keyPressEvent(self, event):  # noqa: N802 (Qt API)
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ControlModifier:
                self.activate_requested.emit()
            elif event.modifiers() & Qt.ShiftModifier:
                self.previous_requested.emit()
            else:
                self.next_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class SearchBar(QWidget):
    """Search field with previous/next buttons and a match counter. Emits ``found(row)`` for the
    paragraph to show and ``activated(row)`` (Ctrl+Enter) to read from it."""

    found = Signal(int)
    activated = Signal(int)
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._texts: list[str] = []
        self._normalized: list[str] | None = None
        self._matches: list[int] = []
        self._index = -1
        self.start_row = lambda: 0  # where the first search starts: the selected or the paragraph being read

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.edit = _SearchEdit()
        self.edit.setPlaceholderText("Пошук у тексті…")
        self.edit.setClearButtonEnabled(True)
        self.edit.setToolTip("Enter — наступний збіг, Shift+Enter — попередній, "
                             "Ctrl+Enter — читати від знайденого абзацу, Esc — закрити")
        self.counter = QLabel()
        self.counter.setMinimumWidth(90)
        style = self.style()
        self.prev_button = QToolButton(toolTip="Попередній збіг (Shift+Enter)", autoRaise=True)
        self.prev_button.setIcon(style.standardIcon(QStyle.SP_ArrowUp))
        self.next_button = QToolButton(toolTip="Наступний збіг (Enter)", autoRaise=True)
        self.next_button.setIcon(style.standardIcon(QStyle.SP_ArrowDown))
        self.close_button = QToolButton(toolTip="Закрити (Esc)", autoRaise=True)
        self.close_button.setIcon(style.standardIcon(QStyle.SP_TitleBarCloseButton))
        for widget in (self.edit, self.counter, self.prev_button, self.next_button, self.close_button):
            layout.addWidget(widget)
        layout.setStretch(0, 1)

        self._timer = QTimer(self, singleShot=True, interval=200)
        self._timer.timeout.connect(self._search)
        self.edit.textChanged.connect(lambda _t: self._timer.start())
        self.edit.next_requested.connect(self.next)
        self.edit.previous_requested.connect(self.previous)
        self.edit.activate_requested.connect(self._activate)
        self.prev_button.clicked.connect(self.previous)
        self.next_button.clicked.connect(self.next)
        self.close_button.clicked.connect(self.close_bar)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.close_bar, context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence.FindNext, self, activated=self.next, context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence.FindPrevious, self, activated=self.previous, context=Qt.WidgetWithChildrenShortcut)
        self._update_counter()

    def set_texts(self, texts: list[str]) -> None:
        self._texts = texts
        self._normalized = None
        if self.isVisible():
            self._search()

    def open_bar(self) -> None:
        self.show()
        self.edit.setFocus(Qt.ShortcutFocusReason)
        self.edit.selectAll()

    def close_bar(self) -> None:
        self.hide()
        self.closed.emit()

    @property
    def matches(self) -> list[int]:
        return list(self._matches)

    def current_row(self) -> int | None:
        return self._matches[self._index] if 0 <= self._index < len(self._matches) else None

    def next(self) -> None:
        self._step(1)

    def previous(self) -> None:
        self._step(-1)

    # ---------------------------------------------------------------- internals
    def _activate(self) -> None:
        if self._timer.isActive():
            self._search()
        row = self.current_row()
        if row is not None:
            self.activated.emit(row)

    def _search(self) -> None:
        self._timer.stop()
        if self._normalized is None:
            self._normalized = [normalize_for_search(t) for t in self._texts]
        self._matches = find_paragraphs(self._normalized, self.edit.text())
        self._index = -1
        if self._matches:
            start = self.start_row()
            self._index = next((i for i, row in enumerate(self._matches) if row >= start), 0)
            self.found.emit(self._matches[self._index])
        self._update_counter()

    def _step(self, direction: int) -> None:
        if self._timer.isActive():  # typed but not searched yet
            self._search()
            return
        if not self._matches:
            return
        self._index = (self._index + direction) % len(self._matches)
        self.found.emit(self._matches[self._index])
        self._update_counter()

    def _update_counter(self) -> None:
        has_text = bool(self.edit.text().strip())
        if self._matches:
            self.counter.setText(f"{self._index + 1} з {len(self._matches)}")
        else:
            self.counter.setText("Не знайдено" if has_text else "")
        self.prev_button.setEnabled(len(self._matches) > 1)
        self.next_button.setEnabled(len(self._matches) > 1)
