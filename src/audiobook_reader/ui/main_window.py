"""Main application window."""

from __future__ import annotations

import html
import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QProgressDialog, QPushButton, QSlider,
                               QSpinBox, QSplitter, QSplitterHandle, QStatusBar, QStyle, QTextBrowser, QToolButton,
                               QVBoxLayout, QWidget)

from ..audio.cache import AudioCache
from ..document import SUPPORTED_EXTENSIONS, Document, ScannedPdfError, load_document
from ..document.ocr import OcrCancelled, VisionOcr
from ..document.ocr import is_available as ocr_available
from ..reader.controller import ReaderController, ReaderEvents, VoiceSettings
from ..reader.export import ExportCancelled, export_audio, m4a_supported
from ..storage.settings import SPEED_MAX, SPEED_MIN, Progress, ProgressStore, Settings, document_fingerprint
from ..tts.base import ModelMissingError, TTSEngine
from ..tts.supertonic_engine import APPROX_DOWNLOAD_MB, MODEL_REPO, SupertonicEngine, download_model
from .abbreviations_dialog import AbbreviationsDialog
from .paragraph_view import ParagraphView
from .settings_dialog import SettingsDialog
from .tasks import BackgroundTask, run_background

log = logging.getLogger(__name__)

APP_NAME = "Local Audiobook Reader"
AUTHOR = "Дячук Роман"
LANG_LABELS = {"uk": "Українська", "ru": "Русский"}
STATE_LABELS = {"stopped": "Зупинено", "buffering": "Генерування мовлення…", "playing": "Читання",
                "paused": "Пауза", "finished": "Книжку дочитано"}
FILE_FILTER = "Книжки (*.pdf *.epub *.txt *.docx);;PDF (*.pdf);;EPUB (*.epub);;Текст (*.txt);;Word (*.docx)"
OCR_NOTE = ("Розпізнавання тексту виконується локально вбудованим у macOS рушієм Apple Vision. "
            "Документ не залишає ваш Mac. Результат кешується, тож повторне відкриття миттєве.")

class _PaddedStatusBar(QStatusBar):
    """Status bar with side padding; Qt draws temporary messages at a fixed 6 px offset otherwise."""
    PADDING = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(self.PADDING, 4, self.PADDING, 6)

    def paintEvent(self, event):  # noqa: N802 (Qt API)
        message = self.currentMessage()
        if not message:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setPen(self.palette().windowText().color())
        rect = self.rect().adjusted(self.PADDING, 0, -self.PADDING, 0)
        painter.drawText(rect, Qt.AlignLeading | Qt.AlignVCenter | Qt.TextSingleLine, message)


class _GripHandle(QSplitterHandle):
    """Dark green divider with three dots in the middle, hinting that it can be dragged."""
    COLOR, HOVER, DOT = QColor("#1b4d2a"), QColor("#24653a"), QColor(255, 255, 255, 200)

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setAttribute(Qt.WA_Hover)

    def paintEvent(self, event):  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.HOVER if self.underMouse() else self.COLOR)
        painter.drawRoundedRect(self.rect(), 3, 3)
        painter.setBrush(self.DOT)
        center, radius, step = self.rect().center(), 2.0, 9
        for i in (-1, 0, 1):
            if self.orientation() == Qt.Vertical:
                painter.drawEllipse(QPointF(center.x() + 0.5 + i * step, center.y() + 0.5), radius, radius)
            else:
                painter.drawEllipse(QPointF(center.x() + 0.5, center.y() + 0.5 + i * step), radius, radius)


class _GripSplitter(QSplitter):
    def createHandle(self):  # noqa: N802 (Qt API)
        return _GripHandle(self.orientation(), self)


class _Bridge(QObject):
    """Turns controller callbacks (from worker/audio threads) into queued Qt signals."""
    position = Signal(int, int)
    state = Signal(str)
    error = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self, data_dir: Path):
        super().__init__()
        self.data_dir = data_dir
        self.settings_path = data_dir / "settings.json"
        self.settings = Settings.load(self.settings_path)
        self.progress_store = ProgressStore(data_dir / "progress.json")
        self.cache = AudioCache(Path(self.settings.cache_dir), self.settings.cache_max_mb * 1024 * 1024)
        self.engine: TTSEngine | None = None
        self.document: Document | None = None
        self.fingerprint: str | None = None
        self._last_saved = (-1, -1, 0.0)
        self._loading = False
        self.ocr_mode = "off"

        self.bridge = _Bridge()
        self.bridge.position.connect(self._on_position)
        self.bridge.state.connect(self._on_state)
        self.bridge.error.connect(self._on_reader_error)
        self.controller = ReaderController(self.cache, ReaderEvents(
            on_position=self.bridge.position.emit, on_state=self.bridge.state.emit, on_error=self.bridge.error.emit))
        self._apply_voice_settings()

        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(1100, 780)
        self._build_ui()
        self._build_menu()
        self._set_controls_enabled(False)
        self._load_engine()

    # ================================================================== UI
    def _build_ui(self) -> None:
        style = self.style()
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        # Header: title + open button
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        self.title_label = QLabel("Відкрийте книжку або перетягніть файл у це вікно")
        font = self.title_label.font()
        font.setPointSizeF(font.pointSizeF() + 6)
        font.setBold(True)
        self.title_label.setFont(font)
        self.title_label.setWordWrap(True)
        self.subtitle_label = QLabel("Підтримуються PDF, EPUB, TXT і DOCX · українська та російська мови")
        muted = self.subtitle_label.palette()
        dim = muted.color(muted.ColorRole.WindowText)
        dim.setAlpha(150)
        muted.setColor(muted.ColorRole.WindowText, dim)
        self.subtitle_label.setPalette(muted)
        title_box.addWidget(self.title_label)
        title_box.addWidget(self.subtitle_label)
        header.addLayout(title_box, 1)
        self.open_button = QPushButton(style.standardIcon(QStyle.SP_DialogOpenButton), "Відкрити файл…")
        self.open_button.clicked.connect(self.open_file_dialog)
        header.addWidget(self.open_button, 0, Qt.AlignTop)
        root.addLayout(header)

        # Banner for model problems
        self.banner = QFrame()
        self.banner.setFrameShape(QFrame.StyledPanel)
        self.banner.setStyleSheet("QFrame { background: rgba(255, 170, 0, 40); border-radius: 6px; }")
        banner_layout = QHBoxLayout(self.banner)
        self.banner_label = QLabel()
        self.banner_label.setWordWrap(True)
        self.banner_button = QPushButton(f"Завантажити модель (≈{APPROX_DOWNLOAD_MB} МБ)")
        self.banner_button.clicked.connect(self._download_model)
        banner_layout.addWidget(self.banner_label, 1)
        banner_layout.addWidget(self.banner_button)
        self.banner.hide()
        root.addWidget(self.banner)

        # Sections + paragraphs
        splitter = QSplitter(Qt.Horizontal)
        self.sections_list = QListWidget()
        self.sections_list.setMinimumWidth(180)
        self.sections_list.itemActivated.connect(self._section_activated)
        self.sections_list.itemClicked.connect(self._section_activated)
        self.paragraph_view = ParagraphView()
        self.paragraph_view.doubleClicked.connect(lambda idx: self._seek_and_play(idx.row()))
        splitter.addWidget(self.sections_list)
        splitter.addWidget(self.paragraph_view)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([230, 870])

        # Current paragraph display
        self.current_text = QTextBrowser()
        self.current_text.setMinimumHeight(50)
        self.current_text.document().setDocumentMargin(12)
        self.current_text.setOpenLinks(False)
        self.current_text.setPlaceholderText("Тут з'явиться абзац, який читається зараз.")

        # Draggable divider between the document and the current paragraph
        self.text_splitter = _GripSplitter(Qt.Vertical)
        self.text_splitter.setChildrenCollapsible(False)
        self.text_splitter.setHandleWidth(10)
        self.text_splitter.addWidget(splitter)
        self.text_splitter.addWidget(self.current_text)
        self.text_splitter.setStretchFactor(0, 1)
        self.text_splitter.setStretchFactor(1, 0)
        self.text_splitter.setSizes([600, self.settings.current_text_height])
        self.text_splitter.splitterMoved.connect(self._remember_text_height)
        root.addWidget(self.text_splitter, 1)

        # PDF page range
        self.pdf_row = QWidget()
        pdf_layout = QHBoxLayout(self.pdf_row)
        pdf_layout.setContentsMargins(0, 0, 0, 0)
        self.page_from = QSpinBox(minimum=1, maximum=1)
        self.page_to = QSpinBox(minimum=1, maximum=1)
        for spin in (self.page_from, self.page_to):
            spin.setMinimumSize(90, 30)
            spin.lineEdit().setTextMargins(8, 0, 4, 0)  # keep the number off the field's edges
        apply_pages = QPushButton("Застосувати діапазон")
        apply_pages.clicked.connect(self._apply_page_range)
        pdf_layout.addWidget(QLabel("Сторінки PDF: з"))
        pdf_layout.addWidget(self.page_from)
        pdf_layout.addWidget(QLabel("по"))
        pdf_layout.addWidget(self.page_to)
        pdf_layout.addWidget(apply_pages)
        pdf_layout.addStretch(1)
        self.pdf_row.hide()
        root.addWidget(self.pdf_row)

        # Progress
        progress_row = QHBoxLayout()
        self.progress_slider = QSlider(Qt.Horizontal)
        self.progress_slider.setMinimum(0)
        self.progress_slider.setMaximum(0)
        self.progress_slider.sliderReleased.connect(lambda: self._seek(self.progress_slider.value()))
        self.position_label = QLabel("—")
        self.position_label.setMinimumWidth(320)
        progress_row.addWidget(self.progress_slider, 1)
        progress_row.addWidget(self.position_label)
        root.addLayout(progress_row)

        # Transport + voice controls
        controls = QHBoxLayout()

        def tool(icon, tip, slot, text=None):
            button = QToolButton()
            button.setIcon(style.standardIcon(icon))
            button.setToolTip(tip)
            if text:
                button.setText(text)
                button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setAutoRaise(False)
            button.clicked.connect(slot)
            controls.addWidget(button)
            return button

        self.prev_button = tool(QStyle.SP_MediaSkipBackward, "Попередній абзац (⌘←)", self.controller.previous_paragraph)
        self.replay_button = tool(QStyle.SP_BrowserReload, "Повторити абзац (⌘R)", self.controller.replay_paragraph)
        self.play_button = tool(QStyle.SP_MediaPlay, "Читати / пауза (пробіл)", self.controller.toggle, "Читати")
        self.play_button.setMinimumWidth(110)
        self.stop_button = tool(QStyle.SP_MediaStop, "Зупинити", self.controller.stop)
        self.next_button = tool(QStyle.SP_MediaSkipForward, "Наступний абзац (⌘→)", self.controller.next_paragraph)
        controls.addSpacing(16)

        controls.addWidget(QLabel("Мова:"))
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("Автоматично", "auto")
        self.lang_combo.addItem("Українська", "uk")
        self.lang_combo.addItem("Русский", "ru")
        self.lang_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.lang_combo.setCurrentIndex(max(self.lang_combo.findData(self.settings.language), 0))
        self.lang_combo.currentIndexChanged.connect(self._language_changed)
        controls.addWidget(self.lang_combo)

        controls.addWidget(QLabel("Голос:"))
        self.voice_combo = QComboBox()
        self.voice_combo.setMinimumWidth(190)
        self.voice_combo.currentIndexChanged.connect(self._voice_changed)
        controls.addWidget(self.voice_combo)

        controls.addWidget(QLabel("Швидкість:"))
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(int(SPEED_MIN * 100), int(SPEED_MAX * 100))
        self.speed_slider.setSingleStep(5)
        self.speed_slider.setPageStep(10)
        self.speed_slider.setFixedWidth(170)
        self.speed_slider.setToolTip("Швидкість читання 0,7×–3×. Найчистіше звучання — до 2×; "
                                     "на 2,5–3× мовлення дуже стиснуте.")
        self.speed_slider.setValue(int(round(self.settings.speed * 100)))
        self.speed_label = QLabel()
        self.speed_label.setMinimumWidth(42)
        self.speed_slider.valueChanged.connect(lambda v: self.speed_label.setText(f"{v / 100:.2f}×"))
        self.speed_slider.sliderReleased.connect(self._speed_changed)
        self.speed_slider.valueChanged.connect(lambda _v: None if self.speed_slider.isSliderDown() else self._speed_changed())
        self.speed_label.setText(f"{self.settings.speed:.2f}×")
        controls.addWidget(self.speed_slider)
        controls.addWidget(self.speed_label)
        controls.addStretch(1)
        root.addLayout(controls)

        self.setCentralWidget(central)
        self.setStatusBar(_PaddedStatusBar())
        self.status_label = QLabel("Завантаження моделі мовлення…")
        self.statusBar().addWidget(self.status_label, 1)
        self.author_label = QLabel(f"Розробник: {AUTHOR}")
        self.author_label.setPalette(self.subtitle_label.palette())
        self.statusBar().addPermanentWidget(self.author_label)

        for keys, slot in (("Space", self.controller.toggle), ("Ctrl+Right", self.controller.next_paragraph),
                           ("Ctrl+Left", self.controller.previous_paragraph), ("Ctrl+R", self.controller.replay_paragraph),
                           ("Ctrl+.", self.controller.stop)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(lambda s=slot: s() if self.document and self.engine else None)

        self._speed_timer = QTimer(self, singleShot=True, interval=300)
        self._speed_timer.timeout.connect(self._apply_speed)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("Файл")
        open_action = QAction("Відкрити…", self, shortcut=QKeySequence.Open, triggered=self.open_file_dialog)
        file_menu.addAction(open_action)
        self.recent_menu = file_menu.addMenu("Нещодавні")
        self._refresh_recent_menu()
        file_menu.addSeparator()
        self.export_section_action = QAction("Експортувати поточний розділ в аудіо…", self,
                                             triggered=lambda: self._export(whole=False))
        self.export_book_action = QAction("Експортувати всю книжку в аудіо…", self,
                                          triggered=lambda: self._export(whole=True))
        self.ocr_action = QAction("Розпізнати текст (OCR)…", self, triggered=self.ocr_current_document)
        file_menu.addAction(self.ocr_action)
        file_menu.addSeparator()
        file_menu.addAction(self.export_section_action)
        file_menu.addAction(self.export_book_action)
        abbreviations_action = QAction("Словник скорочень…", self, triggered=self._open_abbreviations)
        file_menu.addAction(abbreviations_action)
        settings_action = QAction("Налаштування…", self, shortcut=QKeySequence.Preferences,
                                  triggered=self._open_settings)
        settings_action.setMenuRole(QAction.PreferencesRole)
        file_menu.addAction(settings_action)

        play_menu = self.menuBar().addMenu("Відтворення")
        for text, keys, slot in (("Читати / пауза", "Space", self.controller.toggle),
                                 ("Наступний абзац", "Ctrl+Right", self.controller.next_paragraph),
                                 ("Попередній абзац", "Ctrl+Left", self.controller.previous_paragraph),
                                 ("Повторити абзац", "Ctrl+R", self.controller.replay_paragraph),
                                 ("Зупинити", "Ctrl+.", self.controller.stop)):
            action = QAction(f"{text}\t{QKeySequence(keys).toString(QKeySequence.NativeText)}", self)
            action.triggered.connect(slot)
            play_menu.addAction(action)

        help_menu = self.menuBar().addMenu("Довідка")
        about = QAction("Про застосунок", self, triggered=self._about)
        about.setMenuRole(QAction.AboutRole)
        help_menu.addAction(about)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.prev_button, self.replay_button, self.play_button, self.stop_button, self.next_button,
                       self.progress_slider):
            widget.setEnabled(enabled)
        self.export_section_action.setEnabled(enabled)
        self.export_book_action.setEnabled(enabled)
        self.ocr_action.setEnabled(self.document is not None and self.document.format == "pdf")

    def _refresh_controls(self) -> None:
        self._set_controls_enabled(self.document is not None and self.engine is not None)

    # ============================================================ engine
    def _load_engine(self) -> None:
        self.status_label.setText("Завантаження моделі мовлення…")
        model_dir = Path(self.settings.model_dir)
        steps = self.settings.quality_steps
        run_background(SupertonicEngine, model_dir, steps,
                       on_success=self._engine_ready, on_error=self._engine_failed)

    def _engine_ready(self, engine: TTSEngine) -> None:
        self.engine = engine
        self.controller.set_engine(engine)
        self.banner.hide()
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        for voice in engine.voices():
            self.voice_combo.addItem(voice.label, voice.id)
        index = self.voice_combo.findData(self.settings.voice)
        self.voice_combo.setCurrentIndex(max(index, 0))
        self.voice_combo.blockSignals(False)
        self.status_label.setText("Модель Supertonic 3 готова · синтез виконується локально")
        self._refresh_controls()

    def _engine_failed(self, exc: Exception) -> None:
        self.engine = None
        self._refresh_controls()
        if isinstance(exc, ModelMissingError):
            self.banner_label.setText(
                f"Модель мовлення ще не завантажена. Її потрібно один раз завантажити з Hugging Face "
                f"({MODEL_REPO}, ≈{APPROX_DOWNLOAD_MB} МБ, ліцензія OpenRAIL-M). Після цього застосунок "
                f"працює повністю офлайн.\nТека моделі: {self.settings.model_dir}")
            self.banner_button.show()
        else:
            self.banner_label.setText(f"Не вдалося запустити модель мовлення: {exc}")
            self.banner_button.hide()
        self.banner.show()
        self.status_label.setText("Модель мовлення недоступна")

    def _download_model(self) -> None:
        answer = QMessageBox.question(
            self, "Завантаження моделі",
            f"Буде завантажено модель Supertonic 3 (≈{APPROX_DOWNLOAD_MB} МБ) з huggingface.co/{MODEL_REPO} "
            f"у теку:\n{self.settings.model_dir}\n\nПотрібне інтернет-з'єднання лише на час завантаження. Продовжити?")
        if answer != QMessageBox.Yes:
            return
        dialog = QProgressDialog("Завантаження моделі… Це може тривати кілька хвилин.", None, 0, 0, self)
        dialog.setWindowTitle("Завантаження")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setCancelButton(None)
        dialog.show()

        def done(_result):
            dialog.close()
            self._load_engine()

        def failed(exc):
            dialog.close()
            QMessageBox.critical(self, "Помилка завантаження", f"Не вдалося завантажити модель:\n{exc}")

        run_background(download_model, Path(self.settings.model_dir), on_success=done, on_error=failed)

    # =========================================================== documents
    def open_file_dialog(self) -> None:
        start = str(Path(self.settings.recent_files[0]).parent) if self.settings.recent_files else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Відкрити книжку", start, FILE_FILTER)
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path, page_range: tuple[int, int] | None = None, use_saved_range: bool = True,
                  ocr_mode: str | None = None) -> None:
        """Open a document in the background. ``ocr_mode``: None (as saved), "off", "scans" or "all"."""
        if self._loading:
            return
        self._loading = True
        self.controller.pause()
        self.status_label.setText(f"Відкриття «{path.name}»…")
        self.setCursor(Qt.BusyCursor)
        cancel = threading.Event()
        dialog: QProgressDialog | None = None

        def work():
            fingerprint = document_fingerprint(path)
            progress = self.progress_store.get(fingerprint)
            rng = page_range
            if rng is None and use_saved_range and progress and progress.page_range:
                rng = tuple(progress.page_range)
            mode = ocr_mode or (progress.ocr_mode if progress and progress.ocr_mode else "off")
            ocr = None
            if mode in ("scans", "all") and path.suffix.lower() == ".pdf":
                ocr = VisionOcr(self._ocr_languages(), self.data_dir / "ocr-cache", fingerprint)
            doc = load_document(path, rng, ocr=ocr, ocr_all=mode == "all",
                                progress=lambda done, total: task.progress.emit(done, total), cancel=cancel)
            return doc, fingerprint, progress, mode

        task = BackgroundTask(work)
        if ocr_mode in ("scans", "all"):
            dialog = QProgressDialog("Розпізнавання тексту (OCR)…\nПерший запуск рушія може тривати до півхвилини.",
                                     "Скасувати", 0, 0, self)
            dialog.setWindowTitle("Розпізнавання тексту")
            dialog.setWindowModality(Qt.WindowModal)
            dialog.setMinimumDuration(0)
            dialog.canceled.connect(cancel.set)

            def show_progress(done, total):
                dialog.setMaximum(total)
                dialog.setValue(done)
                dialog.setLabelText(f"Розпізнавання тексту (OCR): сторінка {done} з {total}")

            task.progress.connect(show_progress)
            dialog.show()

        def finished(result):
            if dialog:
                dialog.close()
            self._document_loaded(result)

        def failed(exc):
            if dialog:
                dialog.close()
            self._document_failed(path, exc)

        task.succeeded.connect(finished)
        task.failed.connect(failed)
        task.start()

    def _ocr_languages(self) -> tuple[str, ...]:
        return ("ru", "uk") if self.lang_combo.currentData() == "ru" else ("uk", "ru")

    def _offer_ocr(self, path: Path, pages: int, all_pages_option: bool = False) -> None:
        if not ocr_available():
            QMessageBox.warning(self, "Розпізнавання недоступне",
                                "Рушій розпізнавання Apple Vision недоступний у цьому середовищі. "
                                "Виконайте scripts/setup.sh, щоб установити залежності.")
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Розпізнавання тексту (OCR)")
        if all_pages_option:
            box.setText("Розпізнати текст у цьому PDF?")
            box.setInformativeText(
                f"Сторінок без текстового шару: {pages}. Можна розпізнати лише їх або всі сторінки "
                f"(корисно, якщо вбудований текст пошкоджений).\n\n{OCR_NOTE}")
            scans = box.addButton("Лише сторінки без тексту", QMessageBox.AcceptRole) if pages else None
            every = box.addButton("Усі сторінки", QMessageBox.AcceptRole)
        else:
            box.setText(f"Цей PDF — скан без текстового шару ({pages} стор.). Розпізнати текст?")
            box.setInformativeText(f"{OCR_NOTE}\n\nОрієнтовно 0,2–1 с на сторінку.")
            scans = box.addButton("Розпізнати", QMessageBox.AcceptRole)
            every = None
        box.addButton("Скасувати", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is None or clicked not in (scans, every):
            return
        mode = "all" if clicked is every else "scans"
        rng = self.document.page_range if self.document and self.document.path == path else None
        self.open_path(path, page_range=rng, use_saved_range=rng is None, ocr_mode=mode)

    def ocr_current_document(self) -> None:
        doc = self.document
        if not doc or doc.format != "pdf":
            QMessageBox.information(self, "Розпізнавання тексту", "Спершу відкрийте PDF-файл.")
            return
        self._offer_ocr(doc.path, len(doc.scan_pages), all_pages_option=True)

    def _document_failed(self, path: Path, exc: Exception) -> None:
        self._loading = False
        self.unsetCursor()
        self.status_label.setText("Не вдалося відкрити документ")
        if isinstance(exc, ScannedPdfError):
            self._offer_ocr(path, exc.pages)
        elif isinstance(exc, OcrCancelled):
            self.status_label.setText("Розпізнавання скасовано (уже розпізнані сторінки збережено в кеші)")
        else:
            QMessageBox.critical(self, "Помилка відкриття", f"Не вдалося відкрити «{path.name}»:\n{exc}")

    def _document_loaded(self, result) -> None:
        doc, fingerprint, progress, ocr_mode = result
        self._loading = False
        self.ocr_mode = ocr_mode
        self.unsetCursor()
        self.document, self.fingerprint = doc, fingerprint
        self.settings.add_recent(str(doc.path))
        self._save_settings()
        self._refresh_recent_menu()

        self.title_label.setText(doc.title)
        lang_name = LANG_LABELS.get(doc.language or "", "не визначено")
        details = [doc.format.upper(), f"{len(doc.paragraphs)} абзаців", f"мова тексту: {lang_name}"]
        if doc.page_count:
            details.append(f"{doc.page_count} стор.")
        self.subtitle_label.setText(" · ".join(details))
        self._update_auto_language_label()

        self.sections_list.clear()
        for section in doc.sections:
            item = QListWidgetItem(section.title)
            item.setData(Qt.UserRole, section.start)
            item.setToolTip(section.title)
            self.sections_list.addItem(item)
        self.sections_list.setVisible(len(doc.sections) > 1)
        self.paragraph_view.model_.set_document(doc)
        self.progress_slider.setMaximum(max(len(doc.paragraphs) - 1, 0))

        self.pdf_row.setVisible(doc.format == "pdf" and (doc.page_count or 0) > 1)
        if doc.format == "pdf" and doc.page_count:
            for spin in (self.page_from, self.page_to):
                spin.setMaximum(doc.page_count)
            first, last = doc.page_range or (1, doc.page_count)
            self.page_from.setValue(first)
            self.page_to.setValue(last)

        paragraph = segment = 0
        if progress and progress.paragraph_count == len(doc.paragraphs):
            paragraph, segment = progress.paragraph, progress.segment
            if progress.language in ("uk", "ru", "auto"):
                self.lang_combo.blockSignals(True)
                self.lang_combo.setCurrentIndex(max(self.lang_combo.findData(progress.language), 0))
                self.lang_combo.blockSignals(False)
        self._apply_voice_settings()
        self.controller.set_document(doc, paragraph, segment)
        self._last_saved = (paragraph, segment, time.time())
        resumed = f" · продовжуємо з абзацу {paragraph + 1}" if paragraph else ""
        recognized = f" · розпізнано OCR: {doc.ocr_pages} стор." if doc.ocr_pages else ""
        self.status_label.setText(f"Документ відкрито{recognized}{resumed}")
        self._refresh_controls()
        self._save_progress(force=True)
        if doc.scan_pages:
            self.statusBar().showMessage(
                f"Сторінок без тексту (скан): {len(doc.scan_pages)}. Щоб їх прочитати: "
                f"Файл → Розпізнати текст (OCR)…", 15000)
        if doc.language is None:
            self.status_label.setText("Увага: у тексті майже немає кирилиці. Синтез розрахований на українську та російську.")

    def _apply_page_range(self) -> None:
        if not self.document:
            return
        first, last = self.page_from.value(), self.page_to.value()
        if first > last:
            QMessageBox.warning(self, "Діапазон сторінок", "Початкова сторінка більша за кінцеву.")
            return
        rng = None if (first, last) == (1, self.document.page_count) else (first, last)
        self._save_progress(force=True)
        if self.fingerprint:
            progress = self.progress_store.get(self.fingerprint) or Progress()
            progress.page_range = list(rng) if rng else None
            progress.paragraph = progress.segment = 0
            progress.paragraph_count = -1  # paragraphs differ for a new range: start at its beginning
            self.progress_store.set(self.fingerprint, progress)
        self.open_path(self.document.path, page_range=rng, use_saved_range=False, ocr_mode=self.ocr_mode)

    def _refresh_recent_menu(self) -> None:
        self.recent_menu.clear()
        recent = [p for p in self.settings.recent_files if Path(p).is_file()]
        for path in recent:
            action = QAction(Path(path).name, self)
            action.setToolTip(path)
            action.triggered.connect(lambda _=False, p=path: self.open_path(Path(p)))
            self.recent_menu.addAction(action)
        self.recent_menu.setEnabled(bool(recent))

    # ======================================================= drag & drop
    def _dropped_path(self, event) -> Path | None:
        if not event.mimeData().hasUrls():
            return None
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                return path
        return None

    def dragEnterEvent(self, event):  # noqa: N802 (Qt API)
        if self._dropped_path(event):
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        path = self._dropped_path(event)
        if path:
            event.acceptProposedAction()
            self.open_path(path)

    # ===================================================== voice settings
    def _resolved_language(self) -> str:
        choice = self.lang_combo.currentData() if hasattr(self, "lang_combo") else self.settings.language
        if choice in ("uk", "ru"):
            return choice
        return (self.document.language if self.document and self.document.language else "uk")

    def _apply_voice_settings(self) -> None:
        s = self.settings
        self.controller.update_voice(
            language=self._resolved_language(), voice=s.voice, speed=s.speed, expand_numbers=s.expand_numbers,
            bible_references=s.bible_references, abbreviations=s.abbreviation_tuples(),
            sentence_pause=s.sentence_pause, paragraph_pause=s.paragraph_pause)

    def _update_auto_language_label(self) -> None:
        detected = LANG_LABELS.get(self.document.language, "Українська") if self.document and self.document.language \
            else "Українська"
        self.lang_combo.setItemText(0, f"Автоматично ({detected})")

    def _language_changed(self) -> None:
        self.settings.language = self.lang_combo.currentData()
        self._save_settings()
        self.controller.update_voice(language=self._resolved_language())
        self._save_progress(force=True)

    def _voice_changed(self) -> None:
        voice = self.voice_combo.currentData()
        if voice:
            self.settings.voice = voice
            self._save_settings()
            self.controller.update_voice(voice=voice)

    def _speed_changed(self) -> None:
        self._speed_timer.start()

    def _apply_speed(self) -> None:
        speed = round(self.speed_slider.value() / 100, 2)
        if abs(speed - self.settings.speed) < 1e-6:
            return
        self.settings.speed = speed
        self._save_settings()
        self.controller.update_voice(speed=speed)

    # ===================================================== reader events
    def _seek(self, paragraph: int) -> None:
        self.controller.seek(paragraph)

    def _seek_and_play(self, paragraph: int) -> None:
        if not self.engine:
            return
        self.controller.seek(paragraph)
        self.controller.play()

    def _section_activated(self, item: QListWidgetItem) -> None:
        self._seek(item.data(Qt.UserRole))

    def _on_position(self, paragraph: int, segment: int) -> None:
        doc = self.document
        if doc is None or paragraph >= len(doc.paragraphs):
            return
        self.paragraph_view.highlight(paragraph, follow=True)
        if not self.progress_slider.isSliderDown():
            self.progress_slider.setValue(paragraph)
        total = len(doc.paragraphs)
        percent = 100.0 * (paragraph + 1) / total
        parts = [f"Абзац {paragraph + 1} з {total} · {percent:.1f}%"]
        para = doc.paragraphs[paragraph]
        if para.page:
            parts.append(f"стор. {para.page}")
        section_index = para.section
        if len(doc.sections) > 1 and section_index < len(doc.sections):
            parts.append(doc.sections[section_index].title[:40])
            self.sections_list.blockSignals(True)
            self.sections_list.setCurrentRow(section_index)
            self.sections_list.blockSignals(False)
        self.position_label.setText(" · ".join(parts))

        segments = self.controller.segments(paragraph)
        rendered = []
        for i, seg in enumerate(segments):
            text = html.escape(seg)
            rendered.append(f"<span style='background-color: rgba(255, 200, 0, 90);'>{text}</span>"
                            if i == segment else text)
        self.current_text.setHtml(f"<div style='font-size: 15px; line-height: 140%;'>{' '.join(rendered)}</div>")
        self._save_progress()

    def _on_state(self, state: str) -> None:
        playing = state in ("playing", "buffering")
        icon = QStyle.SP_MediaPause if playing else QStyle.SP_MediaPlay
        self.play_button.setIcon(self.style().standardIcon(icon))
        self.play_button.setText("Пауза" if playing else "Читати")
        self.status_label.setText(STATE_LABELS.get(state, state))
        if state in ("paused", "stopped", "finished"):
            self._save_progress(force=True)

    def _on_reader_error(self, message: str) -> None:
        log.warning("Reader error reported to user")
        self.statusBar().showMessage(message, 8000)

    # ========================================================= persistence
    def _remember_text_height(self, *_args) -> None:
        self.settings.current_text_height = self.text_splitter.sizes()[1]

    def _save_settings(self) -> None:
        try:
            self.settings.save(self.settings_path)
        except OSError as exc:
            self.statusBar().showMessage(f"Не вдалося зберегти налаштування: {exc}", 6000)

    def _save_progress(self, force: bool = False) -> None:
        if not self.document or not self.fingerprint:
            return
        paragraph, segment = self.controller.position
        last_p, last_s, last_t = self._last_saved
        if not force and (paragraph, segment) == (last_p, last_s):
            return
        if not force and paragraph == last_p and time.time() - last_t < 10:
            return
        try:
            self.progress_store.set(self.fingerprint, Progress(
                paragraph=paragraph, segment=segment, language=self.lang_combo.currentData(),
                voice=self.settings.voice,
                page_range=list(self.document.page_range) if self.document.page_range else None,
                paragraph_count=len(self.document.paragraphs), ocr_mode=self.ocr_mode))
            self._last_saved = (paragraph, segment, time.time())
        except OSError as exc:
            self.statusBar().showMessage(f"Не вдалося зберегти позицію: {exc}", 6000)

    # ============================================================ dialogs
    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.cache, self.progress_store.clear, self._clear_ocr_cache, self)
        if dialog.exec() != SettingsDialog.Accepted:
            return
        new = dialog.result_settings()
        old = self.settings
        self.settings = new
        self._save_settings()
        if (new.cache_dir, new.cache_max_mb) != (old.cache_dir, old.cache_max_mb):
            try:
                self.cache = AudioCache(Path(new.cache_dir), new.cache_max_mb * 1024 * 1024)
                self.cache.trim()
                self.controller.set_cache(self.cache)
            except OSError as exc:
                QMessageBox.critical(self, "Кеш", f"Не вдалося використати теку кешу:\n{exc}")
        self._apply_voice_settings()
        if (new.model_dir, new.quality_steps) != (old.model_dir, old.quality_steps):
            self.controller.stop()
            self.engine = None
            self._refresh_controls()
            self._load_engine()

    def _open_abbreviations(self) -> None:
        dialog = AbbreviationsDialog(self.settings.abbreviations, self._resolved_language(),
                                     self.settings.bible_references, self)
        if dialog.exec() != AbbreviationsDialog.Accepted:
            return
        self.settings.abbreviations = dialog.entries()
        self._save_settings()
        self.controller.update_voice(abbreviations=self.settings.abbreviation_tuples())
        self.statusBar().showMessage("Словник скорочень збережено", 4000)

    def _clear_ocr_cache(self) -> None:
        ocr_dir = self.data_dir / "ocr-cache"
        for path in ocr_dir.glob("*.json"):
            path.unlink(missing_ok=True)

    def _export(self, whole: bool) -> None:
        doc, engine = self.document, self.engine
        if not doc or not engine:
            return
        if whole:
            start, end, label = 0, len(doc.paragraphs), doc.title
        else:
            index = doc.section_of(self.controller.position[0])
            section = doc.sections[index]
            start = section.start
            end = doc.sections[index + 1].start if index + 1 < len(doc.sections) else len(doc.paragraphs)
            label = f"{doc.title} — {section.title}"
        safe = "".join(c for c in label if c not in '/\\:*?"<>|').strip()[:120] or "audiobook"
        # M4A needs macOS's afconvert; elsewhere (Windows) FLAC is offered first.
        formats = ["AAC (*.m4a)", "FLAC (*.flac)", "WAV (*.wav)"] if m4a_supported() else ["FLAC (*.flac)", "WAV (*.wav)"]
        suffixes = [f[f.index("*") + 1:-1] for f in formats]
        default = str(Path.home() / "Music" / f"{safe}{suffixes[0]}")
        path, _ = QFileDialog.getSaveFileName(self, "Експорт в аудіо", default, ";;".join(formats))
        if not path:
            return
        out = Path(path)
        if out.suffix.lower() not in suffixes:
            out = out.with_suffix(suffixes[0])

        self.controller.pause()
        dialog = QProgressDialog("Генерування аудіо…", "Скасувати", 0, end - start, self)
        dialog.setWindowTitle("Експорт")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        cancel = threading.Event()
        exporter = BackgroundTask(export_audio, doc, start, end, out, engine, self.cache,
                                  VoiceSettings(**vars(self.controller.voice)),
                                  progress=lambda done, total: exporter.progress.emit(done, total), cancel=cancel)
        exporter.progress.connect(lambda done, _total: dialog.setValue(done))
        dialog.canceled.connect(cancel.set)

        def finished(_result):
            dialog.close()
            QMessageBox.information(self, "Експорт завершено", f"Аудіо збережено:\n{out}")

        def failed(exc):
            dialog.close()
            if not isinstance(exc, ExportCancelled):
                QMessageBox.critical(self, "Помилка експорту", str(exc))

        exporter.succeeded.connect(finished)
        exporter.failed.connect(failed)
        exporter.start()

    def _about(self) -> None:
        QMessageBox.about(self, APP_NAME, (
            f"<b>{APP_NAME}</b><br>Локальна читалка аудіокниг українською та російською.<br><br>"
            "Синтез мовлення: Supertonic 3 (Supertone Inc., ліцензія OpenRAIL-M), ONNX Runtime.<br>"
            "Усі документи, аудіо й позиції читання залишаються на цьому комп'ютері.<br><br>"
            f"Розробник: {AUTHOR}"))

    # ============================================================== close
    def closeEvent(self, event):  # noqa: N802
        self._save_progress(force=True)
        self._save_settings()
        self.controller.shutdown()
        super().closeEvent(event)
