import asyncio
import json
import os
import pathlib
import sys

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows ConPTY only")

ROOT = pathlib.Path(__file__).resolve().parents[1]

EXPECTED_TOOLS = {
    "terminal_start",
    "terminal_send",
    "terminal_read",
    "terminal_wait",
    "terminal_screen",
    "terminal_interrupt",
    "terminal_resize",
    "terminal_list",
    "terminal_stop",
    "terminal_exec",
}


def payload(result) -> dict:
    if result.structured_content:
        return result.structured_content
    for item in result.content:
        if getattr(item, "type", None) == "text":
            return json.loads(item.text)
    raise AssertionError(f"Unexpected tool result: {result!r}")


async def call(session, name, arguments=None, timeout=60):
    return payload(await asyncio.wait_for(session.call_tool(name, arguments or {}), timeout))


async def test_mcp_stdio_end_to_end():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_interactive_terminal"],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await asyncio.wait_for(session.initialize(), 30)
            assert init.server_info.name == "interactive-terminal"
            assert "terminal" in (init.instructions or "").lower()

            listed = await asyncio.wait_for(session.list_tools(), 30)
            names = {tool.name for tool in listed.tools}
            assert EXPECTED_TOOLS <= names
            for tool in listed.tools:
                assert tool.description and len(tool.description) > 20

            started = await call(session, "terminal_start", {"shell": "powershell", "cwd": str(ROOT)})
            session_id = started["session_id"]
            assert started["running"] is True
            assert "PS " in started["screen"]

            sent = await call(session, "terminal_send", {
                "session_id": session_id,
                "text": "Write-Output 'mcp-e2e-ok'",
                "enter": True,
            })
            assert sent["sent_chars"] > 0

            waited = await call(session, "terminal_wait", {
                "session_id": session_id,
                "until": "mcp-e2e-ok",
                "timeout_ms": 20000,
            })
            assert waited["reason"] == "matched"
            assert waited["matched"] is True

            screen = await call(session, "terminal_screen", {"session_id": session_id})
            assert "mcp-e2e-ok" in screen["text"]
            assert screen["cols"] == 120

            read = await call(session, "terminal_read", {"session_id": session_id})
            assert isinstance(read["cursor"], int)

            resized = await call(session, "terminal_resize", {
                "session_id": session_id, "cols": 100, "rows": 30,
            })
            assert resized["cols"] == 100

            sessions = await call(session, "terminal_list")
            assert any(item["session_id"] == session_id for item in sessions["sessions"])

            interrupt = await call(session, "terminal_interrupt", {"session_id": session_id})
            assert interrupt["session_id"] == session_id

            executed = await call(session, "terminal_exec", {"command": "exit 7"})
            assert executed["exit_code"] == 7

            stopped = await call(session, "terminal_stop", {"session_id": session_id})
            assert stopped["stopped"] is True

            remaining = await call(session, "terminal_list")
            assert remaining["sessions"] == []


async def test_mcp_error_is_reported():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_interactive_terminal"],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), 30)
            result = await asyncio.wait_for(
                session.call_tool("terminal_screen", {"session_id": "ghost"}), 30
            )
            assert result.is_error is True
