import pytest

from mcp_interactive_terminal.buffer import OutputBuffer


def test_append_and_read_incremental():
    buf = OutputBuffer(1000)
    buf.append("hello ")
    buf.append("world")
    text, cursor, dropped, truncated = buf.read(0)
    assert text == "hello world"
    assert cursor == 11
    assert dropped == 0
    assert truncated is False
    text, cursor, _, _ = buf.read(cursor)
    assert text == ""
    buf.append("!")
    text, _, _, _ = buf.read(11)
    assert text == "!"


def test_cursor_is_absolute_after_trimming():
    buf = OutputBuffer(5)
    buf.append("abcdefghij")
    assert buf.start == 5
    assert buf.end == 10
    text, cursor, dropped, _ = buf.read(0)
    assert text == "fghij"
    assert cursor == 10
    assert dropped == 5


def test_read_from_future_cursor_is_clamped():
    buf = OutputBuffer(100)
    buf.append("abc")
    text, cursor, _, _ = buf.read(999)
    assert text == ""
    assert cursor == 3


def test_truncation_keeps_head_and_tail_with_marker():
    buf = OutputBuffer(10_000)
    buf.append("A" * 500 + "B" * 500)
    text, _, _, truncated = buf.read(0, max_chars=200)
    assert truncated is True
    assert "characters omitted" in text
    assert text.startswith("A")
    assert text.endswith("B")
    assert len(text) < 300


def test_clear_resets_offsets():
    buf = OutputBuffer(100)
    buf.append("abc")
    buf.clear()
    assert buf.start == buf.end == 3
    assert buf.read(3)[0] == ""


@pytest.mark.parametrize("size,payload", [(5, "abcdefghij"), (1, "abc"), (100, "abc")])
def test_length_never_exceeds_max(size, payload):
    buf = OutputBuffer(size)
    buf.append(payload)
    assert buf.length <= size
