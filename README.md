# mcp-interactive-terminal

[![CI](https://github.com/hugo94z/mcp-interactive-terminal/actions/workflows/ci.yml/badge.svg)](https://github.com/hugo94z/mcp-interactive-terminal/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

A [Model Context Protocol](https://modelcontextprotocol.io) server that gives AI agents a **real interactive terminal** on Windows: launch PowerShell, PowerShell 7 or CMD, type into it, read what happens, answer prompts, interrupt processes and resize the window — across multiple sessions that stay alive between tool calls.

Most "terminal" tools for LLMs run a command and return its output. That is not a terminal. Anything that asks a question, shows a menu, draws a progress bar or waits for a keypress is out of reach. This server runs the shell inside a **ConPTY** (Windows pseudo-console), so the agent talks to a genuine terminal session, exactly like a human.

```
agent ── MCP (stdio) ──> session manager ── ConPTY ──> powershell.exe / pwsh.exe / cmd.exe
                             │
                             ├─ raw output ring buffer (cursor based reads)
                             └─ VT emulator (rendered screen, like a human sees it)
```

## Features

- **Real PTY sessions** — ConPTY under the hood, not pipes. Prompts, TUIs, colors and interactive programs work.
- **Live interaction** — send text and named keys (`enter`, `tab`, `ctrl-c`, `up`, `f1`…), read incrementally.
- **Rendered screen** — an internal VT100 emulator turns cursor movements and repaints into clean, readable text.
- **Blocking waits** — wait for a regex, for output to go quiet, for the process to exit, or for a timeout. No polling.
- **Multiple sessions** — independent shells running in parallel, each with its own buffer, screen and size.
- **One-shot shortcut** — `terminal_exec` for commands that only need output and an exit code.
- **UTF-8 everywhere** — accents and non-ASCII output are handled for PowerShell and CMD.
- **Token friendly** — incremental reads, `grep`/`tail` filters, head+tail truncation with an explicit omission marker.

## Requirements

- Windows 10 (1809+) or Windows 11 — ConPTY is required.
- Python 3.10+.
- An MCP client (Claude Desktop, Cursor, opencode, Cline, any SDK-based agent).

## Install

```powershell
pip install git+https://github.com/hugo94z/mcp-interactive-terminal
```

Or from a clone:

```powershell
git clone https://github.com/hugo94z/mcp-interactive-terminal
cd mcp-interactive-terminal
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -e .
```

The `mcp-interactive-terminal` command starts the server on stdio.

## Configure your MCP client

### opencode (`~/.config/opencode/opencode.jsonc`)

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "interactive-terminal": {
        "type": "local",
        "command": ["mcp-interactive-terminal"]
      }
    }
  }
}
```

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "interactive-terminal": {
      "command": "mcp-interactive-terminal"
    }
  }
}
```

### Cursor (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "interactive-terminal": {
      "command": "mcp-interactive-terminal"
    }
  }
}
```

If the command is not on your `PATH`, use the absolute path to the entry point, for example:

```json
{
  "command": "C:\\Users\\you\\project\\.venv\\Scripts\\mcp-interactive-terminal.exe"
}
```

## Tools

| Tool | Description |
|---|---|
| `terminal_start` | Start a session (`powershell`, `pwsh`, `cmd`, or any executable), with `cwd`, `env`, `cols`, `rows`, `name`, `replace`, `args`. Returns the id, pid and initial screen. |
| `terminal_send` | Send `text`, named `keys`, `enter=true`, `repeat`. |
| `terminal_read` | Incremental raw output since the last read (or an explicit `since` cursor). Optional `grep`, `tail`, `strip_ansi`. |
| `terminal_wait` | Block until `until` regex matches, output is quiet for `quiet_ms`, the session exits, or `timeout_ms`. Provide `until` and/or `quiet_ms`. |
| `terminal_screen` | Rendered VT screen with cursor position — the authoritative view. |
| `terminal_interrupt` | Ctrl+C, then terminate the child process tree if the command is still running. The shell survives. |
| `terminal_resize` | Resize the pseudo-terminal (columns × rows). |
| `terminal_list` | Active sessions, state, pid, cwd, size, idle time. |
| `terminal_stop` | Close a session (`force` to kill the tree). |
| `terminal_exec` | One-shot command: output, `exit_code`, `timed_out`, duration. |

### Keys accepted by `terminal_send`

`enter` `tab` `backtab` `esc` `space` `backspace` `up` `down` `left` `right` `home` `end`
`pageup` `pagedown` `insert` `delete` `f1`…`f12` `ctrl-a`…`ctrl-z` `ctrl-space` `ctrl-break`,
plus `text:<literal>` for arbitrary text.

## Example

```text
terminal_start(shell="powershell", cwd="C:/work/api")
-> session_id: "t1", screen: "PS C:\\work\\api> "

terminal_send(session_id="t1", text="python -m http.server 8080", enter=True)
terminal_wait(session_id="t1", until="Serving HTTP on", timeout_ms=15000)
-> reason: "matched"

terminal_exec(command="curl.exe -s -o NUL -w '%{http_code}' http://localhost:8080")
-> output: "200", exit_code: 0

terminal_interrupt(session_id="t1")
-> sent: true, running: true      # back to the prompt

terminal_send(session_id="t1", text="exit", enter=True)
terminal_stop(session_id="t1")
```

## Why `terminal_screen` and `terminal_read` both exist

PowerShell uses PSReadLine, which redraws the current line with absolute cursor movements every time a character is typed. Raw output therefore contains fragments such as `\x1b[1;58He`, `\x1b[1;58Hec`, `\x1b[1;58Hech`… Stripping ANSI codes gives unreadable text.

`terminal_screen` feeds that stream into a VT100 emulator (via [pyte](https://github.com/selectel/pyte)) and returns what a human would actually see. `terminal_read` is still useful for exact incremental output (logs, byte streams, detecting events) and never returns the same bytes twice.

`terminal_wait` matches against the rendered screen **and** the raw output, and ignores the echo of the command you just typed by default (`ignore_echo`).

## Design notes

- One reader thread per session pushes output into a bounded ring buffer and the VT screen under a single lock.
- Reads are cursor-based (`buffer end offset`), so nothing is duplicated and nothing is lost silently.
- `terminal_wait` sleeps on a condition variable — no busy loop, negligible CPU.
- Sessions are closed on exit (`atexit`, EOF on stdio, or explicit `terminal_stop`); forced stops use `taskkill /T /F` on the process tree.
- PowerShell sessions are started with `-NoExit -Command` to force UTF-8 console encoding before the first prompt.
- CMD sessions run `chcp 65001` at startup.

## Notes on Windows behaviour

- **Ctrl+C in a pseudo-console** is not delivered as a console control event to native
  child processes: the control character reaches the console input buffer, but the child
  process group does not receive `CTRL_C_EVENT`. `terminal_interrupt` therefore sends
  Ctrl+C and then terminates the remaining child process tree while keeping the shell
  alive. Processes that trap Ctrl+C gracefully get the chance to run their handler first.
- **Resizing** the pseudo-console can make some shells drop the next write. See
  [Known limitations](#known-limitations).

## Known limitations

- Windows only. ConPTY does not exist on Linux or macOS, so there is no POSIX backend yet.
- `terminal_resize` works, but some shells need a moment to redraw after a size change; give
  the next command a short delay if you resize in the middle of a session.
- The rendered screen shows the visible window only. Use `terminal_read` for full scrollback
  (bounded by the 500k-character ring buffer).
- Interactive programs that require raw mouse events or bracketed paste are not emulated.

## Security

This server executes arbitrary commands **with the privileges of the user running it**. There is no sandbox, no allowlist and no confirmation prompt. Only connect it to MCP clients you trust, and treat its tools with the same care as a shell running on your machine.

## Development

```powershell
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
.venv\Scripts\python.exe -m pytest -q
```

The test suite covers the ring buffer, VT rendering, key mapping, truncation, real PowerShell/CMD
sessions (interactive prompt, Ctrl+C, resize, exit codes) and a full MCP client handshake over stdio.

## License

MIT — see [LICENSE](LICENSE).
