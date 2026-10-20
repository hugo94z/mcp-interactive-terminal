import os
import shutil
import subprocess


class BackendError(RuntimeError):
    pass


_CREATE_NO_WINDOW = 0x08000000


def require_supported() -> None:
    if os.name != "nt":
        raise BackendError(
            "mcp-interactive-terminal currently supports Windows only (ConPTY via pywinpty)."
        )


def spawn(argv: list[str], cwd: str | None = None, env: dict | None = None,
          cols: int = 120, rows: int = 30):
    require_supported()
    try:
        from winpty import PtyProcess
    except ImportError as exc:
        raise BackendError("pywinpty is not installed. Run: pip install pywinpty") from exc
    if not argv:
        raise BackendError("Empty command line")
    try:
        return PtyProcess.spawn(argv, cwd=cwd, env=env, dimensions=(rows, cols))
    except FileNotFoundError as exc:
        raise BackendError(f"Executable not found: {argv[0]}") from exc
    except PermissionError as exc:
        raise BackendError(f"Permission denied: {argv[0]}") from exc
    except Exception as exc:
        raise BackendError(f"Failed to start {argv[0]}: {exc}") from exc


def which_executable(name: str) -> str | None:
    return shutil.which(name)


def kill_tree(pid: int | None) -> None:
    if not pid or os.name != "nt":
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            creationflags=_CREATE_NO_WINDOW,
            timeout=10,
        )
    except Exception:
        pass


def kill_children(pid: int | None) -> None:
    if not pid or os.name != "nt":
        return
    for child in children_of(pid):
        try:
            subprocess.run(
                ["taskkill", "/PID", str(child), "/T", "/F"],
                capture_output=True,
                creationflags=_CREATE_NO_WINDOW,
                timeout=10,
            )
        except Exception:
            pass


def children_of(pid: int) -> list[int]:
    if not pid or os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return []
    pairs: list[tuple[int, int]] = []
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(ProcessEntry32W)
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                pairs.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID)))
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)
    return [child for child, parent in pairs if parent == pid]
