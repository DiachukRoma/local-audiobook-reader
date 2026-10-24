"""Real Supertonic 3 synthesis tests (skipped when the model is not downloaded)."""

import io

import numpy as np
import pytest
import soundfile as sf

from audiobook_reader.storage.settings import DEFAULT_MODEL_DIR
from audiobook_reader.tts.base import ModelMissingError, TTSError
from audiobook_reader.tts.supertonic_engine import SupertonicEngine, model_present
from audiobook_reader.tts.text_prep import prepare_for_tts

pytestmark = pytest.mark.skipif(not model_present(DEFAULT_MODEL_DIR), reason="Supertonic 3 model not downloaded")


@pytest.fixture(scope="module")
def engine():
    return SupertonicEngine(DEFAULT_MODEL_DIR)


def test_missing_model_is_reported(tmp_path):
    with pytest.raises(ModelMissingError):
        SupertonicEngine(tmp_path / "nothing")


def test_engine_initialization(engine):
    assert engine.sample_rate == 44100
    assert {v.id for v in engine.voices()} == {f"F{i}" for i in range(1, 6)} | {f"M{i}" for i in range(1, 6)}
    assert engine.engine_id.startswith("supertonic-3@")


@pytest.mark.parametrize("lang,text", [
    ("uk", "Доброго ранку! Сьогодні ми читаємо книжку українською мовою: їжак, ґанок, сім'я."),
    ("ru", "Доброе утро! Сегодня мы читаем книгу на русском языке: ёжик, щётка, съезд."),
])
def test_real_synthesis_produces_decodable_audio(engine, lang, text):
    audio = engine.synthesize(prepare_for_tts(text, lang), lang, "F1", 1.0)
    assert audio.dtype == np.float32
    seconds = audio.size / engine.sample_rate
    assert 2.0 < seconds < 20.0
    rms = float(np.sqrt(np.mean(audio ** 2)))
    assert rms > 0.01  # not silence
    buf = io.BytesIO()
    sf.write(buf, audio, engine.sample_rate, format="WAV", subtype="PCM_16")
    buf.seek(0)
    decoded, sr = sf.read(buf, dtype="float32")
    assert sr == 44100 and decoded.size == audio.size


def test_speed_changes_duration(engine):
    text = "Швидкість читання можна змінювати."
    slow = engine.synthesize(text, "uk", "M1", 0.8).size
    fast = engine.synthesize(text, "uk", "M1", 1.6).size
    assert fast < slow * 0.8


def test_unsupported_characters_do_not_crash(engine):
    audio = engine.synthesize("Текст із символами ✓ ★ ☃ та емодзі 😀.", "uk", "F2", 1.0)
    assert audio.size > 0
    assert engine.synthesize("★ ✓", "uk", "F2", 1.0).size == 0


def test_invalid_language_and_voice(engine):
    with pytest.raises(TTSError):
        engine.synthesize("Hello", "en", "F1", 1.0)
    with pytest.raises(TTSError):
        engine.synthesize("Текст", "uk", "Z9", 1.0)


def test_onnxruntime_telemetry_is_disabled(monkeypatch):
    import onnxruntime

    calls = []
    monkeypatch.setattr(onnxruntime, "disable_telemetry_events", lambda: calls.append(True))
    SupertonicEngine(DEFAULT_MODEL_DIR)
    assert calls
