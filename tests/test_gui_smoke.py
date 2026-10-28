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

    # Next start: the last book reopens by itself, at the saved position.
    restarted = MainWindow(data)
    restarted.restore_last_document()
    assert _wait(app, lambda: restarted.document is not None)
    assert restarted.document.path == book
    assert restarted.controller.position == (2, 0)
    restarted.close()


def test_no_last_document_to_restore(app, tmp_path):
    from audiobook_reader.storage.settings import Settings
    from audiobook_reader.ui.main_window import MainWindow

    data = tmp_path / "data"
    data.mkdir()
    Settings(cache_dir=str(tmp_path / "cache"), recent_files=[str(tmp_path / "deleted.txt")]).save(data / "settings.json")
    window = MainWindow(data)
    window.restore_last_document()  # the file is gone: nothing happens, no error dialog
    assert window.document is None and not window._loading
    window.close()


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
        pytest.skip("OCR engine not available")
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



def test_background_task_kept_alive_until_result_delivered(app):
    """A finished task must stay referenced until its queued result reaches the GUI thread;
    otherwise the garbage collector can delete it and the result is silently lost."""
    import threading

    from audiobook_reader.ui import tasks

    done = threading.Event()
    received = []

    def work():
        done.set()
        return 42

    task = tasks.BackgroundTask(work)
    task.succeeded.connect(received.append)
    task.start()
    assert done.wait(5)
    time.sleep(0.2)  # the worker has emitted by now; the GUI thread has not processed events yet
    assert task in tasks._running and received == []
    assert _wait(app, lambda: received == [42])
    assert task not in tasks._running


def test_paragraph_list_follows_the_paragraph_being_read(app):
    """The highlighted paragraph stays on screen in a long book, also right after opening it.
    A highlight change must not re-run the batched layout (that used to make the list jump)."""
    from types import SimpleNamespace

    from audiobook_reader.ui.paragraph_view import ParagraphView

    words = [5, 40, 120, 15, 80]
    paragraphs = [SimpleNamespace(text=" ".join(["слово"] * words[i % 5]), page=1) for i in range(3000)]
    doc = SimpleNamespace(paragraphs=paragraphs, sections=[], paragraph_number=lambda row: row + 1)
    view = ParagraphView()
    view.resize(800, 500)
    view.show()

    def on_screen(row):
        return view.viewport().rect().intersects(view.visualRect(view.model_.index(row)))

    view.model_.set_document(doc)
    view.highlight(2000)  # restored reading position, layout not finished yet
    assert _wait(app, lambda: on_screen(2000))
    for row in range(2001, 2010):
        view.highlight(row)
        app.processEvents()
        assert on_screen(row), row


def test_current_paragraph_font_size_setting(app, tmp_path, monkeypatch, uk_paragraphs):
    """The font size chosen in Settings applies to the bottom pane at once and is remembered."""
    from audiobook_reader.storage.settings import Settings
    from audiobook_reader.ui import main_window as mw

    data = tmp_path / "data"
    data.mkdir()
    Settings(cache_dir=str(tmp_path / "cache")).save(data / "settings.json")
    book = tmp_path / "книга.txt"
    book.write_text("\n\n".join(uk_paragraphs), encoding="utf-8")
    window = mw.MainWindow(data)
    window.open_path(book)
    assert _wait(app, lambda: window.document is not None and window.current_text.toPlainText())
    assert "font-size:15px" in window.current_text.toHtml().replace(" ", "")

    def accept_with_bigger_font(dialog):
        dialog.font_size.setValue(26)
        return mw.SettingsDialog.Accepted

    monkeypatch.setattr(mw.SettingsDialog, "exec", accept_with_bigger_font)
    window._open_settings()
    assert "font-size:26px" in window.current_text.toHtml().replace(" ", "")
    assert Settings.load(data / "settings.json").current_text_font_size == 26
    window.close()
