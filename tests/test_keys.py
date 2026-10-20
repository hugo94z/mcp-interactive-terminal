import pytest

from mcp_interactive_terminal.keys import known_keys, resolve_key, resolve_keys


def test_named_keys():
    assert resolve_key("enter") == "\r"
    assert resolve_key("ctrl-c") == "\x03"
    assert resolve_key("up") == "\x1b[A"
    assert resolve_key("F5") == "\x1b[15~"
    assert resolve_key("tab") == "\t"


def test_text_prefix_is_literal():
    assert resolve_key("text:ctrl-c") == "ctrl-c"
    assert resolve_key("text:hello world") == "hello world"


def test_single_character_passthrough():
    assert resolve_key("a") == "a"
    assert resolve_key(" ") == " "


def test_unknown_key_lists_known_keys():
    with pytest.raises(ValueError) as excinfo:
        resolve_key("super-key")
    assert "Unknown key" in str(excinfo.value)
    assert "ctrl-c" in str(excinfo.value)


def test_resolve_keys_concatenates():
    assert resolve_keys(["text:ab", "enter"]) == "ab\r"
    assert resolve_keys([]) == ""
    assert resolve_keys(None) == ""


def test_known_keys_is_stable():
    keys = known_keys()
    assert keys == sorted(keys)
    assert "ctrl-z" in keys and "f12" in keys
