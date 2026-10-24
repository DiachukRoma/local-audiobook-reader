"""Playback pipeline tests with a fake TTS engine and a fake audio device."""

import time

import numpy as np
import pytest

from audiobook_reader.audio.cache import AudioCache
from audiobook_reader.audio.player import AudioPlayer
from audiobook_reader.document import Document, Paragraph
from audiobook_reader.reader.controller import ReaderController, ReaderEvents
from audiobook_reader.tts.base import TTSEngine, TTSError, Voice

SR = 1000


class FakeEngine(TTSEngine):
    engine_id = "fake"
    sample_rate = SR
    languages = ("uk", "ru")

    def __init__(self, fail_on: str | None = None):
        self.calls: list[str] = []
        self.fail_on = fail_on

    def voices(self):
        return [Voice("F1", "F1")]

    def synthesize(self, text, lang, voice, speed):
        self.calls.append(text)
        if self.fail_on and self.fail_on in text:
            raise TTSError("boom")
        return np.full(100, 0.5, dtype=np.float32)  # 0.1 s of "speech"


class FakeStream:
    """Stands in for sounddevice.OutputStream; the test pumps the callback."""

    def __init__(self, callback):
        self.callback = callback
        self.active = False

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        pass

    def pump(self, frames=200):
        out = np.zeros((frames, 1), dtype=np.float32)
        self.callback(out, frames, None, None)
        return out


class Harness:
    def __init__(self, tmp_path, engine, paragraphs):
        self.streams: list[FakeStream] = []
        self.positions: list[tuple[int, int]] = []
        self.states: list[str] = []
        self.errors: list[str] = []

        def factory(sr, **callbacks):
            def stream_factory(cb):
                stream = FakeStream(cb)
                self.streams.append(stream)
                return stream
            return AudioPlayer(sr, stream_factory=stream_factory, **callbacks)

        events = ReaderEvents(on_position=lambda p, s: self.positions.append((p, s)),
                              on_state=self.states.append, on_error=self.errors.append)
        self.ctl = ReaderController(AudioCache(tmp_path / "cache"), events, player_factory=factory)
        self.ctl.update_voice(sentence_pause=0.0, paragraph_pause=0.0)
        self.ctl.set_engine(engine)
        self.doc = Document(path=tmp_path / "x.txt", title="x", format="txt",
                            paragraphs=[Paragraph(t) for t in paragraphs])
        self.ctl.set_document(self.doc)

    def wait(self, predicate, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False

    def play_through(self, max_pumps=500):
        for _ in range(max_pumps):
            if self.ctl.status == "finished":
                return
            if self.streams:
                self.streams[-1].pump()
            time.sleep(0.005)


@pytest.fixture
def paragraphs():
    return ["Перший абзац. Друге речення.", "Другий абзац.", "Третій абзац — останній."]


def test_reads_all_segments_in_order(tmp_path, paragraphs):
    engine = FakeEngine()
    h = Harness(tmp_path, engine, paragraphs)
    h.ctl.play()
    h.play_through()
    assert h.ctl.status == "finished"
    assert engine.calls == ["Перший абзац. Друге речення.", "Другий абзац.", "Третій абзац — останній."]
    heard = [p for p in h.positions if p != (0, 0)]
    assert heard[-1] == (2, 0)
    assert "buffering" in h.states and "playing" in h.states
    h.ctl.shutdown()


def test_cached_audio_is_reused(tmp_path, paragraphs):
    engine = FakeEngine()
    h = Harness(tmp_path, engine, paragraphs)
    h.ctl.play()
    h.play_through()
    first_calls = len(engine.calls)
    h.ctl.seek(0)
    h.ctl.play()
    h.play_through()
    assert len(engine.calls) == first_calls  # second pass served from the cache
    h.ctl.shutdown()


def test_seek_and_navigation(tmp_path, paragraphs):
    h = Harness(tmp_path, FakeEngine(), paragraphs)
    h.ctl.seek(2)
    assert h.ctl.position == (2, 0)
    h.ctl.previous_paragraph()
    assert h.ctl.position == (1, 0)
    h.ctl.next_paragraph()
    h.ctl.next_paragraph()  # clamps at the last paragraph
    assert h.ctl.position == (2, 0)
    h.ctl.seek(-5)
    assert h.ctl.position == (0, 0)
    h.ctl.shutdown()


def test_pause_resume_keeps_position(tmp_path, paragraphs):
    h = Harness(tmp_path, FakeEngine(), paragraphs)
    h.ctl.play()
    assert h.wait(lambda: h.streams and h.ctl._player.queued_tags())
    h.streams[-1].pump(50)
    assert h.ctl.status == "playing"
    h.ctl.pause()
    assert h.ctl.status == "paused"
    silent = h.streams[-1].pump(50)
    assert not silent.any()  # nothing plays while paused
    pos = h.ctl.position
    h.ctl.play()
    assert h.ctl.position == pos
    assert h.streams[-1].pump(50).any()
    h.ctl.stop()
    assert h.ctl.status == "stopped" and h.ctl.position == (pos[0], 0)
    h.ctl.shutdown()


def test_synthesis_error_skips_segment_and_continues(tmp_path, paragraphs):
    engine = FakeEngine(fail_on="Другий")
    h = Harness(tmp_path, engine, paragraphs)
    h.ctl.play()
    h.play_through()
    assert h.ctl.status == "finished"
    assert len(h.errors) == 1
    assert engine.calls.count("Другий абзац.") == 2  # retried once
    assert (2, 0) in h.positions  # reading continued after the failure
    h.ctl.shutdown()


def test_lookahead_is_bounded(tmp_path):
    many = [f"Абзац номер {i}." for i in range(200)]
    engine = FakeEngine()
    h = Harness(tmp_path, engine, many)
    h.ctl.play()
    time.sleep(0.5)  # no pumping: playback does not advance
    from audiobook_reader.reader.controller import MAX_QUEUED_SEGMENTS
    assert len(engine.calls) <= MAX_QUEUED_SEGMENTS + 1
    h.ctl.shutdown()


def test_voice_change_regenerates_from_current_position(tmp_path, paragraphs):
    engine = FakeEngine()
    h = Harness(tmp_path, engine, paragraphs)
    h.ctl.seek(1)
    h.ctl.play()
    assert h.wait(lambda: len(engine.calls) >= 2)
    h.ctl.update_voice(voice="M1")
    assert h.wait(lambda: engine.calls.count("Другий абзац.") >= 2)
    h.ctl.shutdown()
