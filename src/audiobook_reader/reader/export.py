"""Export a paragraph range (chapter or whole book) to an audio file.

Audio is streamed to disk segment by segment, so memory use stays constant.
M4A (AAC) output uses macOS's built-in ``afconvert``; no extra software needed.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np
import soundfile as sf

from ..audio.cache import AudioCache
from ..document import Document
from ..document.chunking import split_segments
from ..tts.base import TTSEngine
from ..tts.text_prep import prepare_for_tts
from .controller import VoiceSettings, pause_seconds, synthesize_segment

log = logging.getLogger(__name__)


class ExportCancelled(Exception):
    pass


def m4a_supported() -> bool:
    return shutil.which("afconvert") is not None


def export_audio(document: Document, start: int, end: int, out_path: Path, engine: TTSEngine,
                 cache: AudioCache, voice: VoiceSettings,
                 progress: Callable[[int, int], None] = lambda done, total: None,
                 cancel: threading.Event | None = None) -> Path:
    """Synthesize paragraphs ``start``..``end`` (exclusive) into ``out_path`` (.wav, .flac or .m4a)."""
    out_path = Path(out_path)
    suffix = out_path.suffix.lower()
    if suffix not in (".wav", ".flac", ".m4a"):
        raise ValueError("Підтримувані формати експорту: .m4a, .flac, .wav")
    if suffix == ".m4a" and not m4a_supported():
        raise RuntimeError("Системна утиліта afconvert недоступна; оберіть формат FLAC або WAV.")

    work_path = out_path.with_name(out_path.stem + ".part.wav") if suffix == ".m4a" else out_path
    sr = engine.sample_rate
    total = end - start
    fmt = "FLAC" if suffix == ".flac" else "WAV"
    try:
        with sf.SoundFile(work_path, "w", samplerate=sr, channels=1, format=fmt, subtype="PCM_16") as fh:
            for i, index in enumerate(range(start, end)):
                if cancel is not None and cancel.is_set():
                    raise ExportCancelled()
                segments = split_segments(document.paragraphs[index].text)
                for j, text in enumerate(segments):
                    prepared = prepare_for_tts(text, voice.language, voice.expand_numbers,
                                               voice.bible_references, voice.abbreviations)
                    fh.write(synthesize_segment(engine, cache, prepared, voice))
                    pause = pause_seconds(voice, j == len(segments) - 1)
                    fh.write(np.zeros(int(pause * sr), dtype=np.float32))
                progress(i + 1, total)
        if suffix == ".m4a":
            subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "96000", str(work_path), str(out_path)],
                           check=True, capture_output=True, timeout=3600)
            work_path.unlink(missing_ok=True)
    except BaseException:
        work_path.unlink(missing_ok=True)
        if work_path != out_path:
            out_path.unlink(missing_ok=True)
        raise
    log.info("Exported %d paragraphs", total)
    return out_path
