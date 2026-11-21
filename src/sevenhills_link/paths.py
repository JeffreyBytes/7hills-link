"""Where the client keeps its files, and where bundled files live when frozen."""

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    """%LOCALAPPDATA%\\7HillsLink on Windows, ~/.7hills-link elsewhere."""
    base = os.environ.get("LOCALAPPDATA")
    p = Path(base) / "7HillsLink" if base else Path.home() / ".7hills-link"
    p.mkdir(parents=True, exist_ok=True)
    return p


def resource(*parts: str) -> Path:
    """A file shipped with the client (PyInstaller unpacks to sys._MEIPASS)."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    frozen = root / "sevenhills_link" / Path(*parts)
    return frozen if frozen.exists() else Path(__file__).resolve().parent / Path(*parts)
