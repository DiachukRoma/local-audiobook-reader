"""Estimated listening time of a document at a given speed."""

from __future__ import annotations

import re
from itertools import accumulate

# Supertonic 3 at 1× speaks about 13 characters per second (measured on Ukrainian and Russian text,
# silence trimmed); faster speeds are time-stretched, so the rate scales with the speed.
CHARS_PER_SECOND = 13.0

_SENTENCE_END = re.compile(r"[.!?…]+[»\"”)]*\s+")


class ReadingTime:
    """Prefix sums over paragraphs, so the time from any paragraph to the end is computed instantly."""

    def __init__(self, texts: list[str]):
        self._chars = [0, *accumulate(len(t) for t in texts)]
        # Sentence pauses inside paragraphs; the last sentence ends with a paragraph pause.
        self._sentences = [0, *accumulate(len(_SENTENCE_END.findall(t.strip())) for t in texts)]
        self.paragraphs = len(texts)

    def seconds(self, speed: float, sentence_pause: float, paragraph_pause: float, start: int = 0) -> float:
        """Seconds to read from paragraph ``start`` to the end. Pauses shorten with faster speech
        as in playback (see controller.pause_seconds)."""
        start = min(max(start, 0), self.paragraphs)
        chars = self._chars[-1] - self._chars[start]
        sentences = self._sentences[-1] - self._sentences[start]
        paragraphs = self.paragraphs - start
        speed = max(speed, 0.1)
        pauses = (sentences * sentence_pause + paragraphs * paragraph_pause) / max(speed, 1.0)
        return chars / (CHARS_PER_SECOND * speed) + pauses


def format_duration(seconds: float) -> str:
    """«5 год 20 хв», «45 хв», «< 1 хв»."""
    minutes = int(round(seconds / 60))
    if minutes < 1:
        return "< 1 хв"
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f"{minutes} хв"
    return f"{hours} год {minutes} хв" if minutes else f"{hours} год"
