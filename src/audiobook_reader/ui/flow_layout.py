"""A layout that places items in a row and wraps them onto the next line when the row is too narrow."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, h_spacing: int = 16, v_spacing: int = 8):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(0, 0, 0, 0)

    # QLayout API --------------------------------------------------------------
    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 (Qt API)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 (Qt API)
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 (Qt API)
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802 (Qt API)
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt API)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt API)
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 (Qt API)
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 (Qt API)
        """As narrow as the widest single item: everything else can wrap."""
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    # ------------------------------------------------------------------------
    def _do_layout(self, rect: QRect, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        lines: list[list[tuple[QLayoutItem, QSize]]] = [[]]
        x = 0
        for item in self._items:
            hint = item.sizeHint()
            if item.isEmpty():  # hidden
                continue
            if lines[-1] and x + hint.width() > area.width():
                lines.append([])
                x = 0
            lines[-1].append((item, hint))
            x += hint.width() + self._h_spacing

        y = area.y()
        for line in lines:
            if not line:
                continue
            height = max(hint.height() for _item, hint in line)
            if apply:
                x = area.x()
                for item, hint in line:
                    width = min(hint.width(), area.width())
                    # Items of one line are centred vertically on it.
                    item.setGeometry(QRect(QPoint(x, y + (height - hint.height()) // 2), QSize(width, hint.height())))
                    x += hint.width() + self._h_spacing
            y += height + self._v_spacing
        return max(y - self._v_spacing - area.y(), 0) + margins.top() + margins.bottom()
