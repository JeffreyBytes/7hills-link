"""Updates 7Hills Link from the GitHub releases of this repository.

1. check(): asks api.github.com for the latest release; newer than this build?
2. download(): fetches 7HillsLink.exe to %LOCALAPPDATA%\\7HillsLink\\update\\ and checks
   its SHA-256 against the release (the asset digest GitHub reports, or the
   7HillsLink.exe.sha256 file the build uploads). A file that does not match is deleted.
3. install(): only in the packaged exe. Renames the running exe to
   7HillsLink.old.exe (Windows allows renaming a running exe), puts the new one
   in its place and starts it with --updated. The new process writes a "ready"
   marker; if none appears within 20 s, the old exe is put back and started.
4. cleanup(): the new process removes 7HillsLink.old.exe at startup.

Downloads come only from github.com / objects.githubusercontent.com over HTTPS.
Once releases are code-signed, install() will also require the 7Hills AB signature.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__
from .paths import data_dir

REPO = "TheBanjolorian/7hills-link"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = "7HillsLink.exe"
ALLOWED_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
READY_WAIT = 20.0


class UpdateError(Exception):
    pass


def parse_version(v: str) -> tuple[int, ...]:
    v = (v or "").strip().lstrip("vV").split("-")[0]
    out = []
    for part in v.split("."):
        out.append(int(part) if part.isdigit() else 0)
    return tuple(out) or (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


def _get(url: str, timeout: float = 15.0) -> bytes:
    host = urllib.parse.urlparse(url).hostname or ""
    if not url.startswith("https://") or not (host == "api.github.com" or host in ALLOWED_HOSTS):
        raise UpdateError(f"Refusing to download from {host or url}")
    req = urllib.request.Request(url, headers={"User-Agent": f"7HillsLink/{__version__}", "Accept": "application/octet-stream, application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        final = urllib.parse.urlparse(r.geturl()).hostname or ""
        if final != "api.github.com" and final not in ALLOWED_HOSTS:
            raise UpdateError(f"Redirected to {final}")
        return r.read()


def check() -> dict | None:
    """{version, url, sha256 or None, sha256_url or None, notes} for a newer release, else None."""
    data = json.loads(_get(API))
    tag = data.get("tag_name") or ""
    if data.get("draft") or data.get("prerelease") or not is_newer(tag):
        return None
    assets = {a.get("name"): a for a in data.get("assets") or []}
    exe = assets.get(ASSET)
    if not exe:
        return None
    digest = exe.get("digest") or ""
    sha = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None
    side = assets.get(ASSET + ".sha256")
    return {"version": tag.lstrip("vV"), "url": exe.get("browser_download_url"), "sha256": sha,
            "sha256_url": side.get("browser_download_url") if side else None, "size": exe.get("size")}


def update_dir() -> Path:
    d = data_dir() / "update"
    d.mkdir(parents=True, exist_ok=True)
    return d


def download(info: dict) -> Path:
    want = info.get("sha256")
    if not want and info.get("sha256_url"):
        want = _get(info["sha256_url"]).decode("ascii", "replace").split()[0].strip().lower()
    if not want or len(want) != 64:
        raise UpdateError("The release has no checksum; not installing it")
    blob = _get(info["url"], timeout=120)
    got = hashlib.sha256(blob).hexdigest()
    if got != want:
        raise UpdateError("Downloaded file does not match the release checksum")
    path = update_dir() / f"7HillsLink-{info['version']}.exe"
    tmp = path.with_suffix(".part")
    tmp.write_bytes(blob)
    os.replace(tmp, path)
    for old in update_dir().glob("7HillsLink-*.exe"):
        if old != path:
            try:
                old.unlink()
            except OSError:
                pass
    return path


def can_install() -> bool:
    """Only the packaged exe replaces itself; running from source never does."""
    return bool(getattr(sys, "frozen", False)) and os.name == "nt"


def _ready_marker() -> Path:
    return update_dir() / "ready"


def mark_ready() -> None:
    """Called by a freshly updated process once it is up."""
    try:
        _ready_marker().write_text(str(os.getpid()))
    except OSError:
        pass


def install(new_exe: Path) -> bool:
    """Swap in the new exe and start it. True means: the caller should exit now."""
    if not can_install():
        raise UpdateError("Updates install only in the packaged 7HillsLink.exe")
    current = Path(sys.executable).resolve()
    old = current.with_name(current.stem + ".old.exe")
    try:
        if old.exists():
            old.unlink()
        os.replace(current, old)                 # renaming a running exe is allowed
    except OSError as e:
        raise UpdateError(f"Cannot replace {current.name} (folder not writable?): {e}") from e
    try:
        data = Path(new_exe).read_bytes()
        current.write_bytes(data)
    except OSError as e:
        os.replace(old, current)
        raise UpdateError(f"Could not write the new version: {e}") from e

    marker = _ready_marker()
    try:
        marker.unlink()
    except OSError:
        pass
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        proc = subprocess.Popen([str(current), "--updated", __version__], close_fds=True, creationflags=flags)
    except OSError as e:
        _rollback(current, old)
        raise UpdateError(f"Could not start the new version: {e}") from e

    end = time.time() + READY_WAIT
    while time.time() < end:
        if marker.exists():
            return True
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    # The new version did not come up: put the old one back.
    try:
        proc.kill()
    except Exception:
        pass
    time.sleep(0.5)
    _rollback(current, old)
    raise UpdateError("The new version did not start; kept the current one")


def _rollback(current: Path, old: Path) -> None:
    try:
        if current.exists():
            current.unlink()
        os.replace(old, current)
    except OSError:
        pass


def cleanup() -> None:
    """Remove the previous exe after an update (retry a few times while it exits)."""
    if not can_install():
        return
    old = Path(sys.executable).resolve().with_name(Path(sys.executable).stem + ".old.exe")
    for _ in range(20):
        if not old.exists():
            return
        try:
            old.unlink()
            return
        except OSError:
            time.sleep(0.5)
