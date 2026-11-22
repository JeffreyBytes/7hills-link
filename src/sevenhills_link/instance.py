"""One 7Hills Link at a time.

The first instance holds a named Windows mutex and waits on a named event.
A second start (double-click, Start menu, autostart) sets the event so the
first one shows its window, and then exits. Outside Windows this is a no-op.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Callable

MUTEX = "Local\\7HillsLink.instance"
EVENT = "Local\\7HillsLink.show"
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0

_handles: list = []   # keep the mutex and event open for the life of the process


def _k32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateEventW.restype = wintypes.HANDLE
    k.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    k.OpenEventW.restype = wintypes.HANDLE
    k.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.SetEvent.argtypes = [wintypes.HANDLE]
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return ctypes, k


def acquire(wait: float = 0.0) -> bool:
    """True if this process is the only 7Hills Link. With wait, keep trying that
    long (used right after an install or update, while the old one closes)."""
    if sys.platform != "win32":
        return True
    ctypes, k = _k32()
    deadline = time.time() + wait
    while True:
        h = k.CreateMutexW(None, False, MUTEX)
        if h and ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
            _handles.append(h)
            return True
        if h:
            k.CloseHandle(h)
        if time.time() >= deadline:
            return False
        time.sleep(0.25)


def signal_running() -> bool:
    """Ask the running instance to show its window."""
    if sys.platform != "win32":
        return False
    _, k = _k32()
    h = k.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False, EVENT)
    if not h:
        return False
    ok = bool(k.SetEvent(h))
    k.CloseHandle(h)
    return ok


def listen(on_show: Callable[[], None]) -> None:
    """In the running instance: call on_show each time another start asks for the window."""
    if sys.platform != "win32":
        return
    _, k = _k32()
    h = k.CreateEventW(None, False, False, EVENT)   # auto-reset
    if not h:
        return
    _handles.append(h)

    def loop():
        while True:
            if k.WaitForSingleObject(h, 0xFFFFFFFF) == WAIT_OBJECT_0:
                try:
                    on_show()
                except Exception:
                    pass
    threading.Thread(target=loop, name="instance-show", daemon=True).start()
