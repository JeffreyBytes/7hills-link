"""Find the Virpil (VPC) devices connected to this PC.

Virpil devices use USB vendor id 0x3344. Each device shows up as several HID
interfaces, so they are grouped by product id and serial number into one entry
per physical device. Reading the list only looks at what Windows reports; it
does not open or send anything to the devices.
"""

from __future__ import annotations

VIRPIL_VID = 0x3344


def _hid():
    try:
        import hid  # hidapi
        return hid
    except Exception:
        return None


def list_devices() -> tuple[list[dict], str | None]:
    """[{id, name, vid, pid, serial}] sorted by name, and an error text if listing failed."""
    hid = _hid()
    if hid is None:
        return [], "USB device listing is not available in this build"
    try:
        raw = hid.enumerate(VIRPIL_VID, 0)
    except Exception as e:
        return [], f"Could not list USB devices: {e}"[:200]
    seen: dict[str, dict] = {}
    for d in raw:
        pid = int(d.get("product_id") or 0)
        serial = (d.get("serial_number") or "").strip()
        dev_id = f"{VIRPIL_VID:04X}:{pid:04X}" + (f":{serial}" if serial else "")
        name = (d.get("product_string") or "").strip() or f"Virpil device {pid:04X}"
        cur = seen.get(dev_id)
        # Keep the most descriptive name among the device's interfaces.
        if cur is None or (len(name) > len(cur["name"]) and not name.startswith("Virpil device")):
            seen[dev_id] = {"id": dev_id, "name": name, "vid": f"{VIRPIL_VID:04X}", "pid": f"{pid:04X}", "serial": serial or None}
    out = sorted(seen.values(), key=lambda x: (x["name"].lower(), x["id"]))
    return out, None
