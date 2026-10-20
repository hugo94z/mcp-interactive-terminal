import os
import re
import threading
import time

from . import backend
from .buffer import OutputBuffer
from .keys import resolve_keys
from .text import grep_lines, tail_lines, to_plain_text, truncate_middle
from .vt import VirtualScreen

_INIT_PS = (
    "$OutputEncoding = [Console]::OutputEncoding = "
    "New-Object System.Text.UTF8Encoding $false"
)

SHELLS = {
    "powershell": ["powershell.exe", "-NoLogo", "-NoProfile", "-NoExit", "-Command", _INIT_PS],
    "pwsh": ["pwsh.exe", "-NoLogo", "-NoProfile", "-NoExit", "-Command", _INIT_PS],
    "cmd": ["cmd.exe", "/d", "/k", "chcp 65001>nul"],
}

ONE_SHOT = {
    "powershell": ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"],
    "pwsh": ["pwsh.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"],
    "cmd": ["cmd.exe", "/d", "/s", "/c"],
}

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
_MAX_SESSIONS = 16
_MAX_BUFFER = 500_000


class SessionError(RuntimeError):
    pass


def resolve_shell(shell: str | None, args: list[str] | None = None) -> list[str]:
    key = (shell or "powershell").strip()
    lowered = key.lower()
    if lowered in SHELLS:
        if lowered == "pwsh" and backend.which_executable("pwsh.exe") is None:
            raise SessionError("pwsh is not installed. Use shell='powershell' or install PowerShell 7.")
        return SHELLS[lowered] + list(args or [])
    if os.path.isabs(key) and os.path.exists(key):
        return [key] + list(args or [])
    if backend.which_executable(key):
        return [key] + list(args or [])
    raise SessionError(
        f"Unknown shell {shell!r}. Use 'powershell', 'pwsh', 'cmd' or an absolute path to an executable."
    )


def build_one_shot(shell: str | None, command: str) -> list[str]:
    key = (shell or "powershell").strip().lower()
    if key not in ONE_SHOT:
        raise SessionError("terminal_exec supports shell='powershell', 'pwsh' or 'cmd' only.")
    if key == "pwsh" and backend.which_executable("pwsh.exe") is None:
        raise SessionError("pwsh is not installed. Use shell='powershell'.")
    if key == "cmd":
        argv = list(ONE_SHOT[key])
        return argv + [f"chcp 65001>nul & {command}"]
    argv = list(ONE_SHOT[key])
    wrapped = (
        "$OutputEncoding = [Console]::OutputEncoding = "
        f"New-Object System.Text.UTF8Encoding $false; {command}; exit $LASTEXITCODE"
    )
    return argv + [wrapped]


def _strip_echo(text: str, target: str) -> str:
    target = target.strip()
    if not target:
        return text
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == target:
            continue
        index = stripped.find(target)
        if index != -1 and "> " in stripped[: index + 1]:
            continue
        marker = stripped.rfind("> ")
        if marker != -1:
            tail = stripped[marker + 2:].strip()
            if len(tail) >= 4 and target.startswith(tail):
                continue
        kept.append(line)
    return "\n".join(kept)


class TerminalSession:
    def __init__(self, name: str, proc, shell: str, cwd: str | None,
                 cols: int = 120, rows: int = 30, max_buffer: int = _MAX_BUFFER) -> None:
        self.name = name
        self.proc = proc
        self.shell = shell
        self.cwd = cwd
        self.cols = max(2, int(cols))
        self.rows = max(2, int(rows))
        self.buffer = OutputBuffer(max_buffer)
        self.vt = VirtualScreen(self.cols, self.rows)
        self.running = True
        self.exit_code: int | None = None
        self.started_at = time.time()
        self.last_activity = time.monotonic()
        self.last_input = ""
        self._match_cursor = 0
        self._last_read_cursor = 0
        self._revision = 0
        self._cond = threading.Condition(threading.RLock())
        self._reader = threading.Thread(target=self._read_loop, name=f"pty-{name}", daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        while True:
            try:
                data = self.proc.read(8192)
            except (EOFError, OSError, ValueError):
                break
            except Exception:
                break
            if not data:
                time.sleep(0.01)
                continue
            with self._cond:
                self.buffer.append(data)
                self.vt.feed(data)
                self.last_activity = time.monotonic()
                self._revision += 1
                self._cond.notify_all()
        try:
            self.proc.isalive()
        except Exception:
            pass
        exit_code = None
        try:
            exit_code = self.proc.exitstatus
        except Exception:
            pass
        with self._cond:
            self.running = False
            self.exit_code = exit_code
            self._cond.notify_all()

    def write(self, payload: str) -> None:
        if not payload:
            raise SessionError("Nothing to send")
        with self._cond:
            if not self.running:
                raise SessionError(f"Session {self.name!r} has exited (exit code: {self.exit_code})")
            self._match_cursor = self.buffer.end
            if "\r" in payload or "\n" in payload:
                for line in payload.replace("\r", "\n").split("\n"):
                    if line.strip():
                        self.last_input = line.strip()
            try:
                self.proc.write(payload)
            except Exception as exc:
                raise SessionError(f"Write failed on {self.name!r}: {exc}") from exc
            self.last_activity = time.monotonic()
            self._revision += 1

    def send(self, text: str | None = None, keys: list[str] | None = None,
             enter: bool = False, repeat: int = 1) -> str:
        if repeat < 1 or repeat > 100:
            raise SessionError("repeat must be between 1 and 100")
        payload = (text or "") + resolve_keys(keys) + ("\r" if enter else "")
        if not payload:
            raise SessionError("Nothing to send: provide text, keys, or enter=true")
        payload = payload * repeat
        self.write(payload)
        return payload

    def read(self, since: int | None = None, max_chars: int = 20000, grep: str | None = None,
             tail: int | None = None, strip_ansi: bool = True) -> dict:
        with self._cond:
            cursor_in = self._last_read_cursor if since is None else int(since)
            raw, cursor, dropped, truncated = self.buffer.read(cursor_in, 200_000)
            if since is None:
                self._last_read_cursor = cursor
            text = to_plain_text(raw) if strip_ansi else raw
            if grep:
                try:
                    text = grep_lines(text, grep)
                except re.error as exc:
                    raise SessionError(f"Invalid grep regex: {exc}") from exc
            if tail and tail > 0:
                text = tail_lines(text, tail)
            limited = truncate_middle(text, max_chars) if max_chars > 0 else text
            return {
                "session_id": self.name,
                "text": limited,
                "cursor": cursor,
                "dropped": dropped,
                "truncated": truncated or len(limited) < len(text),
                "total_chars": self.buffer.end,
                "running": self.running,
                "exit_code": self.exit_code,
            }

    def _haystack(self, ignore_echo: bool) -> str:
        screen = self.vt.render()
        raw, _, _, _ = self.buffer.read(self._match_cursor, 200_000)
        plain = to_plain_text(raw)
        complete = plain.rsplit("\n", 1)[0] if "\n" in plain else ""
        text = screen + "\n" + complete
        if ignore_echo:
            text = _strip_echo(text, self.last_input)
        return text

    def wait(self, until: str | None = None, quiet_ms: int = 0,
             timeout_ms: int = 30000, ignore_echo: bool = True) -> dict:
        if not until and quiet_ms <= 0:
            raise SessionError("Provide until=<regex>, quiet_ms>0, or both")
        pattern = None
        if until:
            try:
                pattern = re.compile(until, re.IGNORECASE)
            except re.error as exc:
                raise SessionError(f"Invalid until regex: {exc}") from exc
        deadline = time.monotonic() + max(0.01, timeout_ms / 1000.0)
        last_revision = self._revision
        seen_output = False
        result = {"session_id": self.name, "reason": "timeout", "matched": False}
        with self._cond:
            checked_once = False
            while True:
                now = time.monotonic()
                new_output = self._revision != last_revision
                if new_output or not checked_once:
                    checked_once = True
                    if new_output:
                        last_revision = self._revision
                        seen_output = True
                    if pattern is not None and pattern.search(self._haystack(ignore_echo)):
                        result.update(reason="matched", matched=True)
                        break
                if not self.running:
                    result.update(reason="exited", matched=False)
                    break
                idle_ms = (now - self.last_activity) * 1000.0
                threshold = quiet_ms if seen_output else max(quiet_ms, 1500)
                if quiet_ms > 0 and idle_ms >= threshold and self.vt.render():
                    result.update(reason="quiet", matched=False)
                    break
                remaining = deadline - now
                if remaining <= 0:
                    result.update(reason="timeout", matched=False)
                    break
                self._cond.wait(min(0.2, remaining))
            result.update(
                running=self.running,
                exit_code=self.exit_code,
                screen=self.vt.render(),
            )
        return result

    def screen(self, max_chars: int = 20000) -> dict:
        with self._cond:
            text = truncate_middle(self.vt.render(), max_chars) if max_chars > 0 else self.vt.render()
            return {
                "session_id": self.name,
                "text": text,
                "cursor": self.vt.cursor,
                "cols": self.cols,
                "rows": self.rows,
                "running": self.running,
                "exit_code": self.exit_code,
                "vt_error": self.vt.error,
            }

    def interrupt(self, force: bool = False) -> dict:
        if not self.running:
            return {"session_id": self.name, "sent": False, "running": False, "killed": []}
        try:
            self.write("\x03")
        except SessionError:
            return {"session_id": self.name, "sent": False, "running": self.running, "killed": []}
        pid = self.proc.pid
        if force:
            time.sleep(0.05)
        else:
            time.sleep(0.5)
        killed = backend.children_of(pid) if pid else []
        if killed:
            backend.kill_children(pid)
            time.sleep(0.1)
        return {"session_id": self.name, "sent": True, "running": self.running, "killed": killed}

    def resize(self, cols: int, rows: int) -> dict:
        if cols < 2 or rows < 2 or cols > 1000 or rows > 500:
            raise SessionError("cols must be 2..1000 and rows 2..500")
        with self._cond:
            try:
                self.proc.setwinsize(int(rows), int(cols))
            except Exception as exc:
                raise SessionError(f"Resize failed: {exc}") from exc
            self.vt.resize(int(cols), int(rows))
            self.cols = int(cols)
            self.rows = int(rows)
            result = {"session_id": self.name, "cols": self.cols, "rows": self.rows}
        time.sleep(0.15)
        return result

    def stop(self, force: bool = False) -> None:
        pid = self.proc.pid
        try:
            if self.proc.isalive():
                try:
                    self.proc.write("\x03")
                except Exception:
                    pass
                time.sleep(0.15)
                if self.proc.isalive():
                    self.proc.terminate(force=True)
        except Exception:
            pass
        if force:
            backend.kill_tree(pid)
        try:
            self.proc.close(force=True)
        except Exception:
            pass
        with self._cond:
            self.running = False
            self._cond.notify_all()

    def info(self) -> dict:
        with self._cond:
            return {
                "session_id": self.name,
                "shell": self.shell,
                "pid": self.proc.pid,
                "cwd": self.cwd,
                "cols": self.cols,
                "rows": self.rows,
                "running": self.running,
                "exit_code": self.exit_code,
                "idle_ms": int((time.monotonic() - self.last_activity) * 1000),
                "buffer_chars": self.buffer.length,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.started_at)),
                "vt_error": self.vt.error,
            }


class TerminalManager:
    def __init__(self, max_sessions: int = _MAX_SESSIONS, max_buffer: int = _MAX_BUFFER) -> None:
        self._sessions: dict[str, TerminalSession] = {}
        self._lock = threading.RLock()
        self.max_sessions = max(1, int(max_sessions))
        self.max_buffer = max(10_000, int(max_buffer))

    def _next_name(self) -> str:
        index = 1
        while f"t{index}" in self._sessions:
            index += 1
        return f"t{index}"

    def _resolve_cwd(self, cwd: str | None) -> str:
        target = os.path.abspath(os.path.expanduser(cwd)) if cwd else os.getcwd()
        if not os.path.isdir(target):
            raise SessionError(f"Working directory does not exist: {target}")
        return target

    def start(self, shell: str = "powershell", cwd: str | None = None, env: dict | None = None,
              cols: int = 120, rows: int = 30, name: str | None = None,
              replace: bool = False, args: list[str] | None = None) -> TerminalSession:
        if cols < 2 or rows < 2 or cols > 1000 or rows > 500:
            raise SessionError("cols must be 2..1000 and rows must be 2..500")
        argv = resolve_shell(shell, args)
        target_cwd = self._resolve_cwd(cwd)
        full_env = dict(os.environ)
        for key, value in (env or {}).items():
            full_env[str(key)] = str(value)
        with self._lock:
            session_name = (name or self._next_name()).strip()
            if not _NAME_RE.match(session_name):
                raise SessionError("session name must match [A-Za-z0-9._-]{1,40}")
            if session_name in self._sessions:
                if not replace:
                    raise SessionError(
                        f"Session {session_name!r} already exists. Use replace=true or another name."
                    )
                self._sessions.pop(session_name).stop(force=True)
            if len(self._sessions) >= self.max_sessions:
                raise SessionError(
                    f"Too many sessions ({self.max_sessions}). Stop one with terminal_stop first."
                )
            proc = backend.spawn(argv, cwd=target_cwd, env=full_env, cols=cols, rows=rows)
            session = TerminalSession(
                session_name,
                proc,
                shell=shell,
                cwd=target_cwd,
                cols=cols,
                rows=rows,
                max_buffer=self.max_buffer,
            )
            self._sessions[session_name] = session
            return session

    def get(self, name: str) -> TerminalSession:
        with self._lock:
            session = self._sessions.get(name)
            if session is None:
                known = ", ".join(sorted(self._sessions)) or "none"
                raise SessionError(f"Unknown session {name!r}. Active sessions: {known}")
            return session

    def list(self) -> list[dict]:
        with self._lock:
            return [session.info() for session in self._sessions.values()]

    def stop(self, name: str, force: bool = False) -> None:
        with self._lock:
            session = self._sessions.pop(name, None)
        if session is None:
            known = ", ".join(sorted(self._sessions)) or "none"
            raise SessionError(f"Unknown session {name!r}. Active sessions: {known}")
        session.stop(force=force)

    def stop_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            try:
                session.stop(force=True)
            except Exception:
                pass

    def execute(self, command: str, shell: str = "powershell", cwd: str | None = None,
                env: dict | None = None, timeout_ms: int = 120000,
                max_chars: int = 20000) -> dict:
        if not command or not command.strip():
            raise SessionError("command is empty")
        argv = build_one_shot(shell, command)
        target_cwd = self._resolve_cwd(cwd)
        full_env = dict(os.environ)
        for key, value in (env or {}).items():
            full_env[str(key)] = str(value)
        started = time.monotonic()
        proc = backend.spawn(argv, cwd=target_cwd, env=full_env, cols=200, rows=50)
        session = TerminalSession(
            "exec", proc, shell=shell, cwd=target_cwd, cols=200, rows=50, max_buffer=2_000_000
        )
        deadline = started + max(1.0, timeout_ms / 1000.0)
        while session.running and time.monotonic() < deadline:
            time.sleep(0.05)
        timed_out = session.running
        if timed_out:
            session.stop(force=True)
        text = to_plain_text(session.buffer.text())
        session.stop(force=True)
        limited = truncate_middle(text, max_chars) if max_chars > 0 else text
        return {
            "command": command,
            "shell": shell,
            "cwd": target_cwd,
            "output": limited,
            "exit_code": None if timed_out else session.exit_code,
            "timed_out": timed_out,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "truncated": len(limited) < len(text),
        }
