"""Install 7Hills Link for the current user, and uninstall it.

The exe lives in %LOCALAPPDATA%\\Programs\\7HillsLink (no admin rights, and the
folder is writable so updates can replace the exe). Started from anywhere else,
the window offers to install: copy the exe there, add Start menu and desktop
shortcuts, point "Start with Windows" at it, start the installed copy and let
that one remove the old file.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .log import log

APP_NAME = "7Hills Link"
EXE_NAME = "7HillsLink.exe"


def install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "Programs" / "7HillsLink"


def target_exe() -> Path:
    return install_dir() / EXE_NAME


def is_packaged() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def current_exe() -> Path:
    return Path(sys.executable).resolve()


def is_installed_copy() -> bool:
    try:
        return current_exe().parent == install_dir().resolve()
    except OSError:
        return False


def needs_install(declined: bool) -> bool:
    return is_packaged() and not declined and not is_installed_copy()


def _special_folder(name: str) -> Path | None:
    try:
        import win32com.client  # pywin32
        return Path(win32com.client.Dispatch("WScript.Shell").SpecialFolders(name))
    except Exception as e:
        log.warning("special folder %s: %s", name, e)
        return None


def _shortcut_paths() -> dict[str, Path]:
    out: dict[str, Path] = {}
    programs = _special_folder("Programs")
    desktop = _special_folder("Desktop")
    if programs:
        out["start_menu"] = programs / (APP_NAME + ".lnk")
    if desktop:
        out["desktop"] = desktop / (APP_NAME + ".lnk")
    return out


def _make_shortcut(link: Path, exe: Path) -> bool:
    try:
        import win32com.client
        sc = win32com.client.Dispatch("WScript.Shell").CreateShortCut(str(link))
        sc.TargetPath = str(exe)
        sc.WorkingDirectory = str(exe.parent)
        sc.IconLocation = str(exe) + ",0"
        sc.Description = "7Hills Link: Star Citizen telemetry for 7hills.space"
        sc.save()
        return True
    except Exception as e:
        log.warning("shortcut %s: %s", link, e)
        return False


def install(start_menu: bool, desktop: bool, remove_old: bool, start_with_windows: bool) -> str | None:
    """Copy this exe into place and start it there. Returns an error text, or None
    when the installed copy has been started and this process should quit."""
    if not is_packaged():
        return "Installing works only in the packaged 7HillsLink.exe"
    src, dst = current_exe(), target_exe()
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".new")
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    except OSError as e:
        log.error("install copy failed: %s", e)
        return f"Could not copy to {dst.parent}: {e}"
    links = _shortcut_paths()
    if start_menu and "start_menu" in links:
        _make_shortcut(links["start_menu"], dst)
    if desktop and "desktop" in links:
        _make_shortcut(links["desktop"], dst)
    from .prefs import apply_startup
    apply_startup(start_with_windows, dst)
    args = [str(dst), "--installed"]
    if remove_old:
        args += ["--remove-old", str(src)]
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen(args, close_fds=True, creationflags=flags, cwd=str(dst.parent))
    except OSError as e:
        log.error("could not start the installed copy: %s", e)
        return f"Installed, but could not start it: {e}"
    log.info("installed to %s (from %s)", dst, src)
    return None


def remove_old_copy(path: str) -> None:
    """In the installed copy: delete the exe it was installed from, once that one has exited."""
    old = Path(path)
    if not old.name.lower().endswith(".exe") or old.resolve() == current_exe():
        return

    def run():
        for _ in range(60):
            try:
                old.unlink()
                log.info("removed the old copy %s", old)
                return
            except FileNotFoundError:
                return
            except OSError:
                time.sleep(0.5)
        log.warning("could not remove the old copy %s", old)
    threading.Thread(target=run, name="remove-old", daemon=True).start()


def uninstall() -> None:
    """Remove shortcuts and the Windows Run entry, then open the app folder so the
    user can delete it after quitting (a running exe cannot delete itself)."""
    from .prefs import apply_startup
    apply_startup(False)
    for link in _shortcut_paths().values():
        try:
            link.unlink()
        except OSError:
            pass
    log.info("uninstalled shortcuts and autostart")
    try:
        os.startfile(str(current_exe().parent))  # type: ignore[attr-defined]
    except Exception:
        pass
