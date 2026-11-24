"""Talks to 7Net (www.7hills.space) and keeps the device key."""

from __future__ import annotations

import json
import os
import platform
import urllib.error
import urllib.request

from . import __version__
from .paths import data_dir

BASE = os.environ.get("SEVENHILLS_LINK_BASE", "https://www.7hills.space")
UA = f"7HillsLink/{__version__} ({platform.system()} {platform.release()})"
KEYRING_SERVICE = "7HillsLink"


# Bytes sent to and received from 7Net, for the traffic readout in the window.
traffic = {"out": 0, "in": 0}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


def _call(method: str, path: str, body: dict | None = None, token: str | None = None, timeout: float = 10) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("User-Agent", UA)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    traffic["out"] += len(data or b"") + 300   # body plus roughly the request headers
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read() or b"{}"
            traffic["in"] += len(raw) + 200
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read() or b"{}").get("error", e.reason)
        except Exception:
            msg = str(e.reason)
        raise ApiError(e.code, str(msg)) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ApiError(0, str(e)) from None


def device_name() -> str:
    return (platform.node() or "PC")[:60]


def start_link() -> dict:
    return _call("POST", "/api/telemetry/link/start", {"device_name": device_name()})


def poll_link(code: str, poll_secret: str) -> dict:
    return _call("POST", "/api/telemetry/link/poll", {"code": code, "poll_secret": poll_secret})


_UNSET = object()


def ingest(token: str, frame: dict | None, events: list[str], location=_UNSET) -> dict:
    """location: a place from Game.log (location.Tracker.snapshot), None to clear it, or left out."""
    body = {"client_version": __version__, "frame": frame, "events": events}
    if location is not _UNSET:
        body["location"] = location
    return _call("POST", "/api/telemetry/ingest", body, token=token)


def get_settings(token: str) -> dict:
    return _call("GET", "/api/telemetry/device/settings", token=token)


def patch_settings(token: str, patch: dict) -> dict:
    return _call("PATCH", "/api/telemetry/device/settings", patch, token=token)


# ------------------------------------------------------------------ device key

def _key_file():
    return data_dir() / "device.key"


def load_token() -> str | None:
    try:
        import keyring  # type: ignore
        t = keyring.get_password(KEYRING_SERVICE, "device")
        if t:
            return t
    except Exception:
        pass
    f = _key_file()
    return f.read_text().strip() or None if f.exists() else None


def save_token(token: str) -> None:
    try:
        import keyring  # type: ignore
        keyring.set_password(KEYRING_SERVICE, "device", token)
        return
    except Exception:
        pass
    _key_file().write_text(token)


def clear_token() -> None:
    try:
        import keyring  # type: ignore
        keyring.delete_password(KEYRING_SERVICE, "device")
    except Exception:
        pass
    f = _key_file()
    if f.exists():
        f.unlink()
