import pytest

from audiobook_reader.reader.duration import CHARS_PER_SECOND, ReadingTime, format_duration


def test_reading_time_scales_with_speed_and_counts_pauses():
    texts = ["Перше речення. Друге речення!", "Третій абзац."]
    estimate = ReadingTime(texts)
    chars = sum(map(len, texts))
    # One sentence pause inside the first paragraph, a paragraph pause after each paragraph.
    assert estimate.seconds(1.0, 0.2, 0.5) == pytest.approx(chars / CHARS_PER_SECOND + 0.2 + 2 * 0.5)
    assert estimate.seconds(2.0, 0.0, 0.0) == pytest.approx(chars / CHARS_PER_SECOND / 2)
    assert estimate.seconds(2.0, 0.2, 0.5) == pytest.approx(chars / CHARS_PER_SECOND / 2 + (0.2 + 1.0) / 2)


def test_remaining_time_from_paragraph():
    estimate = ReadingTime(["а" * 130, "б" * 260])
    assert estimate.seconds(1.0, 0, 0, start=1) == pytest.approx(20.0)
    assert estimate.seconds(1.0, 0, 0, start=2) == 0
    assert estimate.seconds(1.0, 0, 0, start=0) == pytest.approx(30.0)


@pytest.mark.parametrize("seconds,text", [
    (10, "< 1 хв"), (45 * 60, "45 хв"), (3600, "1 год"), (5 * 3600 + 20 * 60 + 10, "5 год 20 хв"),
    (2 * 3600 + 5 * 60, "2 год 5 хв"),
])
def test_format_duration(seconds, text):
    assert format_duration(seconds) == text
