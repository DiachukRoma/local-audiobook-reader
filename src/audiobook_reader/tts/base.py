"""Engine-independent TTS interface. Other engines can be added by implementing TTSEngine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


class TTSError(Exception):
    """Speech synthesis failed."""


class ModelMissingError(TTSError):
    """The model files are not present on disk."""


@dataclass(frozen=True)
class Voice:
    id: str
    label: str


class TTSEngine(ABC):
    #: Identifies engine + model version; part of the audio cache key.
    engine_id: str
    sample_rate: int
    languages: tuple[str, ...]
    speed_range: tuple[float, float] = (0.7, 2.0)
    #: Speed range the model itself produces cleanly. Speeds outside it are achieved by
    #: pitch-preserving time stretching of audio synthesized at the nearest natural speed.
    natural_speed_min: float = 0.7
    natural_speed_max: float = 2.0

    @abstractmethod
    def voices(self) -> list[Voice]:
        ...

    @abstractmethod
    def synthesize(self, text: str, lang: str, voice: str, speed: float) -> np.ndarray:
        """Return mono float32 audio at ``sample_rate`` for one short text segment."""
