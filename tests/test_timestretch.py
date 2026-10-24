import numpy as np
import pytest

from audiobook_reader.audio.cache import AudioCache
from audiobook_reader.audio.timestretch import time_stretch
from audiobook_reader.reader.controller import VoiceSettings, model_speed, pause_seconds, synthesize_segment
from test_controller import FakeEngine

SR = 44100


def _peak_hz(x):
    spectrum = np.abs(np.fft.rfft(x * np.hanning(x.size)))
    return np.fft.rfftfreq(x.size, 1 / SR)[np.argmax(spectrum)]


@pytest.mark.parametrize("rate", [0.7, 0.8, 1.25, 1.6, 2.0, 2.5, 3.0])
def test_duration_changes_but_pitch_does_not(rate):
    t = np.arange(int(2.0 * SR)) / SR
    tone = (0.4 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    out = time_stretch(tone, rate, SR)
    assert abs(out.size - tone.size / rate) <= 1
    assert abs(_peak_hz(out[SR // 10: -SR // 10]) - 220) < 3
    assert np.max(np.abs(out)) < 0.5  # overlap-add is normalized: no clipping or boost


def test_identity_and_tiny_inputs():
    x = np.random.default_rng(0).uniform(-0.3, 0.3, SR).astype(np.float32)
    assert np.array_equal(time_stretch(x, 1.0, SR), x)
    assert time_stretch(np.zeros(0, np.float32), 1.5, SR).size == 0
    short = x[:100]
    assert np.array_equal(time_stretch(short, 1.5, SR), short)


def test_fast_speed_reuses_audio_synthesized_at_natural_speed(tmp_path):
    engine = FakeEngine()
    engine.sample_rate = SR
    engine.natural_speed_min = engine.natural_speed_max = 1.0
    speeds = []
    speech = np.random.default_rng(1).uniform(-0.3, 0.3, SR).astype(np.float32)  # 1 s

    def synthesize(text, lang, voice, speed):
        speeds.append(speed)
        return speech

    engine.synthesize = synthesize
    cache = AudioCache(tmp_path / "c")
    normal = synthesize_segment(engine, cache, "Текст.", VoiceSettings(speed=1.0))
    fast = synthesize_segment(engine, cache, "Текст.", VoiceSettings(speed=2.0))
    faster = synthesize_segment(engine, cache, "Текст.", VoiceSettings(speed=1.6))
    assert speeds == [1.0]  # the model ran once, at its natural speed; the rest came from the cache
    assert abs(fast.size - normal.size / 2.0) <= 1
    assert abs(faster.size - normal.size / 1.6) <= 1

    slow = synthesize_segment(engine, cache, "Текст.", VoiceSettings(speed=0.8))
    assert speeds == [1.0]  # slowing down is done by time stretching too
    assert abs(slow.size - normal.size / 0.8) <= 1


def test_model_speed_and_pauses():
    engine = FakeEngine()
    engine.natural_speed_min = engine.natural_speed_max = 1.0
    assert model_speed(engine, 1.8) == 1.0
    assert model_speed(engine, 0.75) == 1.0
    assert model_speed(FakeEngine(), 0.75) == 0.75  # engines that handle speed natively keep it
    voice = VoiceSettings(speed=2.0, paragraph_pause=0.6, sentence_pause=0.2)
    assert pause_seconds(voice, True) == pytest.approx(0.3)
    assert pause_seconds(VoiceSettings(speed=0.8, sentence_pause=0.2), False) == pytest.approx(0.2)
