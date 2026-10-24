import json
import os
import time

import numpy as np
import soundfile as sf

from audiobook_reader.audio.cache import AudioCache, cache_key
from audiobook_reader.storage.settings import ProgressStore, Progress, Settings, document_fingerprint
from audiobook_reader.tts.text_prep import prepare_for_tts


# ---------------------------------------------------------------- text prep
def test_years_are_spelled_out_with_case_uk():
    out = prepare_for_tts("У 1991 році, а 2026 року — 1990-х.", "uk")
    assert out == "У тисяча дев'ятсот дев'яносто першому році, а дві тисячі двадцять шостого року — тисяча дев'ятсот дев'яностих."


def test_years_are_spelled_out_with_case_ru():
    out = prepare_for_tts("В 1991 году; 1812 г.; в 2003 г.", "ru")
    assert out == ("В тысяча девятьсот девяносто первом году; тысяча восемьсот двенадцатого года; "
                   "в две тысячи третьем году")


def test_numbers_percent_decimals_and_abbreviations():
    assert prepare_for_tts("52 учасники, 15%, 3,5 кг, 10 000 книжок, див. с. 5, і т. д.", "uk") == \
        "п'ятдесят два учасники, п'ятнадцять відсотків, три кома п'ять кг, десять тисяч книжок, дивіться с. п'ять, і так далі"
    assert prepare_for_tts("21 %, 5-го мая, т. е. см. выше", "ru") == \
        "двадцать один процент, пятого мая, то есть смотри выше"


def test_text_prep_keeps_punctuation_and_unsupported_chars_mapped():
    out = prepare_for_tts("Сімʼя „на ґанку“ [примітка] — так!", "uk", expand=False)
    assert out == "Сім'я «на ґанку» (примітка) — так!"


def test_expand_disabled_leaves_digits():
    assert prepare_for_tts("У 1991 році.", "uk", expand=False) == "У 1991 році."


# ---------------------------------------------------------------- storage
def test_settings_roundtrip_and_validation(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings(voice="M2", speed=1.3, language="ru")
    s.add_recent("/a.pdf")
    s.add_recent("/b.epub")
    s.add_recent("/a.pdf")
    s.save(path)
    loaded = Settings.load(path)
    assert loaded.voice == "M2" and loaded.speed == 1.3 and loaded.language == "ru"
    assert loaded.recent_files == ["/a.pdf", "/b.epub"]
    path.write_text(json.dumps({"speed": 99, "language": "xx", "unknown": 1}), encoding="utf-8")
    loaded = Settings.load(path)
    assert loaded.speed == 3.0 and loaded.language == "auto"


def test_corrupt_settings_fall_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert Settings.load(path) == Settings()


def test_reading_progress_persistence(tmp_path):
    book = tmp_path / "book.txt"
    book.write_text("Абзац.\n\nЩе абзац.", encoding="utf-8")
    fp = document_fingerprint(book)
    store = ProgressStore(tmp_path / "progress.json")
    assert store.get(fp) is None
    store.set(fp, Progress(paragraph=7, segment=2, language="uk", voice="F3", paragraph_count=10))
    reopened = ProgressStore(tmp_path / "progress.json")
    got = reopened.get(fp)
    assert (got.paragraph, got.segment, got.language, got.voice) == (7, 2, "uk", "F3")
    # Progress file must not contain the book text.
    assert "Абзац" not in (tmp_path / "progress.json").read_text(encoding="utf-8")
    # Moving/renaming the file keeps the same fingerprint.
    moved = tmp_path / "renamed.txt"
    book.rename(moved)
    assert document_fingerprint(moved) == fp


# ---------------------------------------------------------------- cache
def test_cache_put_get_and_decode(tmp_path):
    cache = AudioCache(tmp_path / "cache")
    audio = (0.5 * np.sin(np.linspace(0, 200, 44100))).astype(np.float32)
    key = cache_key("engine", "uk", "F1", 1.0, "текст")
    assert cache.get(key) is None
    cache.put(key, audio, 44100)
    got = cache.get(key)
    assert got is not None and got.shape == audio.shape
    assert np.max(np.abs(got - audio)) < 1e-3  # 16-bit FLAC
    files = list((tmp_path / "cache").glob("*/*.flac"))
    assert len(files) == 1
    info = sf.info(files[0])
    assert info.samplerate == 44100 and info.format == "FLAC"
    assert cache_key("engine", "uk", "F1", 1.0, "текст") != cache_key("engine", "uk", "F2", 1.0, "текст")


def test_cache_lru_trim_and_clear(tmp_path):
    cache = AudioCache(tmp_path / "cache", max_bytes=1)
    noise = np.random.default_rng(0).uniform(-0.5, 0.5, 44100).astype(np.float32)
    keys = [cache_key(i) for i in range(3)]
    for i, key in enumerate(keys):
        cache.put(key, noise, 44100)
        old = time.time() - 100 + i  # keys[0] oldest
        os.utime(cache._path(key), (old, old))
    one = cache._path(keys[2]).stat().st_size
    cache.max_bytes = one + 10
    cache.trim()
    assert cache.get(keys[0]) is None and cache.get(keys[1]) is None
    assert cache.get(keys[2]) is not None
    cache.clear()
    assert cache.size_bytes() == 0


def test_corrupt_cache_entry_is_discarded(tmp_path):
    cache = AudioCache(tmp_path / "cache")
    key = cache_key("x")
    path = cache._path(key)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not audio")
    assert cache.get(key) is None
    assert not path.exists()
