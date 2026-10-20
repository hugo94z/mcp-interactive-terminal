from collections import deque


class OutputBuffer:
    def __init__(self, max_chars: int = 500_000) -> None:
        self.max_chars = max(1, int(max_chars))
        self._parts: deque[tuple[int, str]] = deque()
        self._length = 0
        self.start = 0
        self.end = 0

    def append(self, text: str) -> None:
        if not text:
            return
        self._parts.append((self.end, text))
        self._length += len(text)
        self.end += len(text)
        while self._length > self.max_chars and self._parts:
            offset, chunk = self._parts[0]
            overflow = self._length - self.max_chars
            if len(chunk) <= overflow:
                self._parts.popleft()
                self._length -= len(chunk)
                self.start = offset + len(chunk)
            else:
                self._parts[0] = (offset + overflow, chunk[overflow:])
                self._length -= overflow
                self.start = offset + overflow

    def read(self, since: int | None, max_chars: int = 20000) -> tuple[str, int, int, bool]:
        if since is None:
            since = self.start
        since = max(0, min(int(since), self.end))
        dropped = 0
        if since < self.start:
            dropped = self.start - since
            since = self.start
        chunks = []
        for offset, chunk in self._parts:
            chunk_end = offset + len(chunk)
            if chunk_end <= since:
                continue
            chunks.append(chunk if offset >= since else chunk[since - offset:])
        text = "".join(chunks)
        truncated = len(text) > max_chars > 0
        if truncated:
            head = max(1, max_chars // 3)
            tail = max(0, max_chars - head)
            marker = f"\n[... {len(text) - max_chars} characters omitted ...]\n"
            text = text[:head] + marker + (text[-tail:] if tail else "")
        return text, self.end, dropped, truncated

    def text(self) -> str:
        return "".join(chunk for _, chunk in self._parts)

    def clear(self) -> None:
        self._parts.clear()
        self._length = 0
        self.start = self.end

    @property
    def length(self) -> int:
        return self._length
