"""Scrollable list of paragraphs with the paragraph being read highlighted."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QAbstractItemView, QListView

from ..document import Document


class ParagraphModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc: Document | None = None
        self._current = -1
        self._heading_rows: set[int] = set()
        self.highlight = QColor(0, 120, 255, 70)

    def set_document(self, doc: Document | None) -> None:
        self.beginResetModel()
        self._doc = doc
        self._current = -1
        self._heading_rows = {s.start for s in doc.sections} if doc else set()
        self.endResetModel()

    def set_current(self, row: int) -> None:
        old, self._current = self._current, row
        for r in (old, row):
            if 0 <= r < self.rowCount():
                idx = self.index(r)
                self.dataChanged.emit(idx, idx, [Qt.BackgroundRole])

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
        if role == Qt.FontRole and row in self._heading_rows:
            font = QFont()
            font.setPointSizeF(font.pointSizeF() + 1)
            font.setBold(True)
            return font
        if role == Qt.ToolTipRole:
            page = self._doc.paragraphs[row].page
            return f"Абзац {row + 1}" + (f", сторінка {page}" if page else "") + " — подвійне клацання, щоб читати звідси"
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

    def highlight(self, row: int, follow: bool = True) -> None:
        self.model_.set_current(row)
        if follow and 0 <= row < self.model_.rowCount():
            self.scrollTo(self.model_.index(row), QAbstractItemView.PositionAtCenter)

