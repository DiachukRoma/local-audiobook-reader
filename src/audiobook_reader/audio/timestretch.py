"""Pitch-preserving tempo change (WSOLA) for speech.

Neural TTS models drop or slur syllables when asked to speak much faster than
their natural pace. Speech is therefore synthesized near natural speed and then
sped up here, like the "1.5×" control of a podcast player: every word is kept,
the voice pitch does not change.
"""

from __future__ import annotations

import numpy as np


def time_stretch(audio: np.ndarray, rate: float, sample_rate: int) -> np.ndarray:
    """Return ``audio`` played ``rate`` times faster (rate > 1) or slower (rate < 1)."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if audio.size == 0 or abs(rate - 1.0) < 0.01:
        return audio
    frame = int(0.030 * sample_rate)          # analysis/synthesis window
    hop_out = frame // 2                      # 50% overlap on output
    hop_in = hop_out * rate                   # advance in the input
    tolerance = int(0.010 * sample_rate)      # how far a frame may shift to stay in phase
    if audio.size < 2 * frame:
        return audio

    window = np.hanning(frame).astype(np.float32)
    pad = tolerance + frame
    x = np.concatenate([np.zeros(pad, np.float32), audio, np.zeros(pad + frame, np.float32)])
    frames = int((audio.size / rate) / hop_out) + 1
    out = np.zeros(frames * hop_out + frame, np.float32)
    norm = np.zeros_like(out)

    previous = pad  # input position of the previously copied frame
    for k in range(frames):
        nominal = pad + int(round(k * hop_in))
        if nominal + tolerance + frame > x.size:
            break
        if k == 0:
            position = nominal
        else:
            # The natural continuation of the previous frame; pick the input frame near
            # ``nominal`` that best matches it, so the waveform joins without phase jumps.
            template = x[previous + hop_out: previous + hop_out + frame]
            lo = max(nominal - tolerance, 0)
            search = x[lo: nominal + tolerance + frame]
            corr = np.correlate(search, template, mode="valid")
            position = lo + int(np.argmax(corr))
        start = k * hop_out
        out[start:start + frame] += x[position:position + frame] * window
        norm[start:start + frame] += window
        previous = position

    length = int(round(audio.size / rate))
    out, norm = out[:length], norm[:length]
    np.divide(out, norm, out=out, where=norm > 1e-3)
    return out
