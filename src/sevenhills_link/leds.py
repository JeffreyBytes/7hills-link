"""Light Virpil LEDs through Virpil's own VPC_LED_Control.exe.

The tool ships with Virpil's VPC Software Suite. Call format, as used by
community tools: VPC_LED_Control.exe <VID> <PID> <command> <R> <G> <B>
with each colour channel one of 00, 40, 80, FF (64 colours). Command 0 resets
the device's LEDs to its own profile; which numbers address which LEDs
depends on the device, so the window lets you try numbers one by one.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

TOOL_NAME = "VPC_LED_Control.exe"
LEVELS = (0x00, 0x40, 0x80, 0xFF)


def snap(color: str) -> tuple[str, str, str]:
    """'#12A0FF' -> ('00', '80', 'FF'): each channel to the nearest level Virpil LEDs can show."""
    c = (color or "").strip().lstrip("#")
    if len(c) != 6:
        raise ValueError("Colour must be RRGGBB")
    out = []
    for i in (0, 2, 4):
        v = int(c[i:i + 2], 16)
        out.append(f"{min(LEVELS, key=lambda x: abs(x - v)):02X}")
    return out[0], out[1], out[2]


def find_tool(extra: list[Path] | None = None) -> Path | None:
    """Look in the usual install folders for VPC_LED_Control.exe."""
    roots = [Path(p) for p in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")) if p]
    roots += extra or []
    for root in roots:
        if not root.exists():
            continue
        try:
            for d in root.iterdir():
                if not d.is_dir() or not any(k in d.name.lower() for k in ("vpc", "virpil")):
                    continue
                for p in _walk(d, 3):
                    return p
        except OSError:
            continue
    return None


def _walk(folder: Path, depth: int):
    try:
        for p in folder.iterdir():
            if p.is_file() and p.name.lower() == TOOL_NAME.lower():
                yield p
            elif p.is_dir() and depth > 0:
                yield from _walk(p, depth - 1)
    except OSError:
        return


def command(tool: Path, device_id: str, cmd: int, color: str) -> list[str]:
    parts = device_id.split(":")
    if len(parts) < 2:
        raise ValueError("Unknown device")
    if not (0 <= int(cmd) <= 255):
        raise ValueError("LED number must be 0-255")
    r, g, b = snap(color)
    return [str(tool), parts[0], parts[1], str(int(cmd)), r, g, b]


def run(tool: Path | None, device_id: str, cmd: int, color: str) -> tuple[bool, str]:
    if not tool or not Path(tool).exists():
        return False, f"{TOOL_NAME} not found. Install Virpil's VPC Software Suite or choose the file."
    try:
        args = command(Path(tool), device_id, cmd, color)
    except ValueError as e:
        return False, str(e)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=5, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"{TOOL_NAME} failed: {e}"[:200]
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    if p.returncode != 0:
        return False, (out or f"exit code {p.returncode}")[:200]
    return True, out[:200]
