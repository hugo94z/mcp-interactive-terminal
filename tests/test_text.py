import pytest

from mcp_interactive_terminal.text import (
    grep_lines,
    strip_ansi,
    tail_lines,
    to_plain_text,
    truncate_middle,
)


def test_strip_ansi_removes_csi_and_osc():
    raw = "\x1b[1;31mred\x1b[0m \x1b]0;title\x07done"
    assert strip_ansi(raw) == "red done"


def test_to_plain_text_normalizes_newlines_and_controls():
    raw = "a\r\nb\rc\x00d\x08e"
    assert to_plain_text(raw) == "a\nb\ncde"


def test_strip_ansi_keeps_newlines():
    assert strip_ansi("a\r\nb") == "a\r\nb"


def test_truncate_middle_noop_when_short():
    assert truncate_middle("abc", 10) == "abc"


def test_truncate_middle_marks_omission():
    text = "x" * 5000
    result = truncate_middle(text, 200)
    assert "characters omitted" in result
    assert len(result) < 220


def test_truncate_middle_tiny_limit():
    assert truncate_middle("abcdef", 3) == "def"


def test_tail_and_grep():
    text = "alpha 1\nbeta 2\ngamma 3"
    assert tail_lines(text, 2) == "beta 2\ngamma 3"
    assert grep_lines(text, r"\d") == text
    assert grep_lines(text, "BETA") == "beta 2"


@pytest.mark.parametrize("value", ["", None])
def test_empty_inputs(value):
    assert to_plain_text(value or "") == ""
