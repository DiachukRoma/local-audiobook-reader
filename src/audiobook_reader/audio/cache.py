"""Size-bounded on-disk cache of synthesized segments (FLAC, 16-bit)."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

import numpy as np
import soundfile as sf

log = logging.getLogger(__name__)


def cache_key(*parts: object) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class AudioCache:
    def __init__(self, directory: Path, max_bytes: int = 2 * 1024**3):
        self.directory = Path(directory)
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self._writes_since_trim = 0
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.flac"

    def get(self, key: str) -> np.ndarray | None:
        path = self._path(key)
        if not path.is_file():
            return None
        try:
            audio, _sr = sf.read(path, dtype="float32", always_2d=False)
        except Exception:
            log.warning("Corrupt cache entry removed: %s", path.name)
            path.unlink(missing_ok=True)
            return None
        try:
            os.utime(path)  # mark as recently used for LRU eviction
        except OSError:
            pass
        return audio

    def put(self, key: str, audio: np.ndarray, sample_rate: int) -> None:
        if audio.size == 0:
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        sf.write(tmp, np.clip(audio, -1.0, 1.0), sample_rate, format="FLAC", subtype="PCM_16")
        os.replace(tmp, path)
        with self._lock:
            self._writes_since_trim += 1
            due = self._writes_since_trim >= 50
            if due:
                self._writes_since_trim = 0
        if due:
            self.trim()

    def _entries(self) -> list[tuple[float, int, Path]]:
        entries = []
        for path in self.directory.glob("*/*.flac"):
            try:
                st = path.stat()
            except OSError:
                continue
            entries.append((st.st_mtime, st.st_size, path))
        return entries

    def size_bytes(self) -> int:
        return sum(size for _, size, _ in self._entries())

    def trim(self) -> int:
        """Delete least recently used entries until the cache fits ``max_bytes``."""
        entries = sorted(self._entries())
        total = sum(size for _, size, _ in entries)
        removed = 0
        for _mtime, size, path in entries:
            if total <= self.max_bytes:
                break
            path.unlink(missing_ok=True)
            total -= size
            removed += 1
        if removed:
            log.info("Audio cache trimmed: %d files removed", removed)
        return removed

    def clear(self) -> None:
        """Remove every cached audio file (only files this cache created)."""
        for _mtime, _size, path in self._entries():
            path.unlink(missing_ok=True)
        for sub in self.directory.glob("*"):
            if sub.is_dir() and not any(sub.iterdir()):
                sub.rmdir()
