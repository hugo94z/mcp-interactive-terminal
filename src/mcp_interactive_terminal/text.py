import re

_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_ESC = re.compile(r"\x1b[@-Z\\-_]")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_ansi(text: str) -> str:
    if not text:
        return ""
    text = _OSC.sub("", text)
    text = _CSI.sub("", text)
    return _ESC.sub("", text)


def to_plain_text(text: str) -> str:
    if not text:
        return ""
    text = strip_ansi(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _CTRL.sub("", text)


def truncate_middle(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    omitted = len(text) - limit
    marker = f"\n[... {omitted} characters omitted ...]\n"
    if len(marker) >= limit:
        return text[-limit:]
    budget = limit - len(marker)
    head = max(1, budget // 3)
    tail = max(0, budget - head)
    return text[:head] + marker + (text[-tail:] if tail else "")


def tail_lines(text: str, count: int) -> str:
    if count <= 0:
        return ""
    lines = text.splitlines()
    return "\n".join(lines[-count:])


def grep_lines(text: str, pattern: str) -> str:
    compiled = re.compile(pattern, re.IGNORECASE)
    return "\n".join(line for line in text.splitlines() if compiled.search(line))
