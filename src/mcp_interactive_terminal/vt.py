import pyte


class VirtualScreen:
    def __init__(self, cols: int, rows: int) -> None:
        self.cols = max(2, int(cols))
        self.rows = max(2, int(rows))
        self.error: str | None = None
        self._screen = pyte.Screen(self.cols, self.rows)
        self._stream = pyte.Stream(self._screen)

    def feed(self, text: str) -> None:
        try:
            self._stream.feed(text)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"

    def resize(self, cols: int, rows: int) -> None:
        self.cols = max(2, int(cols))
        self.rows = max(2, int(rows))
        try:
            self._screen.resize(rows=self.rows, columns=self.cols)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"

    def render(self) -> str:
        lines = [line.rstrip() for line in self._screen.display]
        while lines and not lines[-1]:
            lines.pop()
        while lines and not lines[0]:
            lines.pop(0)
        return "\n".join(lines)

    @property
    def cursor(self) -> dict[str, int]:
        return {"x": self._screen.cursor.x + 1, "y": self._screen.cursor.y + 1}

    @property
    def size(self) -> dict[str, int]:
        return {"cols": self.cols, "rows": self.rows}
