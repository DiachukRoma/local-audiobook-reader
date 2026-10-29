import os

import pytest

from audiobook_reader.ui.search_bar import find_paragraphs, normalize_for_search

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_search_ignores_case_apostrophes_and_line_breaks():
    texts = [normalize_for_search(t) for t in ["Сім’я пішла\nдодому.", "Інший абзац.", "СІМ'Я ПІШЛА далі."]]
    assert find_paragraphs(texts, "сімʼя пішла") == [0, 2]
    assert find_paragraphs(texts, "абзац") == [1]
    assert find_paragraphs(texts, "   ") == []
    assert find_paragraphs(texts, "немає") == []


def test_search_bar_in_window(tmp_path, uk_paragraphs):
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtTest import QTest

    from audiobook_reader.storage.settings import Settings
    from audiobook_reader.ui.main_window import MainWindow
    from test_gui_smoke import _wait

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    data = tmp_path / "data"
    data.mkdir()
    Settings(cache_dir=str(tmp_path / "cache")).save(data / "settings.json")
    paragraphs = [f"Абзац номер {i}." + (" Тут є ключ." if i in (3, 7, 12) else "") for i in range(20)]
    book = tmp_path / "book.txt"
    book.write_text("\n\n".join(paragraphs), encoding="utf-8")

    window = MainWindow(data)
    window.show()
    window.open_path(book)
    assert _wait(app, lambda: window.document is not None)
    window.controller.seek(5)

    bar = window.search_bar
    assert not bar.isVisible()
    QTest.keyClick(window, Qt.Key_F, Qt.ControlModifier)
    assert bar.isVisible()
    # QTest.keyClicks crashes on Cyrillic in PySide6: send key events carrying the text instead.
    for ch in "тут є КЛЮЧ":
        QtWidgets.QApplication.sendEvent(bar.edit, QKeyEvent(QEvent.KeyPress, Qt.Key_unknown, Qt.NoModifier, ch))
    assert bar.edit.text() == "тут є КЛЮЧ"
    QTest.keyClick(bar.edit, Qt.Key_Space)  # a space goes into the field, not to play/pause
    assert window.controller.status == "stopped"
    assert _wait(app, lambda: bar.matches == [3, 7, 12])
    # The first match after the paragraph being read is shown first.
    assert window.paragraph_view.currentIndex().row() == 7
    assert bar.counter.text() == "2 з 3"
    QTest.keyClick(bar.edit, Qt.Key_Return)
    assert window.paragraph_view.currentIndex().row() == 12
    QTest.keyClick(bar.edit, Qt.Key_Return)
    assert window.paragraph_view.currentIndex().row() == 3  # wraps around
    QTest.keyClick(bar.edit, Qt.Key_Return, Qt.ShiftModifier)
    assert window.paragraph_view.currentIndex().row() == 12

    bar.edit.setText("відсутнє слово")
    assert _wait(app, lambda: bar.counter.text() == "Не знайдено")
    QTest.keyClick(bar.edit, Qt.Key_Escape)
    assert not bar.isVisible()
    # Let the background model load finish before the window goes away.
    _wait(app, lambda: window.engine is not None or window.banner.isVisible(), timeout=60)
    window.close()
