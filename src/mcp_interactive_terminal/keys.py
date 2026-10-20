_KEYS = {
    "enter": "\r",
    "return": "\r",
    "tab": "\t",
    "backtab": "\x1b[Z",
    "esc": "\x1b",
    "escape": "\x1b",
    "space": " ",
    "backspace": "\x7f",
    "up": "\x1b[A",
    "down": "\x1b[B",
    "right": "\x1b[C",
    "left": "\x1b[D",
    "home": "\x1b[H",
    "end": "\x1b[F",
    "pageup": "\x1b[5~",
    "pagedown": "\x1b[6~",
    "insert": "\x1b[2~",
    "delete": "\x1b[3~",
    "f1": "\x1bOP",
    "f2": "\x1bOQ",
    "f3": "\x1bOR",
    "f4": "\x1bOS",
    "f5": "\x1b[15~",
    "f6": "\x1b[17~",
    "f7": "\x1b[18~",
    "f8": "\x1b[19~",
    "f9": "\x1b[20~",
    "f10": "\x1b[21~",
    "f11": "\x1b[23~",
    "f12": "\x1b[24~",
    "ctrl-space": "\x00",
    "ctrl-break": "\x03",
}

for _index, _letter in enumerate("abcdefghijklmnopqrstuvwxyz", start=1):
    _KEYS[f"ctrl-{_letter}"] = chr(_index)

_KEYS["ctrl-["] = "\x1b"
_KEYS["ctrl-\\"] = "\x1c"
_KEYS["ctrl-]"] = "\x1d"


def resolve_key(name: str) -> str:
    if not name:
        raise ValueError("Empty key name")
    if len(name) == 1:
        return name
    key = name.strip().lower()
    if key.startswith("text:"):
        return name.strip()[5:]
    if key in _KEYS:
        return _KEYS[key]
    if len(key) == 1:
        return key
    known = ", ".join(sorted(_KEYS))
    raise ValueError(f"Unknown key {name!r}. Known keys: {known}")


def resolve_keys(keys: list[str] | None) -> str:
    if not keys:
        return ""
    return "".join(resolve_key(key) for key in keys)


def known_keys() -> list[str]:
    return sorted(_KEYS)
