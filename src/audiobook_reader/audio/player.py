"""Gapless streaming playback of a queue of audio segments via PortAudio (sounddevice).

Audio is only held for the segments that are queued (a bounded look-ahead), never
for the whole book.
"""

from __future__ import annotations

import collections
import logging
import threading
from collections.abc import Callable, Hashable
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class _Item:
    tag: Hashable
    audio: np.ndarray
    pos: int = 0
    started: bool = False


class AudioPlayer:
    """Plays queued mono float32 buffers back to back.

    Callbacks are invoked from the audio thread and must be cheap and thread-safe:
    ``on_start(tag)`` when a segment begins, ``on_finish(tag)`` when it ends and
    ``on_starved()`` when the queue runs empty while playing.
    """

    def __init__(self, sample_rate: int,
                 on_start: Callable[[Hashable], None] | None = None,
                 on_finish: Callable[[Hashable], None] | None = None,
                 on_starved: Callable[[], None] | None = None,
                 stream_factory: Callable | None = None):
        self.sample_rate = sample_rate
        self._on_start = on_start or (lambda tag: None)
        self._on_finish = on_finish or (lambda tag: None)
        self._on_starved = on_starved or (lambda: None)
        self._queue: collections.deque[_Item] = collections.deque()
        self._lock = threading.Lock()
        self._paused = True
        self._starved_reported = False
        self._stream = None
        self._stream_factory = stream_factory
        self.volume = 1.0

    # -- stream management -------------------------------------------------
    def _ensure_stream(self) -> None:
        if self._stream is not None:
            return
        if self._stream_factory is not None:
            self._stream = self._stream_factory(self._callback)
        else:
            import sounddevice as sd
            self._stream = sd.OutputStream(
                samplerate=self.sample_rate, channels=1, dtype="float32",
                callback=self._callback, latency="high")
        self._stream.start()

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # device may already be gone
                log.exception("Error while closing audio stream")

    # -- queue -------------------------------------------------------------
    def enqueue(self, tag: Hashable, audio: np.ndarray) -> None:
        with self._lock:
            self._queue.append(_Item(tag, np.ascontiguousarray(audio, dtype=np.float32)))
            self._starved_reported = False

    def clear(self) -> None:
        with self._lock:
            self._queue.clear()

    def queued_tags(self) -> list[Hashable]:
        with self._lock:
            return [item.tag for item in self._queue]

    def queued_seconds(self) -> float:
        with self._lock:
            samples = sum(len(item.audio) - item.pos for item in self._queue)
        return samples / self.sample_rate

    # -- transport ---------------------------------------------------------
    def play(self) -> None:
        self._ensure_stream()
        self._paused = False

    def pause(self) -> None:
        self._paused = True

    @property
    def paused(self) -> bool:
        return self._paused

    # -- audio thread --------------------------------------------------------
    def _callback(self, outdata, frames, _time, status) -> None:
        if status and status.output_underflow:
            log.debug("Audio output underflow")
        out = outdata[:, 0] if outdata.ndim == 2 else outdata
        out.fill(0)
        if self._paused:
            return
        events: list[tuple[str, Hashable]] = []
        written = 0
        starved = False
        with self._lock:
            while written < frames:
                if not self._queue:
                    starved = not self._starved_reported
                    self._starved_reported = True
                    break
                item = self._queue[0]
                if not item.started:
                    item.started = True
                    events.append(("start", item.tag))
                take = min(frames - written, len(item.audio) - item.pos)
                out[written:written + take] = item.audio[item.pos:item.pos + take] * self.volume
                item.pos += take
                written += take
                if item.pos >= len(item.audio):
                    self._queue.popleft()
                    events.append(("finish", item.tag))
        for kind, tag in events:
            (self._on_start if kind == "start" else self._on_finish)(tag)
        if starved:
            self._on_starved()
