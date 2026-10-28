"""Scrollable list of paragraphs with the paragraph being read highlighted."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QAbstractItemView, QListView

from ..document import Document


class ParagraphModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc: Document | None = None
        self._current = -1
        self.highlight = QColor(0, 120, 255, 70)

    def set_document(self, doc: Document | None) -> None:
        self.beginResetModel()
        self._doc = doc
        self._current = -1
        self.endResetModel()

    def set_current(self, row: int) -> int:
        """Change the highlighted row and return the previous one. No dataChanged: with word-wrapped rows
        QListView would re-run its whole (batched) layout, which loses the scroll position; the view
        repaints the two rows itself."""
        old, self._current = self._current, row
        return old

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 (Qt API)
        return 0 if parent.isValid() or self._doc is None else len(self._doc.paragraphs)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self._doc is None:
            return None
        row = index.row()
        if role == Qt.DisplayRole:
            return self._doc.paragraphs[row].text
        if role == Qt.BackgroundRole and row == self._current:
            return self.highlight
        if role == Qt.ToolTipRole:
            page = self._doc.paragraphs[row].page
            return f"Абзац {self._doc.paragraph_number(row)}" + (f", сторінка {page}" if page else "") + " — подвійне клацання, щоб читати звідси"
        return None


class ParagraphView(QListView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setUniformItemSizes(False)
        self.setLayoutMode(QListView.Batched)
        self.setBatchSize(150)
        self.setSpacing(5)
        # Inner padding, painted in the same colour as the text area
        self.setViewportMargins(10, 10, 10, 10)
        palette = self.palette()
        palette.setColor(QPalette.Window, palette.color(QPalette.Base))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(False)
        self.model_ = ParagraphModel(self)
        color = self.palette().color(QPalette.Highlight)
        color.setAlpha(70)
        self.model_.highlight = color
        self.setModel(self.model_)
        self._follow_row: int | None = None
        self._follow_tries = 0

    def highlight(self, row: int, follow: bool = True) -> None:
        old = self.model_.set_current(row)
        for r in (old, row):
            if 0 <= r < self.model_.rowCount():
                self.viewport().update(self.visualRect(self.model_.index(r)))
        if follow and 0 <= row < self.model_.rowCount():
            self._follow_row = row
            self._follow_tries = 0
            self._scroll_to_followed()

    def _scroll_to_followed(self) -> None:
        """Center the followed row. Right after a document is loaded the batched layout may not have
        reached it yet (empty rect, or a scroll range that still ends above it), so retry until the row
        is really on screen."""
        row = self._follow_row
        if row is None or row >= self.model_.rowCount():
            return
        index = self.model_.index(row)
        if self.visualRect(index).isValid():
            self.scrollTo(index, QAbstractItemView.PositionAtCenter)
            if self.viewport().rect().intersects(self.visualRect(index)):
                self._follow_row = None
                return
        if self._follow_tries < 200:  # about 10 s
            self._follow_tries += 1
            QTimer.singleShot(50, self._scroll_to_followed)

