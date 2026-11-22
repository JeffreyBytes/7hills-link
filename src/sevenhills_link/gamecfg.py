"""Switch on the game's local telemetry server.

Adds three lines to <channel>\\user.cfg (keeping everything already there) and
sets GRPC_CLIENT_SERVER_ENABLED for the Windows user. The game reads both at
start, so it must be restarted after the first setup.

On Linux (Wine/Proton) the variable has to be in the game's launch environment
(launcher script, Lutris or Steam launch options); the client cannot set it, so
it tells the player what to add and reads the running game's environment to check.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

DEFAULT_PORT = 50051
LIVE_PORT = 2942        # 4.x LIVE ignores grpc.client.server.port and always listens here
PORT_ENV = "SEVENHILLS_SC_PORT"   # force one port (also set by --port)
WANTED = {
    "grpc.client.server.enabled": "1",
    "grpc.client.server.port": str(DEFAULT_PORT),
    "server.game.telemetry.enabled": "1",
}
ENV_NAME = "GRPC_CLIENT_SERVER_ENABLED"
ENV_HOWTO = (
    f"Add {ENV_NAME}=true to the game's launch environment: "
    f"'export {ENV_NAME}=true' in your launch script, Lutris → Configure → System options → Environment variables, "
    f"or Steam launch options '{ENV_NAME}=true %command%'. Then restart the game."
)

_LINE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*=?\s*(.*?)\s*$")


class NeedsAdmin(Exception):
    """user.cfg is in a folder this Windows user may not write to."""


def read_cfg(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith(("--", ";", "#", "//")):
            continue
        m = _LINE.match(s)
        if m:
            out[m.group(1).lower()] = m.group(2)
    return out


def port_of(path: Path) -> int:
    v = read_cfg(path).get("grpc.client.server.port", "")
    try:
        p = int(v)
        return p if 1 <= p <= 65535 else DEFAULT_PORT
    except ValueError:
        return DEFAULT_PORT


def ports_for(path: Path) -> list[int]:
    """Ports to try, in order: a forced port alone, else the user.cfg port and then 2942."""
    forced = os.environ.get(PORT_ENV, "").strip()
    if forced.isdigit() and 1 <= int(forced) <= 65535:
        return [int(forced)]
    out = [port_of(path)]
    if LIVE_PORT not in out:
        out.append(LIVE_PORT)
    return out


def missing(path: Path) -> dict[str, str]:
    """Settings that are absent or set to something else."""
    cur = read_cfg(path)
    out = {}
    for k, v in WANTED.items():
        if k == "grpc.client.server.port":
            if k not in cur:  # any port the player chose is fine
                out[k] = v
        elif cur.get(k) != v:
            out[k] = v
    return out


def patched_text(text: str, changes: dict[str, str]) -> str:
    """Replace lines for keys we change, append the rest. Comments and other lines stay."""
    lines = text.splitlines()
    done: set[str] = set()
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith(("--", ";", "#", "//")):
            continue
        m = _LINE.match(s)
        if m and m.group(1).lower() in changes:
            key = m.group(1).lower()
            lines[i] = f"{key} = {changes[key]}"
            done.add(key)
    extra = [f"{k} = {v}" for k, v in changes.items() if k not in done]
    if extra:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("-- 7Hills Link: game telemetry for 7Net")
        lines.extend(extra)
    return "\n".join(lines) + "\n"


def apply(path: Path) -> bool:
    """Write the missing settings. True if the file changed. Raises NeedsAdmin when not allowed."""
    changes = missing(path)
    if not changes:
        return False
    old = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    try:
        path.write_text(patched_text(old, changes), encoding="utf-8")
    except PermissionError as e:
        raise NeedsAdmin(str(path)) from e
    return True


def apply_elevated(path: Path) -> bool:
    """Ask Windows (UAC) to run this program again as administrator just to write user.cfg."""
    if os.name != "nt":
        return False
    import ctypes
    if getattr(sys, "frozen", False):
        exe, args = sys.executable, f'--write-cfg "{path}"'
    else:
        exe, args = sys.executable, f'-m sevenhills_link --write-cfg "{path}"'
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 0)
    return rc > 32


# ------------------------------------------------------------------ environment

def env_enabled() -> bool | None:
    """True/False on Windows. Elsewhere: what the running game has, True if this
    client's own environment has it, None when the game is not running to check."""
    if os.name != "nt":
        from .detect import running_game_env
        game = running_game_env(ENV_NAME)
        if game is not None:
            return game.lower() == "true"
        if os.environ.get(ENV_NAME, "").lower() == "true":
            return True
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            v, _ = winreg.QueryValueEx(k, ENV_NAME)
            return str(v).lower() == "true"
    except OSError:
        return False


def env_manual() -> bool:
    """The player has to set the variable in the game's launch config themselves (not Windows)."""
    return os.name != "nt"


def enable_env() -> bool:
    """Set GRPC_CLIENT_SERVER_ENABLED=true for this Windows user and tell running programs."""
    if os.name != "nt":
        return False
    import ctypes
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, ENV_NAME, 0, winreg.REG_SZ, "true")
    HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
    ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", SMTO_ABORTIFHUNG, 5000, None)
    return True
