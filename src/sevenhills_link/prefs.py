"""Window and startup preferences, kept in %LOCALAPPDATA%\\7HillsLink\\app.json."""

from __future__ import annotations

import json
import sys

from .paths import data_dir

DEFAULTS = {
    "start_with_windows": True,   # opens minimized in the tray, no music
    "tray": True,                 # minimize and close hide the window to the tray
    "play_on_start": True,        # play the music when the window opens (not on autostart)
    "install_declined": False,    # "Run without installing" was pressed: do not offer to install again
}


class Prefs:
    def __init__(self) -> None:
        self.path = data_dir() / "app.json"
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stored = {}
        self.values = {k: bool(stored.get(k, v)) for k, v in DEFAULTS.items()}

    def get(self, key: str) -> bool:
        return self.values[key]

    def set(self, key: str, value: bool) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        self.values[key] = bool(value)
        try:
            self.path.write_text(json.dumps(self.values), encoding="utf-8")
        except OSError:
            pass
        if key == "start_with_windows":
            apply_startup(self.values[key])

    def as_dict(self) -> dict:
        return dict(self.values)


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "7HillsLink"


def apply_startup(on: bool, exe=None) -> bool:
    """Add or remove the per-user Run entry. Only for the packaged exe on Windows.

    The entry points at the exe's current path, so it follows the exe if the
    user moves it (it is rewritten on every start).
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, f'"{exe or sys.executable}" --autostart')
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
