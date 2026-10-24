"""Reading pipeline: segment text, synthesize ahead in a worker thread, play gaplessly.

The controller is GUI-independent. Events are delivered through ``ReaderEvents``
callbacks, which may be called from the worker or audio threads.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import NamedTuple

import numpy as np

from ..audio.cache import AudioCache, cache_key
from ..audio.player import AudioPlayer
from ..audio.timestretch import time_stretch
from ..document import Document
from ..document.chunking import split_segments
from ..tts.base import TTSEngine, TTSError
from ..tts.text_prep import prepare_for_tts

log = logging.getLogger(__name__)

LOOKAHEAD_SECONDS = 45.0
MAX_QUEUED_SEGMENTS = 16


class Tag(NamedTuple):
    epoch: int
    paragraph: int
    segment: int


@dataclass
class ReaderEvents:
    on_position: Callable[[int, int], None] = lambda p, s: None
    on_state: Callable[[str], None] = lambda state: None
    on_error: Callable[[str], None] = lambda message: None


@dataclass
class VoiceSettings:
    language: str = "uk"
    voice: str = "F1"
    speed: float = 1.0
    expand_numbers: bool = True
    bible_references: bool = True
    abbreviations: tuple[tuple[str, str, str], ...] = ()
    sentence_pause: float = 0.2
    paragraph_pause: float = 0.55


def trim_silence(audio: np.ndarray, sample_rate: int, threshold: float = 0.008) -> np.ndarray:
    """Remove leading/trailing near-silence, keeping a short natural margin."""
    if audio.size == 0:
        return audio
    loud = np.flatnonzero(np.abs(audio) > threshold)
    if loud.size == 0:
        return audio[:0]
    margin = int(0.04 * sample_rate)
    start = max(int(loud[0]) - margin, 0)
    end = min(int(loud[-1]) + margin, audio.size)
    return audio[start:end]


def model_speed(engine: TTSEngine, speed: float) -> float:
    """Speed passed to the TTS model; the rest of the tempo change is done by time stretching."""
    return round(min(max(speed, engine.natural_speed_min), engine.natural_speed_max), 2)


def segment_cache_key(engine: TTSEngine, prepared: str, voice: VoiceSettings) -> str:
    return cache_key(engine.engine_id, engine.sample_rate, voice.language, voice.voice,
                     model_speed(engine, voice.speed), prepared)


def synthesize_segment(engine: TTSEngine, cache: AudioCache, prepared: str, voice: VoiceSettings) -> np.ndarray:
    """Synthesize (or load from cache) one prepared segment at ``voice.speed``.

    The cache holds audio at the model's natural speed, so changing the playback
    speed reuses cached audio instead of synthesizing again.
    """
    natural = model_speed(engine, voice.speed)
    key = segment_cache_key(engine, prepared, voice)
    audio = cache.get(key)
    if audio is None:
        audio = trim_silence(engine.synthesize(prepared, voice.language, voice.voice, natural), engine.sample_rate)
        try:
            cache.put(key, audio, engine.sample_rate)
        except OSError:
            log.exception("Could not write audio cache")
    if abs(voice.speed - natural) > 0.005:
        audio = time_stretch(audio, voice.speed / natural, engine.sample_rate)
    return audio


def pause_seconds(voice: VoiceSettings, paragraph_end: bool) -> float:
    """Pauses shorten along with faster speech so the rhythm stays natural."""
    pause = voice.paragraph_pause if paragraph_end else voice.sentence_pause
    return pause / max(voice.speed, 1.0)


@dataclass
class _State:
    epoch: int = 0
    playing: bool = False  # user wants audio to play (not paused/stopped)
    position: tuple[int, int] = (0, 0)  # segment currently heard (or about to be)
    next_gen: tuple[int, int] = (0, 0)  # next segment to synthesize
    generated_to_end: bool = False
    last_tag: Tag | None = None
    status: str = "stopped"
    segments: dict[int, list[str]] = field(default_factory=dict)


class ReaderController:
    def __init__(self, cache: AudioCache, events: ReaderEvents | None = None,
                 player_factory: Callable[..., AudioPlayer] | None = None):
        self.cache = cache
        self.events = events or ReaderEvents()
        self.voice = VoiceSettings()
        self.document: Document | None = None
        self.engine: TTSEngine | None = None
        self._player_factory = player_factory or AudioPlayer
        self._player: AudioPlayer | None = None
        self._st = _State()
        self._cond = threading.Condition()
        self._shutdown = False
        self._worker = threading.Thread(target=self._run, name="tts-worker", daemon=True)
        self._worker.start()

    # ------------------------------------------------------------------ setup
    def set_engine(self, engine: TTSEngine) -> None:
        with self._cond:
            if self._player is not None:
                self._player.close()
                self._player = None
            self.engine = engine
            self._invalidate_locked()
            self._cond.notify_all()

    def set_cache(self, cache: AudioCache) -> None:
        with self._cond:
            self.cache = cache
            self._invalidate_locked()
            self._cond.notify_all()

    def set_document(self, document: Document, paragraph: int = 0, segment: int = 0) -> None:
        with self._cond:
            self.document = document
            self._st.segments.clear()
            self._st.playing = False
            if self._player:
                self._player.pause()
            paragraph = min(max(paragraph, 0), max(len(document.paragraphs) - 1, 0))
            segment = min(max(segment, 0), max(len(self._segments_locked(paragraph)) - 1, 0))
            self._st.position = (paragraph, segment)
            self._invalidate_locked()
            self._set_status_locked("stopped")
        self.events.on_position(paragraph, segment)

    def update_voice(self, **changes) -> None:
        """Change language/voice/speed/etc. Upcoming audio is regenerated from the current segment."""
        with self._cond:
            for key, value in changes.items():
                setattr(self.voice, key, value)
            self._invalidate_locked()
            self._cond.notify_all()

    # --------------------------------------------------------------- queries
    @property
    def position(self) -> tuple[int, int]:
        return self._st.position

    @property
    def status(self) -> str:
        return self._st.status

    def segments(self, paragraph: int) -> list[str]:
        with self._cond:
            return list(self._segments_locked(paragraph))

    # ------------------------------------------------------------- transport
    def play(self) -> None:
        with self._cond:
            if self.document is None or self.engine is None:
                return
            if self._st.status == "finished":
                self._st.position = (0, 0)
                self._invalidate_locked()
            self._st.playing = True
            player = self._ensure_player_locked()
            try:
                player.play()
            except Exception as exc:
                self._st.playing = False
                log.exception("Audio output failed")
                self._set_status_locked("stopped")
                self._cond.notify_all()
                self.events.on_error(f"Не вдалося відкрити аудіовихід: {exc}")
                return
            ready = bool(player.queued_tags())
            self._set_status_locked("playing" if ready else "buffering")
            self._cond.notify_all()

    def pause(self) -> None:
        with self._cond:
            self._st.playing = False
            if self._player:
                self._player.pause()
            if self._st.status in ("playing", "buffering"):
                self._set_status_locked("paused")

    def toggle(self) -> None:
        if self._st.playing:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        """Stop playback, drop buffered audio and rewind to the start of the current paragraph."""
        with self._cond:
            self._st.playing = False
            paragraph = self._st.position[0]
            self._st.position = (paragraph, 0)
            self._invalidate_locked()
            if self._player:
                self._player.close()
                self._player = None
            self._set_status_locked("stopped")
        self.events.on_position(paragraph, 0)

    def seek(self, paragraph: int, segment: int = 0) -> None:
        with self._cond:
            if self.document is None or not self.document.paragraphs:
                return
            paragraph = min(max(paragraph, 0), len(self.document.paragraphs) - 1)
            segment = min(max(segment, 0), max(len(self._segments_locked(paragraph)) - 1, 0))
            self._st.position = (paragraph, segment)
            self._invalidate_locked()
            if self._st.status == "finished":
                self._set_status_locked("stopped")
            if self._st.playing:
                self._set_status_locked("buffering")
            self._cond.notify_all()
        self.events.on_position(paragraph, segment)

    def next_paragraph(self) -> None:
        self.seek(self._st.position[0] + 1)

    def previous_paragraph(self) -> None:
        paragraph, segment = self._st.position
        # Like a music player: first press restarts the paragraph if we are inside it.
        self.seek(paragraph if segment > 0 else paragraph - 1)

    def replay_paragraph(self) -> None:
        self.seek(self._st.position[0])

    def shutdown(self) -> None:
        with self._cond:
            self._shutdown = True
            self._st.playing = False
            if self._player:
                self._player.close()
                self._player = None
            self._cond.notify_all()
        self._worker.join(timeout=5)

    # -------------------------------------------------------------- internals
    def _segments_locked(self, paragraph: int) -> list[str]:
        segs = self._st.segments.get(paragraph)
        if segs is None:
            text = self.document.paragraphs[paragraph].text if self.document else ""
            segs = split_segments(text) or [text]
            if len(self._st.segments) > 2000:
                self._st.segments.clear()
            self._st.segments[paragraph] = segs
        return segs

    def _advance_locked(self, pos: tuple[int, int]) -> tuple[int, int] | None:
        paragraph, segment = pos
        if segment + 1 < len(self._segments_locked(paragraph)):
            return paragraph, segment + 1
        if self.document and paragraph + 1 < len(self.document.paragraphs):
            return paragraph + 1, 0
        return None

    def _invalidate_locked(self) -> None:
        """Discard queued and in-flight audio; generation restarts at the current position."""
        self._st.epoch += 1
        self._st.next_gen = self._st.position
        self._st.generated_to_end = False
        self._st.last_tag = None
        if self._player:
            self._player.clear()

    def _set_status_locked(self, status: str) -> None:
        if status != self._st.status:
            self._st.status = status
            self.events.on_state(status)

    def _ensure_player_locked(self) -> AudioPlayer:
        if self._player is None:
            self._player = self._player_factory(
                self.engine.sample_rate, on_start=self._on_segment_start,
                on_finish=self._on_segment_finish, on_starved=self._on_starved)
        return self._player

    # Audio-thread callbacks -------------------------------------------------
    def _on_segment_start(self, tag: Tag) -> None:
        with self._cond:
            if tag.epoch != self._st.epoch:
                return
            self._st.position = (tag.paragraph, tag.segment)
            if self._st.playing:
                self._set_status_locked("playing")
            self._cond.notify_all()  # space freed in the look-ahead window
        self.events.on_position(tag.paragraph, tag.segment)

    def _on_segment_finish(self, tag: Tag) -> None:
        with self._cond:
            if tag.epoch == self._st.epoch and self._st.generated_to_end and tag == self._st.last_tag:
                self._st.playing = False
                if self._player:
                    self._player.pause()
                self._set_status_locked("finished")
            self._cond.notify_all()

    def _on_starved(self) -> None:
        with self._cond:
            if self._st.playing and not self._st.generated_to_end:
                self._set_status_locked("buffering")
            self._cond.notify_all()

    # Worker thread -----------------------------------------------------------
    def _needs_audio_locked(self) -> bool:
        if self.document is None or self.engine is None or self._st.generated_to_end:
            return False
        if self._player is None:
            # Pre-generate the first segments even before playback starts.
            return self._st.playing
        return (len(self._player.queued_tags()) < MAX_QUEUED_SEGMENTS
                and self._player.queued_seconds() < LOOKAHEAD_SECONDS)

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._shutdown and not self._needs_audio_locked():
                    self._cond.wait(timeout=1.0)
                if self._shutdown:
                    return
                epoch = self._st.epoch
                paragraph, segment = self._st.next_gen
                segments = self._segments_locked(paragraph)
                text = segments[segment] if segment < len(segments) else ""
                is_paragraph_end = segment + 1 >= len(segments)
                engine = self.engine
                voice = VoiceSettings(**vars(self.voice))

            audio = self._synthesize(engine, text, voice, epoch)

            with self._cond:
                if epoch != self._st.epoch or self._shutdown:
                    continue  # position or settings changed meanwhile: drop the result
                if audio is None:
                    audio = np.zeros(int(0.3 * engine.sample_rate), dtype=np.float32)
                pause = pause_seconds(voice, is_paragraph_end)
                audio = np.concatenate([audio, np.zeros(int(pause * engine.sample_rate), dtype=np.float32)])
                tag = Tag(epoch, paragraph, segment)
                player = self._ensure_player_locked()
                player.enqueue(tag, audio)
                self._st.last_tag = tag
                following = self._advance_locked((paragraph, segment))
                if following is None:
                    self._st.generated_to_end = True
                else:
                    self._st.next_gen = following
                if self._st.playing and player.paused:
                    player.play()

    def _synthesize(self, engine: TTSEngine, text: str, voice: VoiceSettings, epoch: int) -> np.ndarray | None:
        prepared = prepare_for_tts(text, voice.language, voice.expand_numbers, voice.bible_references,
                                   voice.abbreviations)
        last_error: Exception | None = None
        for _attempt in range(2):
            if epoch != self._st.epoch:
                return None
            try:
                return synthesize_segment(engine, self.cache, prepared, voice)
            except TTSError as exc:
                last_error = exc
            except Exception as exc:  # unexpected engine failure: keep the reader alive
                log.exception("Unexpected synthesis failure")
                last_error = exc
        log.warning("Segment skipped after synthesis failure (%d chars)", len(text))
        self.events.on_error(f"Не вдалося озвучити фрагмент, його пропущено. {last_error}")
        return None
