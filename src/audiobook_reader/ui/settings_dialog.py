"""Settings dialog: model and cache locations, cache size, synthesis options."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractSpinBox, QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ..audio.cache import AudioCache
from ..storage.settings import FONT_SIZE_MAX, FONT_SIZE_MIN, Settings

FIELD_WIDTH = 130  # every number field has the same width, so the column lines up


def _muted(label: QLabel) -> QLabel:
    """Secondary text: the window text colour, half transparent (readable in light and dark themes)."""
    palette = label.palette()
    color = palette.color(palette.ColorRole.WindowText)
    color.setAlpha(150)
    palette.setColor(palette.ColorRole.WindowText, color)
    label.setPalette(palette)
    label.setWordWrap(True)
    return label


def _number(spin: QAbstractSpinBox, tip: str = "") -> QAbstractSpinBox:
    spin.setFixedWidth(FIELD_WIDTH)
    spin.setMinimumHeight(28)
    spin.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    spin.lineEdit().setTextMargins(6, 0, 4, 0)
    if tip:
        spin.setToolTip(tip)
    return spin


def _with_hint(field: QWidget, hint: str | QLabel) -> QWidget:
    """A field with a short grey explanation to its right."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    layout.addWidget(field)
    layout.addWidget(hint if isinstance(hint, QLabel) else _muted(QLabel(hint)), 1)
    return row


def _path_row(edit: QLineEdit, parent: QWidget) -> QWidget:
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    edit.setMinimumWidth(320)
    edit.setMinimumHeight(28)
    edit.setTextMargins(4, 0, 4, 0)
    edit.setToolTip(edit.text())
    edit.textChanged.connect(edit.setToolTip)
    edit.setCursorPosition(0)  # show the start of a long path, not its tail
    button = QPushButton("Обрати…", row)

    def browse():
        chosen = QFileDialog.getExistingDirectory(parent, "Оберіть теку", edit.text())
        if chosen:
            edit.setText(chosen)
            edit.setCursorPosition(0)

    button.clicked.connect(browse)
    layout.addWidget(edit, 1)
    layout.addWidget(button)
    return row


def _form() -> QFormLayout:
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(8)
    return form


def _align_labels(*forms: QFormLayout) -> None:
    """Give the label column of several forms one width, so fields line up across group boxes."""
    labels = []
    for form in forms:
        for row in range(form.rowCount()):
            item = form.itemAt(row, QFormLayout.LabelRole)
            if item is not None and item.widget() is not None:
                labels.append(item.widget())
    width = max((label.sizeHint().width() for label in labels), default=0)
    for label in labels:
        label.setMinimumWidth(width)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, cache: AudioCache | None, clear_progress, clear_ocr=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Налаштування")
        self.setMinimumWidth(720)
        self._settings = settings
        self._cache = cache
        self._clear_progress = clear_progress
        self._clear_ocr = clear_ocr

        self.model_dir = QLineEdit(settings.model_dir)
        self.cache_dir = QLineEdit(settings.cache_dir)
        self.cache_max = _number(QSpinBox(suffix=" МБ", minimum=100, maximum=200_000, singleStep=256,
                                          value=settings.cache_max_mb))
        self.steps = _number(QSpinBox(minimum=4, maximum=16, value=settings.quality_steps),
                             "Більше кроків — трохи якісніший звук, але повільніший синтез. Типово 8.")
        self.threads = _number(QSpinBox(minimum=0, maximum=16, value=settings.synthesis_threads,
                                        specialValueText="авто"),
                               "Скільки ядер процесора використовує синтез мовлення. Типово 3: так само швидко, "
                               "як і більше потоків, але процесор майже не навантажений.")
        self.par_pause = _number(QDoubleSpinBox(suffix=" с", minimum=0.0, maximum=3.0, singleStep=0.05,
                                                value=settings.paragraph_pause))
        self.sent_pause = _number(QDoubleSpinBox(suffix=" с", minimum=0.0, maximum=2.0, singleStep=0.05,
                                                 value=settings.sentence_pause))
        self.font_size = _number(QSpinBox(suffix=" px", minimum=FONT_SIZE_MIN, maximum=FONT_SIZE_MAX,
                                          value=settings.current_text_font_size),
                                 "Розмір тексту в нижньому блоці, де показано абзац, що читається.")
        self.expand = QCheckBox("Читати числа й скорочення словами (рекомендовано)")
        self.expand.setChecked(settings.expand_numbers)
        self.expand.setToolTip("Змінюється лише текст, що надсилається синтезатору; книжка не змінюється.")
        self.bible = QCheckBox("Читати біблійні посилання повністю")
        self.bible.setChecked(settings.bible_references)
        self.bible.setToolTip("Мт. 5:3 → «Матвія, п'ятий розділ, третій вірш»")

        # Speech
        speech = _form()
        speech.addRow("Якість (кроки):", _with_hint(self.steps, "типово 8; більше — повільніше"))
        speech.addRow("Потоки синтезу:", _with_hint(self.threads, "типово 3"))
        speech.addRow("Пауза між абзацами:", self.par_pause)
        speech.addRow("Пауза між реченнями:", self.sent_pause)
        checks = QVBoxLayout()
        checks.setSpacing(4)
        checks.addWidget(self.expand)
        checks.addWidget(self.bible)
        checks.addWidget(_muted(QLabel("     Мт. 5:3 → «Матвія, п'ятий розділ, третій вірш»")))
        speech.addRow("", checks)
        speech_box = QGroupBox("Мовлення")
        speech_box.setLayout(speech)

        # Appearance
        view = _form()
        view.addRow("Шрифт поточного абзацу:", _with_hint(self.font_size, "типово 15 px"))
        view_box = QGroupBox("Вигляд")
        view_box.setLayout(view)

        # Files and stored data
        files = _form()
        files.addRow("Тека моделі Supertonic 3:", _path_row(self.model_dir, self))
        files.addRow("Тека аудіокешу:", _path_row(self.cache_dir, self))
        self.cache_label = _muted(QLabel())
        files.addRow("Максимальний розмір кешу:", _with_hint(self.cache_max, self.cache_label))

        clear_cache = QPushButton("Очистити аудіокеш")
        clear_cache.clicked.connect(self._clear_cache)
        clear_progress_btn = QPushButton("Скинути позиції читання")
        clear_progress_btn.setToolTip("Забути, де ви зупинилися, в усіх книжках")
        clear_progress_btn.clicked.connect(self._reset_progress)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        tools.addWidget(clear_cache)
        tools.addWidget(clear_progress_btn)
        if clear_ocr is not None:
            clear_ocr_btn = QPushButton("Очистити кеш OCR")
            clear_ocr_btn.setToolTip("Видалити збережений розпізнаний текст сканованих PDF")
            clear_ocr_btn.clicked.connect(self._clear_ocr_cache)
            tools.addWidget(clear_ocr_btn)
        tools.addStretch(1)
        files_box = QGroupBox("Файли й дані")
        files_layout = QVBoxLayout(files_box)
        files_layout.addLayout(files)
        files_layout.addSpacing(4)
        files_layout.addLayout(tools)
        files_layout.addWidget(_muted(QLabel("Усі дані (текст, аудіо, позиції, модель) зберігаються лише на цьому "
                                             "комп'ютері.")))
        _align_labels(speech, view, files)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Зберегти")
        buttons.button(QDialogButtonBox.Cancel).setText("Скасувати")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        layout.addWidget(speech_box)
        layout.addWidget(view_box)
        layout.addWidget(files_box)
        layout.addSpacing(4)
        layout.addWidget(buttons)
        self._update_cache_label()

    def _update_cache_label(self) -> None:
        if self._cache is None:
            self.cache_label.setText("")
            return
        mb = self._cache.size_bytes() / (1024 * 1024)
        self.cache_label.setText(f"зараз зайнято {mb:.0f} МБ")

    def _clear_cache(self) -> None:
        if self._cache is None:
            return
        if QMessageBox.question(self, "Очистити кеш", "Видалити всі згенеровані аудіофрагменти? "
                                "Книжки й позиції читання не зачіпаються.") == QMessageBox.Yes:
            self._cache.clear()
            self._update_cache_label()

    def _clear_ocr_cache(self) -> None:
        if QMessageBox.question(self, "Очистити кеш OCR", "Видалити розпізнаний текст сканованих PDF? "
                                "Наступного відкриття їх буде розпізнано повторно.") == QMessageBox.Yes:
            self._clear_ocr()

    def _reset_progress(self) -> None:
        if QMessageBox.question(self, "Скинути позиції", "Забути збережені позиції читання для всіх книжок?") \
                == QMessageBox.Yes:
            self._clear_progress()

    def result_settings(self) -> Settings:
        return replace(
            self._settings,
            model_dir=self.model_dir.text().strip(),
            cache_dir=self.cache_dir.text().strip(),
            cache_max_mb=self.cache_max.value(),
            quality_steps=self.steps.value(),
            synthesis_threads=self.threads.value(),
            expand_numbers=self.expand.isChecked(),
            bible_references=self.bible.isChecked(),
            paragraph_pause=round(self.par_pause.value(), 2),
            sentence_pause=round(self.sent_pause.value(), 2),
            current_text_font_size=self.font_size.value(),
        )
