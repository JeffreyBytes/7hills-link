"""Find Star Citizen installs without asking the player.

Order: the running game process, paths the RSI Launcher wrote to its own files,
then the usual install folders on every drive. Each install root holds channel
folders (LIVE, PTU, ...) with Bin64\\StarCitizen.exe inside.
"""

from __future__ import annotations

import os
import re
import string
from dataclasses import dataclass
from pathlib import Path

CHANNELS = ["LIVE", "PTU", "EPTU", "TECH-PREVIEW", "HOTFIX"]

COMMON_ROOTS = [
    r"{d}:\Program Files\Roberts Space Industries\StarCitizen",
    r"{d}:\Roberts Space Industries\StarCitizen",
    r"{d}:\Games\Roberts Space Industries\StarCitizen",
    r"{d}:\StarCitizen",
    r"{d}:\Games\StarCitizen",
]


@dataclass
class Install:
    channel: str
    folder: Path          # ...\StarCitizen\PTU

    @property
    def exe(self) -> Path:
        return self.folder / "Bin64" / "StarCitizen.exe"

    @property
    def user_cfg(self) -> Path:
        return self.folder / "user.cfg"

    def as_dict(self) -> dict:
        return {"channel": self.channel, "folder": str(self.folder)}


def _channel_dir_from_exe(exe: Path) -> Path | None:
    # ...\StarCitizen\PTU\Bin64\StarCitizen.exe → ...\StarCitizen\PTU
    if exe.name.lower() != "starcitizen.exe" or exe.parent.name.lower() != "bin64":
        return None
    return exe.parent.parent


def running_game_folders() -> list[Path]:
    try:
        import psutil  # type: ignore
    except Exception:
        return []
    out: list[Path] = []
    for p in psutil.process_iter(["name", "exe"]):
        try:
            if (p.info.get("name") or "").lower() == "starcitizen.exe" and p.info.get("exe"):
                d = _channel_dir_from_exe(Path(p.info["exe"]))
                if d:
                    out.append(d)
        except Exception:
            continue
    return out


_PATH_RE = re.compile(r"([A-Za-z]:(?:\\\\|\\|/)[^\"'\r\n<>|*?]{1,200}?StarCitizen)(?=[\\/\"'\s]|$)", re.IGNORECASE)


def launcher_roots() -> list[Path]:
    """Folders named ...StarCitizen that the RSI Launcher mentions in its settings and logs."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return []
    base = Path(appdata) / "rsilauncher"
    if not base.exists():
        return []
    found: list[Path] = []
    files = list(base.glob("*.json")) + list((base / "logs").glob("*.log"))
    for f in files[:40]:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")[-2_000_000:]
        except Exception:
            continue
        for m in _PATH_RE.finditer(text):
            p = Path(m.group(1).replace("\\\\", "\\"))
            if p not in found:
                found.append(p)
    return found


def common_roots() -> list[Path]:
    roots: list[Path] = []
    for d in string.ascii_uppercase:
        if not os.path.exists(f"{d}:\\"):
            continue
        for pattern in COMMON_ROOTS:
            roots.append(Path(pattern.format(d=d)))
    return roots


def channels_in(root: Path) -> list[Install]:
    out: list[Install] = []
    for ch in CHANNELS:
        folder = root / ch
        if (folder / "Bin64" / "StarCitizen.exe").exists():
            out.append(Install(ch, folder))
    return out


def find_installs(extra_roots: list[Path] | None = None) -> list[Install]:
    seen: set[str] = set()
    out: list[Install] = []

    def add(inst: Install) -> None:
        key = str(inst.folder).lower()
        if key not in seen:
            seen.add(key)
            out.append(inst)

    for folder in running_game_folders():
        if (folder / "Bin64" / "StarCitizen.exe").exists():
            add(Install(folder.name.upper(), folder))
    for root in (extra_roots or []) + launcher_roots() + common_roots():
        try:
            for inst in channels_in(root):
                add(inst)
        except OSError:
            continue
    return out


def running_channel() -> str | None:
    folders = running_game_folders()
    return folders[0].name.upper() if folders else None
