"""Talks to 7Net (www.7hills.space) and keeps the device key."""

from __future__ import annotations

import json
import os
import platform
import urllib.error
import urllib.request
import uuid

from . import __version__
from .paths import data_dir

BASE = os.environ.get("SEVENHILLS_LINK_BASE", "https://www.7hills.space")
UA = f"7HillsLink/{__version__} ({platform.system()} {platform.release()})"
KEYRING_SERVICE = "7HillsLink"


# Bytes sent to and received from 7Net, for the traffic readout in the window.
traffic = {"out": 0, "in": 0}


class ApiError(Exception):
    """status 0 means 7Net could not be reached. code and reason come from 7Net's
    answer when a PC key is refused: code 'unlinked' (reason user, admin,
    replaced, limit or all), 'expired', 'unauthorized' or 'not_member'."""

    def __init__(self, status: int, message: str, code: str | None = None, reason: str | None = None):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message
        self.code = code
        self.reason = reason


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
        # A 200 that is not 7Net's JSON (a hotel wifi sign-in page, a block page from a
        # filter) is a network problem, not an answer: report it like one instead of
        # letting the decode error end the thread that called.
        try:
            answer = json.loads(raw)
        except ValueError:
            raise ApiError(0, "Got a web page instead of an answer from 7Net. Check the connection.") from None
        if not isinstance(answer, dict):
            raise ApiError(0, "Unexpected answer from 7Net.")
        return answer
    except urllib.error.HTTPError as e:
        code = reason = None
        try:
            j = json.loads(e.read() or b"{}")
            msg = j.get("error", e.reason)
            code, reason = j.get("code"), j.get("reason")
        except Exception:
            msg = str(e.reason)
        raise ApiError(e.code, str(msg), code if isinstance(code, str) else None, reason if isinstance(reason, str) else None) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ApiError(0, str(e)) from None


def device_name() -> str:
    return (platform.node() or "PC")[:60]


def install_id() -> str:
    """A random id for this installation, made on first use and kept in the data folder.
    When the same installation is linked again, 7Net unlinks its old key. Not tied to
    the hardware."""
    f = data_dir() / "install.id"
    try:
        return str(uuid.UUID(f.read_text().strip()))
    except (OSError, ValueError):
        pass
    new = str(uuid.uuid4())
    try:
        f.write_text(new)
    except OSError:
        pass
    return new


def start_link() -> dict:
    return _call("POST", "/api/telemetry/link/start", {"device_name": device_name(), "install_id": install_id()})


def unlink_device(token: str) -> dict:
    """Asks 7Net to stop accepting this PC's key. Call before forgetting the key."""
    return _call("POST", "/api/telemetry/device/unlink", {}, token=token, timeout=6)


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
