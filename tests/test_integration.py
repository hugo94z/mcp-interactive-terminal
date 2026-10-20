import os
import time

import pytest

from mcp_interactive_terminal.sessions import SessionError, TerminalManager

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows ConPTY only")


@pytest.fixture()
def manager():
    instance = TerminalManager()
    yield instance
    instance.stop_all()


def start(manager, shell="powershell", **kwargs):
    session = manager.start(shell=shell, **kwargs)
    session.wait(quiet_ms=600, timeout_ms=25_000)
    return session


def test_powershell_prompt_and_echo(manager):
    session = start(manager)
    assert "PS " in session.screen()["text"]
    session.send(text="Write-Output 'hello-e2e'", enter=True)
    result = session.wait(until="hello-e2e", timeout_ms=15_000)
    assert result["reason"] == "matched"
    assert "hello-e2e" in session.screen()["text"]


def test_utf8_output(manager):
    session = start(manager)
    session.send(text='Write-Output "accents: caf\u00e9 \u00e9l\u00e8ve \u00e0\u00e7"', enter=True)
    result = session.wait(until="caf\u00e9", timeout_ms=15_000)
    assert result["matched"], result["screen"]
    assert "caf\u00e9 \u00e9l\u00e8ve" in session.screen()["text"]


def test_read_is_incremental(manager):
    session = start(manager)
    session.read()
    session.send(text="1..3 | ForEach-Object { \"line-$_\" }", enter=True)
    session.wait(until="line-3", timeout_ms=15_000)
    first = session.read()
    assert "line-1" in first["text"]
    assert session.read()["text"] == ""
    session.send(text="Write-Output 'second-batch'", enter=True)
    session.wait(until="second-batch", timeout_ms=15_000)
    second = session.read()
    assert "second-batch" in second["text"]
    assert "line-1" not in second["text"]


def test_read_filters(manager):
    session = start(manager)
    session.send(text="1..6 | ForEach-Object { \"value-$_\" }", enter=True)
    session.wait(until="value-6", timeout_ms=15_000)
    tailed = session.read(tail=2)
    assert "value-6" in tailed["text"]
    assert "value-1" not in tailed["text"]
    filtered = session.read(since=0, grep="value-[24]")
    assert "value-2" in filtered["text"]
    assert "value-3" not in filtered["text"]


def test_read_host_interaction(manager):
    session = start(manager)
    session.send(text="Read-Host 'Quel nom'", enter=True)
    session.wait(quiet_ms=800, timeout_ms=15_000)
    assert "Quel nom" in session.screen()["text"]
    session.send(text="hugo", enter=True)
    result = session.wait(until="hugo", timeout_ms=15_000)
    assert result["matched"]


def test_cmd_interactive_set_p(manager):
    session = start(manager, shell="cmd")
    session.send(text="set /p nom=Nom? ", enter=True)
    session.wait(quiet_ms=800, timeout_ms=15_000)
    session.send(text="hugo", enter=True)
    session.wait(quiet_ms=800, timeout_ms=15_000)
    session.send(text="echo [%nom%]", enter=True)
    result = session.wait(until=r"\[hugo\]", timeout_ms=15_000)
    assert result["matched"], result["screen"]


def test_ctrl_c_keeps_shell_alive(manager):
    session = start(manager)
    session.send(text='python -c "import time; time.sleep(30)"', enter=True)
    session.wait(quiet_ms=600, timeout_ms=10_000)
    result = session.interrupt()
    assert result["sent"] is True
    assert result["killed"], result
    session.wait(quiet_ms=600, timeout_ms=15_000)
    session.send(text="Write-Output 'after-interrupt'", enter=True)
    matched = session.wait(until="after-interrupt", timeout_ms=15_000)
    assert matched["matched"], matched["screen"]
    assert session.running


def test_exit_code_and_session_end(manager):
    session = start(manager)
    session.send(text="exit", enter=True)
    deadline = time.time() + 20
    while session.running and time.time() < deadline:
        time.sleep(0.05)
    assert session.running is False
    assert session.exit_code == 0
    with pytest.raises(SessionError):
        session.send(text="echo closed", enter=True)


def test_resize(manager):
    session = start(manager)
    info = session.resize(cols=100, rows=40)
    assert info == {"session_id": session.name, "cols": 100, "rows": 40}
    assert session.screen()["cols"] == 100
    session.send(text="Write-Output 'after-resize'", enter=True)
    matched = session.wait(until="after-resize", timeout_ms=15_000)
    assert matched["matched"], matched["screen"]


def test_multiple_sessions_are_isolated(manager):
    first = start(manager, name="alpha")
    second = start(manager, name="beta")
    first.send(text="Write-Output 'marker-alpha'", enter=True)
    second.send(text="Write-Output 'marker-beta'", enter=True)
    assert first.wait(until="marker-alpha", timeout_ms=15_000)["matched"]
    assert second.wait(until="marker-beta", timeout_ms=15_000)["matched"]
    assert first.screen()["text"].count("marker-beta") == 0
    names = {item["session_id"] for item in manager.list()}
    assert names == {"alpha", "beta"}


def test_duplicate_name_requires_replace(manager):
    start(manager, name="dup")
    with pytest.raises(SessionError):
        manager.start(name="dup")
    replaced = manager.start(name="dup", replace=True)
    replaced.wait(quiet_ms=600, timeout_ms=25_000)
    assert replaced.running


def test_unknown_session_errors(manager):
    with pytest.raises(SessionError):
        manager.get("nope")


def test_exec_exit_code_and_output(manager):
    result = manager.execute("Write-Output 'exec-ok'; exit 3")
    assert result["exit_code"] == 3
    assert "exec-ok" in result["output"]
    assert result["timed_out"] is False


def test_exec_cmd(manager):
    result = manager.execute("echo cmd-ok", shell="cmd")
    assert result["exit_code"] == 0
    assert "cmd-ok" in result["output"]


def test_exec_timeout(manager):
    started = time.monotonic()
    result = manager.execute("Start-Sleep -Seconds 20", timeout_ms=1500)
    assert result["timed_out"] is True
    assert result["exit_code"] is None
    assert time.monotonic() - started < 12


def test_exec_working_directory(manager, tmp_path):
    result = manager.execute("(Get-Location).Path", cwd=str(tmp_path))
    assert str(tmp_path) in result["output"]


def test_invalid_shell(manager):
    with pytest.raises(SessionError):
        manager.start(shell="definitely-not-a-shell")
    with pytest.raises(SessionError):
        manager.execute("echo x", shell="bash")
