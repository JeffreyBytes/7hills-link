"""Local bridge: lets tools on this PC read ship state and send game actions.

Off by default. Listens on 127.0.0.1 only, never on the network, and nothing
from 7Net can reach it. Every request needs the local key; requests from a web
page (any Origin header) are refused, so a website cannot drive your ship
through localhost.

  GET  /state                       compact ship and player state (?raw=1 for the full frame)
  GET  /actions                     actions this game build accepts
  POST /action {name, hold_ms?}     send one action to the game
  GET  /events                      Server-Sent Events: the state whenever it changes

Key: header "X-7Hills-Key: <key>" or "Authorization: Bearer <key>".
"""

from __future__ import annotations

import collections
import hmac
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .paths import data_dir

DEFAULT_PORT = 50052
MAX_PER_SECOND = 10
# Actions that can lose you the ship or lock out your crew: blocked until allowed.
RISKY = {
    "v_self_destruct", "v_eject", "v_emergency_exit",
    "v_lock_all_doors", "v_toggle_all_doorlocks", "v_lock_all_ports", "v_toggle_all_portlocks",
}


def _enum(v, prefix: str) -> str | None:
    if v is None or v == "":
        return None
    return str(v).replace(prefix, "").lower()


def state_from_frame(frame: dict | None) -> dict:
    """The parts of a frame a button box cares about, in plain values."""
    if not frame:
        return {"in_game": False}
    actor = frame.get("actor") or {}
    st = actor.get("state") or {}
    out: dict = {
        "in_game": True,
        "locomotion": _enum(st.get("locomotion"), "ACTOR_LOCOMOTION_STATE_"),
        "seat": st.get("seat_name") or None,
        "crew_role": _enum(st.get("crew_role"), "ACTOR_CREW_ROLE_"),
        "seated": False,
    }
    vs = (frame.get("vehicle") or {}).get("state") or {}
    if vs.get("class_name"):
        fl = vs.get("flight") or {}
        fs = fl.get("state") or {}
        ins = fl.get("instruments") or {}
        mm = vs.get("master_mode") or {}
        sh = vs.get("shields") or {}
        boost = ins.get("boost") or {}
        wf = frame.get("weapons") or {}
        out.update({
            "seated": True,
            "ship": vs.get("class_name"),
            "ship_id": vs.get("name"),
            "gear": _enum(fs.get("gear"), "VEHICLE_COMPONENT_DEPLOYMENT_STATE_"),
            "vtol": _enum(fs.get("vtol"), "VEHICLE_COMPONENT_DEPLOYMENT_STATE_"),
            "landed": fs.get("is_landed"),
            "lights": vs.get("lights_enabled"),
            "master_mode": _enum(mm.get("mode"), "VEHICLE_MASTER_MODE_"),
            "quantum_spooled": mm.get("spooled"),
            "power": {k: v for k, v in (vs.get("power") or {}).items() if isinstance(v, bool)},
            "shields": sh.get("level"),
            "hull": vs.get("health"),
            "boost_engaged": boost.get("engaged"),
            "ifcs": {k: v for k, v in (fl.get("settings") or {}).items() if isinstance(v, (bool, int, float, str))},
            "annunciators": {k: _enum(v, "ANNUNCIATOR_STATE_") for k, v in (vs.get("annunciators") or {}).items()},
            "weapon_group": wf.get("preset_name") or wf.get("preset_index"),
            "gimbals_locked": (wf.get("settings") or {}).get("gimbals_locked"),
        })
    return out


class BridgeConfig:
    """Stored in %LOCALAPPDATA%\\7HillsLink\\bridge.json."""

    def __init__(self) -> None:
        self.path = data_dir() / "bridge.json"
        d = {}
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self.enabled = bool(d.get("enabled", False))
        self.allow_risky = bool(d.get("allow_risky", False))
        p = d.get("port")
        self.port = p if isinstance(p, int) and 1024 <= p <= 65535 else DEFAULT_PORT
        k = d.get("key")
        self.key = k if isinstance(k, str) and len(k) >= 24 else secrets.token_urlsafe(24)
        self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps({"enabled": self.enabled, "allow_risky": self.allow_risky, "port": self.port, "key": self.key}, indent=2), encoding="utf-8")

    def new_key(self) -> None:
        self.key = secrets.token_urlsafe(24)
        self.save()


class Bridge:
    """HTTP server on 127.0.0.1. get_frame returns the latest raw frame; get_actions the GameActions or None."""

    def __init__(self, get_frame: Callable[[], dict | None], get_actions: Callable[[], object | None]) -> None:
        self.cfg = BridgeConfig()
        self._get_frame = get_frame
        self._get_actions = get_actions
        self._server: ThreadingHTTPServer | None = None
        self._stop = threading.Event()
        self.error: str | None = None
        self.log: collections.deque = collections.deque(maxlen=20)
        self._recent: collections.deque = collections.deque()
        self._rate_lock = threading.Lock()

    # ---------------------------------------------------------------- lifecycle

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> None:
        if self._server:
            return
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", self.cfg.port), _handler(self))
        except OSError as e:
            self.error = f"Port {self.cfg.port} is in use ({e.strerror or e})"
            return
        srv.daemon_threads = True
        self._stop.clear()
        self._server, self.error = srv, None
        threading.Thread(target=srv.serve_forever, name="bridge", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        srv, self._server = self._server, None
        if srv:
            srv.shutdown()
            srv.server_close()

    # ---------------------------------------------------------------- logic used by the handler

    def authorized(self, headers) -> bool:
        key = headers.get("X-7Hills-Key") or ""
        auth = headers.get("Authorization") or ""
        if not key and auth.lower().startswith("bearer "):
            key = auth[7:].strip()
        return bool(key) and hmac.compare_digest(key.encode(), self.cfg.key.encode())

    def _rate_ok(self) -> bool:
        now = time.monotonic()
        with self._rate_lock:
            while self._recent and now - self._recent[0] > 1.0:
                self._recent.popleft()
            if len(self._recent) >= MAX_PER_SECOND:
                return False
            self._recent.append(now)
            return True

    def run_action(self, name: str, hold_ms: int = 0) -> tuple[int, dict]:
        if not isinstance(name, str) or not name or len(name) > 80:
            return 400, {"error": "name is required"}
        if name in RISKY and not self.cfg.allow_risky:
            self._log(name, False, "blocked: risky actions are off")
            return 403, {"error": f"{name} is blocked. Allow risky actions in 7Hills Link to use it."}
        if not self._rate_ok():
            return 429, {"error": f"More than {MAX_PER_SECOND} actions per second"}
        acts = self._get_actions()
        if acts is None:
            return 503, {"error": "Game not connected"}
        hold = max(0, min(int(hold_ms or 0), 10_000))
        try:
            result = acts.trigger(name, hold)
        except Exception as e:
            self._log(name, False, str(e)[:160])
            return 502, {"error": str(e)[:200]}
        self._log(name, True, None)
        return 200, {"ok": True, "action": name, "result": result}

    def _log(self, name: str, ok: bool, error: str | None) -> None:
        self.log.appendleft({"action": name, "ok": ok, "error": error, "at": time.time()})

    def status(self) -> dict:
        last = self.log[0] if self.log else None
        return {
            "enabled": self.cfg.enabled, "running": self.running, "port": self.cfg.port, "key": self.cfg.key,
            "allow_risky": self.cfg.allow_risky, "error": self.error,
            "last": dict(last, ago=round(time.time() - last["at"], 1)) if last else None,
        }


def _handler(bridge: Bridge):
    class H(BaseHTTPRequestHandler):
        server_version = "7HillsLinkBridge"

        def log_message(self, *a):  # quiet
            pass

        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _gate(self) -> bool:
            # Browsers always send Origin on cross-site requests; local tools do not.
            if self.headers.get("Origin"):
                self._send(403, {"error": "Requests from web pages are not allowed"})
                return False
            if not bridge.authorized(self.headers):
                self._send(401, {"error": "Missing or wrong key"})
                return False
            return True

        def do_GET(self):
            if not self._gate():
                return
            path, _, query = self.path.partition("?")
            if path == "/state":
                frame = bridge._get_frame()
                self._send(200, {"raw": frame} if "raw=1" in query else state_from_frame(frame))
            elif path == "/actions":
                acts = bridge._get_actions()
                if acts is None:
                    return self._send(503, {"error": "Game not connected"})
                try:
                    items = acts.list()
                except Exception as e:
                    return self._send(502, {"error": str(e)[:200]})
                self._send(200, {"actions": [dict(a, blocked=a["action_name"] in RISKY and not bridge.cfg.allow_risky) for a in items]})
            elif path == "/events":
                self._events()
            else:
                self._send(404, {"error": "Unknown path"})

        def do_POST(self):
            if not self._gate():
                return
            if self.path.partition("?")[0] != "/action":
                return self._send(404, {"error": "Unknown path"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(n, 4096)) or b"{}")
            except (ValueError, OSError):
                return self._send(400, {"error": "Invalid JSON"})
            if not isinstance(body, dict):
                return self._send(400, {"error": "Invalid JSON"})
            code, out = bridge.run_action(body.get("name"), body.get("hold_ms") or 0)
            self._send(code, out)

        def do_OPTIONS(self):  # no CORS: web pages get nothing
            self._send(403, {"error": "Requests from web pages are not allowed"})

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = None
            ping = time.monotonic()
            try:
                while not bridge._stop.is_set():
                    st = json.dumps(state_from_frame(bridge._get_frame()), sort_keys=True)
                    if st != last:
                        self.wfile.write(b"event: state\ndata: " + st.encode() + b"\n\n")
                        self.wfile.flush()
                        last, ping = st, time.monotonic()
                    elif time.monotonic() - ping > 15:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        ping = time.monotonic()
                    time.sleep(0.1)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    return H
