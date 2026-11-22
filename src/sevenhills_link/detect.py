"""Find Star Citizen installs without asking the player.

Order: folders the player named (--game-dir / SEVENHILLS_SC_DIR), the running
game process, paths the RSI Launcher wrote to its own files, then the usual
install folders on every drive. Each install root holds channel folders (LIVE,
PTU, ...) with Bin64\\StarCitizen.exe inside.

On Linux the game runs in a Wine/Proton prefix; the same Windows paths are
looked for inside the usual prefixes (LUG helper, Lutris, Steam/Proton, ~/.wine).
"""

from __future__ import annotations

import os
import re
import string
from dataclasses import dataclass
from pathlib import Path

CHANNELS = ["LIVE", "PTU", "EPTU", "TECH-PREVIEW", "HOTFIX"]
IS_WINDOWS = os.name == "nt"
ENV_DIR = "SEVENHILLS_SC_DIR"   # extra install folders, separated by os.pathsep

COMMON_ROOTS = [
    r"{d}:\Program Files\Roberts Space Industries\StarCitizen",
    r"{d}:\Roberts Space Industries\StarCitizen",
    r"{d}:\Games\Roberts Space Industries\StarCitizen",
    r"{d}:\StarCitizen",
    r"{d}:\Games\StarCitizen",
]
# The same folders as parts below a Wine prefix's drive_c.
_WINE_PARTS = [
    ("Program Files", "Roberts Space Industries", "StarCitizen"),
    ("Roberts Space Industries", "StarCitizen"),
    ("Games", "Roberts Space Industries", "StarCitizen"),
    ("StarCitizen",),
    ("Games", "StarCitizen"),
]


@dataclass
class Install:
    channel: str
    folder: Path          # ...\StarCitizen\PTU
    source: str = "auto"  # auto (found by itself) | chosen (picked by the player)

    @property
    def exe(self) -> Path:
        return self.folder / "Bin64" / "StarCitizen.exe"

    @property
    def user_cfg(self) -> Path:
        return self.folder / "user.cfg"

    def as_dict(self) -> dict:
        return {"channel": self.channel, "folder": str(self.folder), "exe": str(self.exe), "source": self.source}


def _channel_dir_from_exe(exe: Path) -> Path | None:
    # ...\StarCitizen\PTU\Bin64\StarCitizen.exe → ...\StarCitizen\PTU
    if exe.name.lower() != "starcitizen.exe" or exe.parent.name.lower() != "bin64":
        return None
    return exe.parent.parent


def _game_processes():
    try:
        import psutil  # type: ignore
    except Exception:
        return []
    out = []
    for p in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            name = (p.info.get("name") or "").lower()
            cmd = p.info.get("cmdline") or []
            if name == "starcitizen.exe" or (not IS_WINDOWS and any(str(a).lower().endswith("starcitizen.exe") for a in cmd[:2])):
                out.append(p)
        except Exception:
            continue
    return out


def _wine_folder(p) -> Path | None:
    """Channel folder of a StarCitizen.exe running under Wine/Proton."""
    try:
        cwd = Path(p.cwd())
        if (cwd / "StarCitizen.exe").exists() or (cwd / "Bin64" / "StarCitizen.exe").exists():
            d = cwd.parent if cwd.name.lower() == "bin64" else cwd
            if (d / "Bin64" / "StarCitizen.exe").exists():
                return d
    except Exception:
        pass
    try:
        prefix = None
        try:
            prefix = (p.environ() or {}).get("WINEPREFIX")
        except Exception:
            pass
        prefix = Path(prefix) if prefix else Path.home() / ".wine"
        for arg in (p.info.get("cmdline") or [])[:2]:
            arg = str(arg)
            if not arg.lower().endswith("starcitizen.exe"):
                continue
            exe = Path(arg) if arg.startswith("/") else wine_to_unix(arg, prefix)
            d = _channel_dir_from_exe(exe) if exe else None
            if d and (d / "Bin64" / "StarCitizen.exe").exists():
                return d
    except Exception:
        pass
    return None


def running_game_folders() -> list[Path]:
    out: list[Path] = []
    for p in _game_processes():
        try:
            if IS_WINDOWS:
                d = _channel_dir_from_exe(Path(p.info["exe"])) if p.info.get("exe") else None
            else:
                d = _wine_folder(p)
            if d and d not in out:
                out.append(d)
        except Exception:
            continue
    return out


def running_game_env(name: str) -> str | None:
    """A variable from the running game's own environment (Linux: the Wine launch env), or None."""
    for p in _game_processes():
        try:
            v = (p.environ() or {}).get(name)
            if v is not None:
                return v
        except Exception:
            continue
    return None


# ------------------------------------------------------------------ Wine / Proton

def wine_to_unix(win_path: str, prefix: Path) -> Path | None:
    """C:\\Program Files\\... inside a prefix → <prefix>/drive_c/Program Files/..."""
    m = re.match(r"^([A-Za-z]):[\\/]*(.*)$", win_path.replace("\\\\", "\\"))
    if not m:
        return None
    letter, rest = m.group(1).lower(), m.group(2)
    dev = prefix / "dosdevices" / f"{letter}:"
    if dev.exists():
        base = dev.resolve()
    elif letter == "c":
        base = prefix / "drive_c"
    elif letter == "z":
        base = Path("/")
    else:
        return None
    parts = [x for x in re.split(r"[\\/]+", rest) if x]
    return base.joinpath(*parts) if parts else base


def wine_prefixes() -> list[Path]:
    """Wine/Proton prefixes where Star Citizen usually lives on Linux."""
    home = Path.home()
    cands: list[Path] = []
    if os.environ.get("WINEPREFIX"):
        cands.append(Path(os.environ["WINEPREFIX"]))
    cands += [home / "Games" / "star-citizen", home / "Games" / "starcitizen", home / ".wine"]
    globs = [
        (home / "Games", "*"),                                   # Lutris default: ~/Games/<game>
        (home / "Games", "*/*"),
        (home / ".local/share/lutris/runners/wine", "*"),
        (home / ".steam/steam/steamapps/compatdata", "*/pfx"),   # Proton
        (home / ".local/share/Steam/steamapps/compatdata", "*/pfx"),
        (home / ".var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/compatdata", "*/pfx"),
        (home / ".var/app/net.lutris.Lutris/data/lutris/prefixes", "*"),
    ]
    for base, pattern in globs:
        try:
            if base.is_dir():
                cands += sorted(base.glob(pattern))[:200]
        except OSError:
            continue
    out: list[Path] = []
    for c in cands:
        try:
            if (c / "drive_c").is_dir() and c not in out:
                out.append(c)
        except OSError:
            continue
    return out


def _roots_in_prefix(prefix: Path) -> list[Path]:
    return [prefix.joinpath("drive_c", *parts) for parts in _WINE_PARTS]


# ------------------------------------------------------------------ folders the player named

def roots_for(path: str | Path) -> list[Path]:
    """Install roots for a folder the player gave: StarCitizen root, a channel folder,
    StarCitizen.exe itself, or a whole Wine prefix."""
    p = Path(os.path.expanduser(str(path).strip().strip('"')))
    if p.is_file():
        d = _channel_dir_from_exe(p)
        return [d.parent] if d else []
    if (p / "Bin64" / "StarCitizen.exe").exists():
        return [p.parent]
    if (p / "drive_c").is_dir():
        return _roots_in_prefix(p)
    return [p]


def user_roots() -> list[Path]:
    """Roots from SEVENHILLS_SC_DIR (also set by --game-dir)."""
    out: list[Path] = []
    for part in os.environ.get(ENV_DIR, "").split(os.pathsep):
        if part.strip():
            for r in roots_for(part):
                if r not in out:
                    out.append(r)
    return out


_PATH_RE = re.compile(r"([A-Za-z]:(?:\\\\|\\|/)[^\"'\r\n<>|*?]{1,200}?StarCitizen)(?=[\\/\"'\s]|$)", re.IGNORECASE)


def _scan_launcher_dir(base: Path, prefix: Path | None = None) -> list[Path]:
    found: list[Path] = []
    files = list(base.glob("*.json")) + list((base / "logs").glob("*.log"))
    for f in files[:40]:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")[-2_000_000:]
        except Exception:
            continue
        for m in _PATH_RE.finditer(text):
            raw = m.group(1).replace("\\\\", "\\")
            p = wine_to_unix(raw, prefix) if prefix is not None else Path(raw)
            if p is not None and p not in found:
                found.append(p)
    return found


def launcher_roots() -> list[Path]:
    """Folders named ...StarCitizen that the RSI Launcher mentions in its settings and logs."""
    if IS_WINDOWS:
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) / "rsilauncher" if appdata else None
        return _scan_launcher_dir(base) if base and base.exists() else []
    found: list[Path] = []
    for prefix in wine_prefixes():
        try:
            bases = list((prefix / "drive_c" / "users").glob("*/AppData/Roaming/rsilauncher"))
        except OSError:
            continue
        for base in bases:
            for p in _scan_launcher_dir(base, prefix):
                if p not in found:
                    found.append(p)
    return found


def common_roots() -> list[Path]:
    roots: list[Path] = []
    if not IS_WINDOWS:
        for prefix in wine_prefixes():
            roots += _roots_in_prefix(prefix)
        return roots
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
    """extra_roots: folders the player named; None means read them from SEVENHILLS_SC_DIR."""
    if extra_roots is None:
        extra_roots = user_roots()
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
    for root in extra_roots + launcher_roots() + common_roots():
        try:
            for inst in channels_in(root):
                add(inst)
        except OSError:
            continue
    return out


def install_from_exe(path: str | Path) -> Install | None:
    """An install from a StarCitizen.exe the player picked; the channel is its folder name."""
    exe = Path(path)
    d = _channel_dir_from_exe(exe)
    if d is None or not exe.is_file():
        return None
    return Install(d.name.upper(), d, "chosen")


def apply_choices(found: list[Install], chosen: dict[str, str]) -> list[Install]:
    """One install per channel. A path the player picked wins over what was found."""
    out: dict[str, Install] = {}
    for inst in found:
        out.setdefault(inst.channel, inst)
    for ch, exe in chosen.items():
        inst = install_from_exe(exe)
        if inst and inst.channel == ch:
            out[ch] = inst
    order = {c: i for i, c in enumerate(CHANNELS)}
    return sorted(out.values(), key=lambda i: (order.get(i.channel, 99), i.channel))


def running_channel() -> str | None:
    folders = running_game_folders()
    return folders[0].name.upper() if folders else None
