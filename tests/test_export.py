import shutil
import threading

import pytest
import soundfile as sf

from audiobook_reader.audio.cache import AudioCache
from audiobook_reader.document import Document, Paragraph
from audiobook_reader.reader.controller import VoiceSettings
from audiobook_reader.reader.export import ExportCancelled, export_audio
from test_controller import FakeEngine


def _doc(tmp_path, n=5):
    return Document(path=tmp_path / "b.txt", title="b", format="txt",
                    paragraphs=[Paragraph(f"Абзац номер {i}. Друге речення.") for i in range(n)])


@pytest.mark.parametrize("suffix", [".wav", ".flac"])
def test_export_streams_to_file(tmp_path, suffix):
    progress = []
    out = export_audio(_doc(tmp_path), 1, 4, tmp_path / f"out{suffix}", FakeEngine(), AudioCache(tmp_path / "c"),
                       VoiceSettings(sentence_pause=0, paragraph_pause=0.1), progress=lambda d, t: progress.append((d, t)))
    info = sf.info(out)
    assert info.samplerate == 1000 and info.frames == 3 * (100 + 100)
    assert progress[-1] == (3, 3)


@pytest.mark.skipif(shutil.which("afconvert") is None, reason="afconvert not available")
def test_export_m4a_with_afconvert(tmp_path):
    engine = FakeEngine()
    engine.sample_rate = 44100
    out = export_audio(_doc(tmp_path, 2), 0, 2, tmp_path / "out.m4a", engine, AudioCache(tmp_path / "c"), VoiceSettings())
    assert out.exists() and out.stat().st_size > 0
    assert not (tmp_path / "out.part.wav").exists()


def test_export_cancel_removes_partial_file(tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ExportCancelled):
        export_audio(_doc(tmp_path), 0, 5, tmp_path / "out.wav", FakeEngine(), AudioCache(tmp_path / "c"),
                     VoiceSettings(), cancel=cancel)
    assert not (tmp_path / "out.wav").exists()
