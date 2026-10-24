"""Editor for the user's abbreviation dictionary, with a live "how will it be read" preview."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
                               QTextBrowser, QVBoxLayout, QWidget)

from ..tts.bible import _BOOKS
from ..tts.text_prep import prepare_for_tts

LANG_CHOICES = [("Обидві мови", "all"), ("Українська", "uk"), ("Русский", "ru")]
EXAMPLES = {"uk": "Як написано в Мт. 5:3-12 і 1 Кор. 13:4, Св. Письмо вчить любові.",
            "ru": "Как написано в Мф. 5:3-12 и 1 Кор. 13:4, Св. Писание учит любви."}


class AbbreviationsDialog(QDialog):
    def __init__(self, entries: list[list[str]], language: str, bible_enabled: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Словник скорочень")
        self.resize(760, 560)
        self._language = language if language in ("uk", "ru") else "uk"
        self._bible = bible_enabled

        tabs = QTabWidget()
        tabs.addTab(self._build_own_tab(entries), "Мої скорочення")
        tabs.addTab(self._build_bible_tab(), "Біблійні книги (вбудовано)")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Зберегти")
        buttons.button(QDialogButtonBox.Cancel).setText("Скасувати")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs, 1)
        layout.addWidget(self._build_preview())
        layout.addWidget(buttons)
        self._update_preview()

    # ----------------------------------------------------------------- tabs
    def _build_own_tab(self, entries: list[list[str]]) -> QWidget:
        page = QWidget()
        info = QLabel("Скорочення замінюються лише під час читання вголос; текст книжки не змінюється. "
                      "Регістр літер має значення («Св.» і «св.» — різні записи). Пишіть повну форму в потрібному "
                      "відмінку, наприклад «св. Миколая» → «святого Миколая».")
        info.setWordWrap(True)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Скорочення", "Читати як", "Мова"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        for written, spoken, lang in entries:
            self._add_row(written, spoken, lang)
        self.table.itemChanged.connect(lambda _item: self._update_preview())

        add = QPushButton("Додати")
        add.clicked.connect(lambda: (self._add_row("", "", "all"), self.table.editItem(
            self.table.item(self.table.rowCount() - 1, 0))))
        remove = QPushButton("Видалити вибране")
        remove.clicked.connect(self._remove_selected)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)

        layout = QVBoxLayout(page)
        layout.addWidget(info)
        layout.addWidget(self.table, 1)
        layout.addLayout(row)
        return page

    def _build_bible_tab(self) -> QWidget:
        page = QWidget()
        browser = QTextBrowser()
        rows = []
        for lang, title in (("uk", "Українська"), ("ru", "Русский")):
            rows.append(f"<h3>{title}</h3><table cellspacing='0' cellpadding='3'>")
            for abbreviations, name, _kind in _BOOKS[lang]:
                rows.append(f"<tr><td><b>{name}</b></td><td>{', '.join(abbreviations)}</td></tr>")
            rows.append("</table>")
        note = ("<p>Посилання розпізнається, коли після назви книги стоїть номер розділу: «Мт. 5:3», «1 Кор. 13:4-7», "
                "«Пс. 22», «Ів 3:16». Без крапки потрібна форма «розділ:вірш», щоб звичайні слова («Як 5 людей») "
                "не зачіпалися. Номер книги (1–4 або I–IV) читається як «Перше/Перша…».</p>")
        browser.setHtml(note + "".join(rows))
        layout = QVBoxLayout(page)
        layout.addWidget(browser)
        return page

    def _build_preview(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(QLabel("Перевірити:"))
        self.preview_lang = QComboBox()
        self.preview_lang.addItem("Українська", "uk")
        self.preview_lang.addItem("Русский", "ru")
        self.preview_lang.setCurrentIndex(0 if self._language == "uk" else 1)
        self.preview_input = QLineEdit(EXAMPLES[self._language])
        top.addWidget(self.preview_input, 1)
        top.addWidget(self.preview_lang)
        self.preview_output = QLabel()
        self.preview_output.setWordWrap(True)
        self.preview_output.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.preview_output.setStyleSheet("padding: 6px; border-radius: 6px; background: rgba(127,127,127,40);")
        self.preview_input.textChanged.connect(self._update_preview)
        self.preview_lang.currentIndexChanged.connect(self._preview_language_changed)
        layout.addLayout(top)
        layout.addWidget(self.preview_output)
        return box

    # ------------------------------------------------------------- helpers
    def _add_row(self, written: str, spoken: str, lang: str) -> None:
        self.table.blockSignals(True)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(written))
        self.table.setItem(row, 1, QTableWidgetItem(spoken))
        combo = QComboBox()
        for label, code in LANG_CHOICES:
            combo.addItem(label, code)
        combo.setCurrentIndex(max(combo.findData(lang), 0))
        combo.currentIndexChanged.connect(self._update_preview)
        self.table.setCellWidget(row, 2, combo)
        self.table.blockSignals(False)

    def _remove_selected(self) -> None:
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)
        self._update_preview()

    def _preview_language_changed(self) -> None:
        lang = self.preview_lang.currentData()
        if self.preview_input.text() in EXAMPLES.values():
            self.preview_input.setText(EXAMPLES[lang])
        self._update_preview()

    def entries(self) -> list[list[str]]:
        result = []
        for row in range(self.table.rowCount()):
            written = (self.table.item(row, 0).text() if self.table.item(row, 0) else "").strip()
            spoken = (self.table.item(row, 1).text() if self.table.item(row, 1) else "").strip()
            combo = self.table.cellWidget(row, 2)
            lang = combo.currentData() if combo else "all"
            if written and spoken:
                result.append([written, spoken, lang])
        return result

    def _update_preview(self) -> None:
        lang = self.preview_lang.currentData()
        entries = tuple(tuple(e) for e in self.entries())
        spoken = prepare_for_tts(self.preview_input.text(), lang, True, self._bible, entries)
        self.preview_output.setText(f"Буде прочитано: {spoken}")
