"""Offscreen GUI smoke test: window builds, documents open in the background, position is restored."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _wait(app, predicate, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_open_document_and_restore_position(app, tmp_path, uk_paragraphs):
    from audiobook_reader.storage.settings import Settings
    from audiobook_reader.ui.main_window import MainWindow

    data = tmp_path / "data"
    data.mkdir()
    Settings(cache_dir=str(tmp_path / "cache")).save(data / "settings.json")
    book = tmp_path / "книга.txt"
    book.write_text("\n\n".join(uk_paragraphs), encoding="utf-8")

    window = MainWindow(data)
    window.open_path(book)
    assert _wait(app, lambda: window.document is not None)
    assert window.paragraph_view.model_.rowCount() == len(uk_paragraphs)
    assert window.title_label.text() == "книга"
    window.controller.seek(2)
    assert _wait(app, lambda: window.position_label.text().startswith("Абзац 3"))
    window.close()

    reopened = MainWindow(data)
    reopened.open_path(book)
    assert _wait(app, lambda: reopened.document is not None)
    assert reopened.controller.position == (2, 0)
    assert str(book) in reopened.settings.recent_files
    reopened.close()


def test_scanned_or_broken_file_does_not_crash(app, tmp_path, monkeypatch):
    from audiobook_reader.ui import main_window as mw

    shown = []
    monkeypatch.setattr(mw.QMessageBox, "critical", lambda *a, **k: shown.append(a[2]))
    data = tmp_path / "data"
    window = mw.MainWindow(data)
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 not really a pdf")
    window.open_path(broken)
    assert _wait(app, lambda: shown)
    assert window.document is None
    window.close()


def test_scanned_pdf_ocr_flow(app, tmp_path, monkeypatch, uk_paragraphs):
    from audiobook_reader.document.ocr import is_available
    from audiobook_reader.storage.settings import Settings
    from audiobook_reader.ui import main_window as mw
    from conftest import make_pdf, make_scanned_pdf

    if not is_available():
        pytest.skip("Apple Vision OCR not available")
    data = tmp_path / "data"
    data.mkdir()
    Settings(cache_dir=str(tmp_path / "cache")).save(data / "settings.json")
    scan = make_scanned_pdf(make_pdf(tmp_path / "t.pdf", [uk_paragraphs, uk_paragraphs]), tmp_path / "scan.pdf")

    offered = []
    monkeypatch.setattr(mw.MainWindow, "_offer_ocr", lambda self, path, pages, all_pages_option=False:
                        offered.append(pages))
    window = mw.MainWindow(data)
    window.open_path(scan)
    assert _wait(app, lambda: offered)
    assert offered == [2] and window.document is None

    window.open_path(scan, ocr_mode="scans")
    assert _wait(app, lambda: window.document is not None, timeout=120)
    assert window.document.ocr_pages == 2
    assert window.paragraph_view.model_.rowCount() >= 4
    assert window.ocr_action.isEnabled()
    window.controller.seek(3)
    assert _wait(app, lambda: window.position_label.text().startswith("Абзац 4"))
    window.close()

    reopened = mw.MainWindow(data)
    reopened.open_path(scan)  # OCR mode and position are remembered; text comes from the OCR cache
    assert _wait(app, lambda: reopened.document is not None)
    assert reopened.document.ocr_pages == 2 and reopened.controller.position == (3, 0)
    assert list((data / "ocr-cache").glob("*.json"))
    reopened._clear_ocr_cache()
    assert not list((data / "ocr-cache").glob("*.json"))
    reopened.close()
