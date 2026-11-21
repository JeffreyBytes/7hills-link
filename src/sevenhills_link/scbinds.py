"""Read Star Citizen's own joystick bindings (actionmaps.xml) for a channel.

Lets the window warn when a panel button already does something in the game,
so one press would not do two things. Read-only; never writes the file.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

_INPUT = re.compile(r"^js(\d+)_button(\d+)$", re.I)
_GUID = re.compile(r"\{([0-9A-Fa-f]{4})([0-9A-Fa-f]{4})-", re.I)


def actionmaps_path(channel_folder: Path) -> Path:
    return channel_folder / "user" / "client" / "0" / "Profiles" / "default" / "actionmaps.xml"


def bindings(channel_folder: Path) -> dict[str, dict[int, list[str]]]:
    """{"3344:80CC": {7: ["v_toggle_landing_system"]}} for joysticks with a USB id in the file."""
    path = actionmaps_path(channel_folder)
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return {}
    instance: dict[str, str] = {}
    for opt in root.iter("options"):
        if (opt.get("type") or "").lower() != "joystick":
            continue
        m = _GUID.search(opt.get("Product") or "")
        if m and opt.get("instance"):
            pid, vid = m.group(1).upper(), m.group(2).upper()
            instance[opt.get("instance")] = f"{vid}:{pid}"
    out: dict[str, dict[int, list[str]]] = {}
    for action in root.iter("action"):
        name = action.get("name")
        for rb in action.iter("rebind"):
            m = _INPUT.match((rb.get("input") or "").strip())
            if not (m and name):
                continue
            dev = instance.get(m.group(1))
            if not dev:
                continue
            out.setdefault(dev, {}).setdefault(int(m.group(2)), []).append(name)
    return out
