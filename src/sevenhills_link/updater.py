"""Updates 7Hills Link from the GitHub releases of this repository.

1. check(): asks api.github.com for the latest release; newer than this build?
2. download(): fetches 7HillsLink.exe to %LOCALAPPDATA%\\7HillsLink\\update\\ and checks
   its SHA-256 against the release (the asset digest GitHub reports, or the
   7HillsLink.exe.sha256 file the build uploads). A file that does not match is deleted.
3. install(): only in the packaged exe. Starts a small PowerShell script and
   exits; the script waits for 7Hills Link to close, copies the new exe over
   the old one (kept as 7HillsLink.old.exe), starts it with --updated and waits
   for its "ready" marker; if none appears within 20 s it puts the old exe back.
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


SWAP_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$pids = @({pids})
$current = '{current}'
$backup = '{backup}'
$new = '{new}'
$marker = '{marker}'
$log = '{log}'
function Log($m) {{ Add-Content -Path $log -Value ((Get-Date -Format s) + ' ' + $m) }}
Log 'waiting for 7Hills Link to exit'
foreach ($p in $pids) {{ Wait-Process -Id $p -Timeout 30 }}
Start-Sleep -Milliseconds 500
Copy-Item -LiteralPath $current -Destination $backup -Force
$ok = $false
for ($i = 0; $i -lt 40; $i++) {{
  try {{ Copy-Item -LiteralPath $new -Destination $current -Force -ErrorAction Stop; $ok = $true; break }} catch {{ Start-Sleep -Milliseconds 500 }}
}}
if (-not $ok) {{ Log 'could not replace the exe; starting the old one'; Start-Process -FilePath $current; exit 1 }}
Remove-Item -LiteralPath $marker -Force
$proc = Start-Process -FilePath $current -ArgumentList '--updated','{old_version}' -PassThru
for ($i = 0; $i -lt 40; $i++) {{ if (Test-Path -LiteralPath $marker) {{ Log 'updated'; exit 0 }}; Start-Sleep -Milliseconds 500 }}
Log 'new version did not start; restoring the old one'
Stop-Process -Id $proc.Id -Force
Start-Sleep -Milliseconds 800
Copy-Item -LiteralPath $backup -Destination $current -Force
Start-Process -FilePath $current
exit 2
"""


def _ps_quote(p: Path | str) -> str:
    return str(p).replace("'", "''")


def swap_script(current: Path, new_exe: Path, pids: list[int]) -> str:
    return SWAP_SCRIPT.format(
        pids=",".join(str(int(p)) for p in pids),
        current=_ps_quote(current), backup=_ps_quote(current.with_name(current.stem + ".old.exe")),
        new=_ps_quote(new_exe), marker=_ps_quote(_ready_marker()), log=_ps_quote(update_dir() / "update.log"),
        old_version=__version__,
    )


def install(new_exe: Path) -> bool:
    """Hand the swap to a small PowerShell script that runs after this app exits.

    A running exe (and PyInstaller's open archive) cannot be replaced, so the
    script waits for both 7Hills Link processes to end, copies the new exe over
    the old one, starts it with --updated and waits for its "ready" marker; if
    none comes within 20 s it puts the old exe back and starts that. Returns
    True: the caller should exit now. Progress goes to update\\update.log.
    """
    if not can_install():
        raise UpdateError("Updates install only in the packaged 7HillsLink.exe")
    current = Path(sys.executable).resolve()
    if not os.access(current.parent, os.W_OK):
        raise UpdateError(f"Cannot write to {current.parent}. Move 7HillsLink.exe to a folder of yours, e.g. Downloads.")
    pids = [os.getpid()]
    try:
        pids.append(os.getppid())   # PyInstaller's launcher process
    except Exception:
        pass
    script = update_dir() / "swap.ps1"
    script.write_text(swap_script(current, Path(new_exe), pids), encoding="utf-8-sig")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script)],
                         close_fds=True, creationflags=flags)
    except OSError as e:
        raise UpdateError(f"Could not start the updater: {e}") from e
    return True


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
