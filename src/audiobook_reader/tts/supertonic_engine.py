"""Supertonic 3 (Supertone, OpenRAIL-M) running locally through ONNX Runtime."""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from .base import ModelMissingError, TTSEngine, TTSError, Voice

log = logging.getLogger(__name__)

MODEL_NAME = "supertonic-3"
MODEL_REPO = "Supertone/supertonic-3"
APPROX_DOWNLOAD_MB = 385
_REQUIRED_FILES = (
    "onnx/tts.json",
    "onnx/unicode_indexer.json",
    "onnx/duration_predictor.onnx",
    "onnx/text_encoder.onnx",
    "onnx/vector_estimator.onnx",
    "onnx/vocoder.onnx",
)
_VOICE_LABELS = {
    **{f"F{i}": f"Жіночий голос {i} (F{i})" for i in range(1, 6)},
    **{f"M{i}": f"Чоловічий голос {i} (M{i})" for i in range(1, 6)},
}


def _disable_onnxruntime_telemetry() -> None:
    """ONNX Runtime ships platform telemetry (1DS); this application must not send any."""
    try:
        import onnxruntime

        onnxruntime.disable_telemetry_events()
    except (ImportError, AttributeError):
        pass


DEFAULT_THREADS = 3


@contextmanager
def _sessions_without_spinning():
    """Make the ONNX sessions supertonic creates sleep between operations instead of busy-waiting.

    supertonic builds its own ``SessionOptions`` and does not expose this option, so its loader
    sees an ``onnxruntime`` whose SessionOptions has it set. Spinning threads kept several cores
    at 100 % for no gain; with spinning off synthesis is as fast and uses about a third of the CPU.
    """
    import onnxruntime
    import supertonic.loader as loader

    class _Runtime:
        def __getattr__(self, name):
            return getattr(onnxruntime, name)

        @staticmethod
        def SessionOptions():  # noqa: N802 (mirrors the onnxruntime API)
            options = onnxruntime.SessionOptions()
            options.add_session_config_entry("session.intra_op.allow_spinning", "0")
            options.add_session_config_entry("session.inter_op.allow_spinning", "0")
            return options

    original = loader.ort
    loader.ort = _Runtime()
    try:
        yield
    finally:
        loader.ort = original


def model_present(model_dir: Path) -> bool:
    return all((model_dir / rel).is_file() for rel in _REQUIRED_FILES) and any(
        (model_dir / "voice_styles").glob("*.json"))


def download_model(model_dir: Path) -> None:
    """Download the pinned model revision from Hugging Face (explicit user action only)."""
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from supertonic.loader import download_model as _download

    model_dir.parent.mkdir(parents=True, exist_ok=True)
    _download(model_dir, MODEL_NAME)
    if not model_present(model_dir):
        raise TTSError("Модель завантажено не повністю.")


class SupertonicEngine(TTSEngine):
    languages = ("uk", "ru")
    speed_range = (0.7, 2.0)
    # Away from 1.0 Supertonic 3 degrades (verified with ASR): at 1.6×–2.0× it drops whole
    # words, at 0.7× it repeats and garbles them. It therefore always speaks at 1.0 and the
    # tempo is changed afterwards by time stretching.
    natural_speed_min = 1.0
    natural_speed_max = 1.0

    def __init__(self, model_dir: Path, quality_steps: int = 8, threads: int = DEFAULT_THREADS):
        """``threads``: CPU threads per operation, 0 lets ONNX Runtime decide. Operations run one after
        another (inter-op 1): the default thread pools use every core, the slow efficiency cores too, and
        on a 16-core laptop made synthesis 4× slower while loading the CPU to 90 %."""
        model_dir = Path(model_dir)
        if not model_present(model_dir):
            raise ModelMissingError(
                f"Модель Supertonic 3 не знайдено в «{model_dir}». "
                f"Її потрібно один раз завантажити (≈{APPROX_DOWNLOAD_MB} МБ).")
        # Never reach the network at runtime: the model is loaded from disk only.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        _disable_onnxruntime_telemetry()
        from supertonic import TTS

        try:
            with _sessions_without_spinning():
                self._tts = TTS(model=MODEL_NAME, model_dir=model_dir, auto_download=False,
                                intra_op_num_threads=threads or None, inter_op_num_threads=1)
        except Exception as exc:
            raise TTSError(f"Не вдалося завантажити модель: {exc}") from exc
        self._model_dir = model_dir
        self._steps = quality_steps
        self._styles: dict = {}
        self._lock = threading.Lock()  # ONNX sessions are used from one worker at a time
        self.sample_rate = int(self._tts.sample_rate)
        self.engine_id = f"{MODEL_NAME}@{self._model_revision()}/steps{quality_steps}"
        log.info("Supertonic loaded: sample_rate=%s threads=%s voices=%s", self.sample_rate, threads or "auto",
                 self._tts.voice_style_names)

    def _model_revision(self) -> str:
        from supertonic.config import get_model_revision
        return get_model_revision(MODEL_NAME)[:12]

    def voices(self) -> list[Voice]:
        return [Voice(name, _VOICE_LABELS.get(name, name)) for name in sorted(self._tts.voice_style_names)]

    def _style(self, voice: str):
        if voice not in self._styles:
            if voice not in self._tts.voice_style_names:
                raise TTSError(f"Невідомий голос: {voice}")
            self._styles[voice] = self._tts.get_voice_style(voice)
        return self._styles[voice]

    def _strip_unsupported(self, text: str) -> str:
        """Replace characters the model cannot pronounce with spaces instead of failing."""
        ok, bad = self._tts.model.text_processor.validate_text(text)
        if ok:
            return text
        return " ".join("".join(" " if ch in bad else ch for ch in text).split())

    def synthesize(self, text: str, lang: str, voice: str, speed: float) -> np.ndarray:
        if lang not in self.languages:
            raise TTSError(f"Мова не підтримується: {lang}")
        text = self._strip_unsupported(text)
        if not any(ch.isalnum() for ch in text):
            return np.zeros(0, dtype=np.float32)
        lo, hi = self.speed_range
        speed = min(max(speed, lo), hi)
        with self._lock:
            try:
                wav, _duration = self._tts.synthesize(
                    text, voice_style=self._style(voice), total_steps=self._steps,
                    speed=speed, lang=lang, max_chunk_length=300, silence_duration=0.15)
            except Exception as exc:
                raise TTSError(f"Помилка синтезу: {exc}") from exc
        audio = np.asarray(wav, dtype=np.float32).reshape(-1)
        if not np.isfinite(audio).all():
            raise TTSError("Модель повернула некоректний аудіосигнал.")
        return audio
