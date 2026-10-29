"""Settings dialog: model and cache locations, cache size, synthesis options."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)

from ..audio.cache import AudioCache
from ..storage.settings import FONT_SIZE_MAX, FONT_SIZE_MIN, Settings


def _path_row(edit: QLineEdit, parent: QWidget) -> QWidget:
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    button = QPushButton("Обрати…", row)

    def browse():
        chosen = QFileDialog.getExistingDirectory(parent, "Оберіть теку", edit.text())
        if chosen:
            edit.setText(chosen)

    button.clicked.connect(browse)
    layout.addWidget(edit, 1)
    layout.addWidget(button)
    return row


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, cache: AudioCache | None, clear_progress, clear_ocr=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Налаштування")
        self.setMinimumWidth(560)
        self._settings = settings
        self._cache = cache
        self._clear_progress = clear_progress
        self._clear_ocr = clear_ocr

        self.model_dir = QLineEdit(settings.model_dir)
        self.cache_dir = QLineEdit(settings.cache_dir)
        self.cache_max = QSpinBox(suffix=" МБ", minimum=100, maximum=200_000, singleStep=256, value=settings.cache_max_mb)
        self.steps = QSpinBox(minimum=4, maximum=16, value=settings.quality_steps)
        self.steps.setToolTip("Більше кроків — трохи якісніший звук, але повільніший синтез. Типово 8.")
        self.threads = QSpinBox(minimum=0, maximum=16, value=settings.synthesis_threads, specialValueText="авто")
        self.threads.setToolTip("Скільки ядер процесора використовує синтез мовлення. Типово 3: так само швидко, "
                                "як і більше потоків, але процесор майже не навантажений.")
        self.expand = QCheckBox("Читати числа й скорочення словами (рекомендовано)")
        self.expand.setChecked(settings.expand_numbers)
        self.expand.setToolTip("Змінюється лише текст, що надсилається синтезатору; книжка не змінюється.")
        self.bible = QCheckBox("Читати біблійні посилання повністю (Мт. 5:3 → «Матвія, п'ятий розділ, третій вірш»)")
        self.bible.setChecked(settings.bible_references)
        self.par_pause = QDoubleSpinBox(suffix=" с", minimum=0.0, maximum=3.0, singleStep=0.05, value=settings.paragraph_pause)
        self.sent_pause = QDoubleSpinBox(suffix=" с", minimum=0.0, maximum=2.0, singleStep=0.05, value=settings.sentence_pause)
        self.font_size = QSpinBox(suffix=" px", minimum=FONT_SIZE_MIN, maximum=FONT_SIZE_MAX,
                                  value=settings.current_text_font_size)
        self.font_size.setToolTip("Розмір тексту в нижньому блоці, де показано абзац, що читається. Типово 15 px.")

        form = QFormLayout()
        form.addRow("Тека моделі Supertonic 3:", _path_row(self.model_dir, self))
        form.addRow("Тека аудіокешу:", _path_row(self.cache_dir, self))
        form.addRow("Максимальний розмір кешу:", self.cache_max)
        form.addRow("Якість синтезу (кроки):", self.steps)
        form.addRow("Потоки синтезу:", self.threads)
        form.addRow("Пауза між абзацами:", self.par_pause)
        form.addRow("Пауза між фрагментами:", self.sent_pause)
        form.addRow("Шрифт поточного абзацу:", self.font_size)
        form.addRow("", self.expand)
        form.addRow("", self.bible)

        self.cache_label = QLabel()
        clear_cache = QPushButton("Очистити аудіокеш")
        clear_cache.clicked.connect(self._clear_cache)
        clear_progress_btn = QPushButton("Скинути збережені позиції читання")
        clear_progress_btn.clicked.connect(self._reset_progress)
        tools = QHBoxLayout()
        tools.addWidget(self.cache_label, 1)
        tools.addWidget(clear_cache)
        tools.addWidget(clear_progress_btn)
        if clear_ocr is not None:
            clear_ocr_btn = QPushButton("Очистити кеш OCR")
            clear_ocr_btn.setToolTip("Видалити збережений розпізнаний текст сканованих PDF")
            clear_ocr_btn.clicked.connect(self._clear_ocr_cache)
            tools.addWidget(clear_ocr_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Зберегти")
        buttons.button(QDialogButtonBox.Cancel).setText("Скасувати")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        note = QLabel("Усі дані (текст, аудіо, позиції, модель) зберігаються лише на цьому комп'ютері.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(tools)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self._update_cache_label()

    def _update_cache_label(self) -> None:
        if self._cache is None:
            self.cache_label.setText("")
            return
        mb = self._cache.size_bytes() / (1024 * 1024)
        self.cache_label.setText(f"Зараз у кеші: {mb:.0f} МБ")

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
