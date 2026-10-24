"""Settings and reading-progress persistence (atomic JSON files)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)

APP_DIR_NAME = "Local Audiobook Reader"
# True inside an installed build (PyInstaller); False when run from the project folder.
FROZEN = bool(getattr(sys, "frozen", False))
PROJECT_ROOT = Path(__file__).resolve().parents[3]
# Read-only files shipped with the application (icon, bundled speech model).
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))


def _user_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_DIR_NAME
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "local-audiobook-reader"


# An installed build keeps settings and caches in the user's profile; a source checkout keeps them in ./data.
DEFAULT_DATA_DIR = _user_data_dir() if FROZEN else PROJECT_ROOT / "data"
_SHIPPED_MODEL_DIR = RESOURCE_ROOT / "models" / "supertonic-3"
# A build made without the model downloads it on first start into the user's data folder.
DEFAULT_MODEL_DIR = (_SHIPPED_MODEL_DIR if not FROZEN or _SHIPPED_MODEL_DIR.is_dir()
                     else DEFAULT_DATA_DIR / "models" / "supertonic-3")
# Playback speed range. The model always speaks naturally; tempo is changed by time stretching.
SPEED_MIN, SPEED_MAX = 0.7, 3.0


def _atomic_write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _read_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        log.warning("Unreadable JSON ignored: %s", path.name)
        return {}


# Church abbreviations that read the same in any grammatical case. Editable in the app.
DEFAULT_ABBREVIATIONS = [
    ["Св. Письмо", "Святе Письмо", "uk"],
    ["Св. Писання", "Святе Писання", "uk"],
    ["Св. Дух", "Святий Дух", "uk"],
    ["Р. Х.", "Різдва Христового", "uk"],
    ["н. е.", "нашої ери", "uk"],
    ["Св. Писание", "Священное Писание", "ru"],
    ["Св. Дух", "Святой Дух", "ru"],
    ["Р. Х.", "Рождества Христова", "ru"],
    ["н. э.", "нашей эры", "ru"],
]


@dataclass
class Settings:
    model_dir: str = str(DEFAULT_MODEL_DIR)
    cache_dir: str = str(DEFAULT_DATA_DIR / "audio-cache")
    cache_max_mb: int = 2048
    language: str = "auto"  # auto | uk | ru
    voice: str = "F1"
    speed: float = 1.0
    quality_steps: int = 8
    expand_numbers: bool = True
    bible_references: bool = True
    abbreviations: list[list[str]] = field(default_factory=lambda: [list(e) for e in DEFAULT_ABBREVIATIONS])
    paragraph_pause: float = 0.55
    sentence_pause: float = 0.2
    recent_files: list[str] = field(default_factory=list)
    current_text_height: int = 120

    @classmethod
    def load(cls, path: Path) -> "Settings":
        raw = _read_json(path)
        known = {f.name for f in fields(cls)}
        settings = cls(**{k: v for k, v in raw.items() if k in known})
        settings.speed = min(max(float(settings.speed), SPEED_MIN), SPEED_MAX)
        settings.quality_steps = min(max(int(settings.quality_steps), 2), 32)
        settings.current_text_height = min(max(int(settings.current_text_height), 50), 2000)
        if not settings.model_dir or (FROZEN and not Path(settings.model_dir).is_dir()):
            settings.model_dir = str(DEFAULT_MODEL_DIR)
        if settings.language not in ("auto", "uk", "ru"):
            settings.language = "auto"
        settings.abbreviations = [
            [str(e[0]), str(e[1]), e[2] if len(e) > 2 and e[2] in ("all", "uk", "ru") else "all"]
            for e in settings.abbreviations if isinstance(e, (list, tuple)) and len(e) >= 2]
        return settings

    def abbreviation_tuples(self) -> tuple[tuple[str, str, str], ...]:
        return tuple((e[0], e[1], e[2]) for e in self.abbreviations if e[0].strip() and e[1].strip())

    def save(self, path: Path) -> None:
        data = asdict(self)
        if self.model_dir == str(DEFAULT_MODEL_DIR):
            # Not pinned to an absolute path, so a moved or updated app finds its own bundled model.
            data["model_dir"] = ""
        _atomic_write_json(path, data)

    def add_recent(self, file_path: str, limit: int = 10) -> None:
        self.recent_files = [file_path] + [p for p in self.recent_files if p != file_path]
        del self.recent_files[limit:]


def document_fingerprint(path: Path) -> str:
    """Stable id of a file's content (size + first/last MiB), independent of its location."""
    st = path.stat()
    h = hashlib.sha256(str(st.st_size).encode())
    with open(path, "rb") as fh:
        h.update(fh.read(1 << 20))
        if st.st_size > 2 << 20:
            fh.seek(-(1 << 20), os.SEEK_END)
            h.update(fh.read(1 << 20))
    return h.hexdigest()[:32]


@dataclass
class Progress:
    paragraph: int = 0
    segment: int = 0
    language: str | None = None
    voice: str | None = None
    page_range: list[int] | None = None
    paragraph_count: int = 0
    ocr_mode: str | None = None  # "scans" / "all" when the PDF was read via OCR
    updated: float = 0.0


class ProgressStore:
    """Reading positions keyed by document fingerprint. Stores no book text."""

    def __init__(self, path: Path):
        self.path = path
        self._data = _read_json(path)

    def get(self, fingerprint: str) -> Progress | None:
        raw = self._data.get(fingerprint)
        if not isinstance(raw, dict):
            return None
        known = {f.name for f in fields(Progress)}
        try:
            return Progress(**{k: v for k, v in raw.items() if k in known})
        except TypeError:
            return None

    def set(self, fingerprint: str, progress: Progress) -> None:
        progress.updated = time.time()
        self._data[fingerprint] = asdict(progress)
        _atomic_write_json(self.path, self._data)

    def clear(self) -> None:
        self._data = {}
        _atomic_write_json(self.path, self._data)
