import atexit
import logging
import os
import sys

import anyio
from mcp.server import MCPServer

from . import __version__
from .sessions import SessionError, TerminalManager

INSTRUCTIONS = """
Interactive terminal server. It gives you real PTY sessions (Windows ConPTY) running
PowerShell, PowerShell 7 (pwsh), CMD, or any executable.

Typical flow:
1. terminal_start(shell="powershell", cwd="C:/work") -> session_id + first screen.
2. terminal_send(session_id, text="npm install", enter=True).
3. terminal_wait(session_id, until="ready in|Done|error", timeout_ms=120000) or quiet_ms.
4. terminal_screen(session_id) to see the authoritative rendered screen (best for prompts and TUIs).
5. terminal_read(session_id) for raw incremental output (cursor based, no duplicates).

Guidelines:
- Prefer terminal_screen over terminal_read when the shell is PowerShell: PSReadLine repaints
  the line and raw output contains cursor movements.
- Never poll in a loop: terminal_wait blocks until a regex matches, output goes quiet, or timeout.
- A session stays alive between calls. Stop it with terminal_stop when finished.
- terminal_exec is the one-shot shortcut (command -> output + exit code) when no interaction is needed.
- Commands run with the privileges of the user running the MCP server. There is no sandbox.
""".strip()

mcp = MCPServer(
    name="interactive-terminal",
    version=__version__,
    instructions=INSTRUCTIONS,
)

_manager: TerminalManager | None = None


def get_manager() -> TerminalManager:
    global _manager
    if _manager is None:
        _manager = TerminalManager()
        atexit.register(_manager.stop_all)
    return _manager


@mcp.tool()
async def terminal_start(
    shell: str = "powershell",
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    cols: int = 120,
    rows: int = 30,
    name: str | None = None,
    replace: bool = False,
    args: list[str] | None = None,
) -> dict:
    """Start an interactive terminal session and return its id plus the initial screen.

    Args:
        shell: "powershell" (Windows PowerShell 5.1), "pwsh" (PowerShell 7), "cmd",
            or an absolute path to any executable.
        cwd: Working directory. Defaults to the server's current directory.
        env: Extra environment variables merged into the inherited environment.
        cols: Terminal width in columns (default 120).
        rows: Terminal height in rows (default 30).
        name: Session id. Auto-generated (t1, t2, ...) when omitted.
        replace: Kill an existing session with the same name and start a fresh one.
        args: Extra arguments passed to the shell or executable.

    Returns:
        session_id, shell, cwd, pid, size, ready reason and the rendered screen.
    """
    def run() -> dict:
        session = get_manager().start(
            shell=shell, cwd=cwd, env=env, cols=cols, rows=rows,
            name=name, replace=replace, args=args,
        )
        ready = session.wait(quiet_ms=500, timeout_ms=20000)
        return {**session.info(), "ready": ready["reason"], "screen": ready["screen"]}

    return await anyio.to_thread.run_sync(run)


@mcp.tool()
async def terminal_send(
    session_id: str,
    text: str | None = None,
    keys: list[str] | None = None,
    enter: bool = False,
    repeat: int = 1,
) -> dict:
    """Send text and/or named keys to a session.

    Args:
        session_id: Session returned by terminal_start.
        text: Literal text to type (not followed by Enter unless enter=true).
        keys: Named keys, e.g. ["ctrl-c"], ["up"], ["tab"], ["f5"], ["text:abc"].
            Supported: enter, tab, backtab, esc, space, backspace, up, down, left, right,
            home, end, pageup, pagedown, insert, delete, f1..f12,
            ctrl-a..ctrl-z, ctrl-space, ctrl-break.
        enter: Append a carriage return after text/keys.
        repeat: Repeat the whole sequence 1..100 times.

    Returns:
        session_id, sent_chars and running state.
    """
    def run() -> dict:
        session = get_manager().get(session_id)
        payload = session.send(text=text, keys=keys, enter=enter, repeat=repeat)
        return {"session_id": session_id, "sent_chars": len(payload), "running": session.running}

    return await anyio.to_thread.run_sync(run)


@mcp.tool()
async def terminal_read(
    session_id: str,
    since: int | None = None,
    max_chars: int = 20000,
    grep: str | None = None,
    tail: int | None = None,
    strip_ansi: bool = True,
) -> dict:
    """Read incremental raw output from a session, without duplicates.

    Each call returns only what arrived after the previous read. Use the returned
    cursor with `since` to resume from an explicit position.

    Args:
        session_id: Session returned by terminal_start.
        since: Absolute character offset to read from. Defaults to the last read position.
        max_chars: Maximum characters returned (head+tail with an explicit omission marker).
        grep: Keep only lines matching this regular expression.
        tail: Keep only the last N lines (applied after grep).
        strip_ansi: Remove ANSI escape sequences.

    Returns:
        text, cursor (pass as `since`), dropped, truncated, running, exit_code.

    Note: PowerShell (PSReadLine) repaints the current line with cursor movements, so raw
    output contains fragments. Use terminal_screen for an authoritative view.
    """
    def run() -> dict:
        return get_manager().get(session_id).read(
            since=since, max_chars=max_chars, grep=grep, tail=tail, strip_ansi=strip_ansi
        )

    return await anyio.to_thread.run_sync(run)


@mcp.tool()
async def terminal_wait(
    session_id: str,
    until: str | None = None,
    quiet_ms: int = 0,
    timeout_ms: int = 30000,
    ignore_echo: bool = True,
) -> dict:
    """Block until output matches a regex, becomes quiet, the session exits, or timeout.

    Args:
        session_id: Session returned by terminal_start.
        until: Case-insensitive regular expression to wait for, e.g. "PS C:\\\\|>>>|Done".
        quiet_ms: Return when no output arrived for this long (0 disables quiet detection).
            Provide at least one of `until` or `quiet_ms`.
        timeout_ms: Give up after this long.
        ignore_echo: Ignore the echo of the last command line when matching `until`
            (prevents matching the command text itself).

    Returns:
        reason: "matched" | "quiet" | "exited" | "timeout",
        matched, running, exit_code, and the rendered screen.
    """
    def run() -> dict:
        return get_manager().get(session_id).wait(
            until=until, quiet_ms=quiet_ms, timeout_ms=timeout_ms, ignore_echo=ignore_echo
        )

    return await anyio.to_thread.run_sync(run)


@mcp.tool()
async def terminal_screen(session_id: str, max_chars: int = 20000) -> dict:
    """Return the rendered terminal screen (VT emulation) with cursor position.

    This is the clean view: cursor moves, erases and color codes are applied, so it shows
    exactly what a human would see, including the current prompt or TUI.

    Args:
        session_id: Session returned by terminal_start.
        max_chars: Maximum characters returned (head+tail with an omission marker).

    Returns:
        text, cursor {x,y}, cols, rows, running, exit_code.
    """
    def run() -> dict:
        return get_manager().get(session_id).screen(max_chars=max_chars)

    return await anyio.to_thread.run_sync(run)


@mcp.tool()
async def terminal_interrupt(session_id: str, force: bool = False) -> dict:
    """Stop the command running in a session, keeping the shell alive.

    Sends Ctrl+C first. Native Windows programs often ignore the control character
    inside a pseudo-console, so any child process still running after a short grace
    period is terminated together with its own children. The shell itself is preserved.

    Args:
        session_id: Session returned by terminal_start.
        force: Skip the grace period and terminate child processes immediately.

    Returns:
        session_id, sent, running and the list of terminated pids.
    """
    def run() -> dict:
        return get_manager().get(session_id).interrupt(force=force)

    return await anyio.to_thread.run_sync(run)


@mcp.tool()
async def terminal_resize(session_id: str, cols: int, rows: int) -> dict:
    """Resize the pseudo-terminal (affects wrapping and full-screen programs).

    Args:
        session_id: Session returned by terminal_start.
        cols: New width, 2..1000.
        rows: New height, 2..500.
    """
    def run() -> dict:
        return get_manager().get(session_id).resize(cols=cols, rows=rows)

    return await anyio.to_thread.run_sync(run)


@mcp.tool()
async def terminal_list() -> dict:
    """List active sessions with their state, pid, cwd, size, idle time and buffer size."""
    def run() -> dict:
        return {"sessions": get_manager().list()}

    return await anyio.to_thread.run_sync(run)


@mcp.tool()
async def terminal_stop(session_id: str, force: bool = False) -> dict:
    """Close a session and free its process.

    Args:
        session_id: Session returned by terminal_start.
        force: Kill the whole process tree instead of requesting a graceful stop.
    """
    def run() -> dict:
        get_manager().stop(session_id, force=force)
        return {"session_id": session_id, "stopped": True}

    return await anyio.to_thread.run_sync(run)


@mcp.tool()
async def terminal_exec(
    command: str,
    shell: str = "powershell",
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout_ms: int = 120000,
    max_chars: int = 20000,
) -> dict:
    """Run a one-shot command to completion and return its output and exit code.

    Use this for non-interactive commands. Use terminal_start + terminal_send for programs
    that need input, a TUI, or a persistent shell.

    Args:
        command: Command line to execute.
        shell: "powershell", "pwsh" or "cmd".
        cwd: Working directory. Defaults to the server's current directory.
        env: Extra environment variables.
        timeout_ms: Kill the command after this long.
        max_chars: Maximum output characters returned.

    Returns:
        output, exit_code, timed_out, duration_ms, truncated.
    """
    def run() -> dict:
        return get_manager().execute(
            command=command, shell=shell, cwd=cwd, env=env,
            timeout_ms=timeout_ms, max_chars=max_chars,
        )

    return await anyio.to_thread.run_sync(run)


def main() -> None:
    argv = sys.argv[1:]
    if "--version" in argv or "-V" in argv:
        print(f"mcp-interactive-terminal {__version__}")
        return
    if "--help" in argv or "-h" in argv:
        print(
            "mcp-interactive-terminal - interactive terminal MCP server (stdio)\n\n"
            "Usage: mcp-interactive-terminal [--version] [--help]\n\n"
            "Configure it in your MCP client; it speaks the Model Context Protocol on\n"
            "stdin/stdout and logs to stderr.\n"
            "Environment: MCP_TERMINAL_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR|CRITICAL"
        )
        return
    level = os.environ.get("MCP_TERMINAL_LOG_LEVEL", "WARNING").upper()
    logging.basicConfig(level=level, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        mcp.run(transport="stdio")
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        if _manager is not None:
            _manager.stop_all()


if __name__ == "__main__":
    main()
