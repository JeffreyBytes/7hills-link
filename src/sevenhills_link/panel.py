"""Panel setup: button presses become game actions, LEDs follow the game.

Mappings live in %LOCALAPPDATA%\\7HillsLink\\panel.json:
  {active, mappings: [{id, device_id, device_name, button, function, mode, led, on_color, off_color}]}
mode: "button" (push button: sends the opposite of the current state, so it
never gets out of step) or "switch" (latching: pressed = on, released = off).

LEDs are set through Virpil's VPC_LED_Control.exe only when their colour
changes. When the game is not running, the panels get their own profile back.
"""

from __future__ import annotations

import json
import queue
import secrets
import threading
import time
from typing import Callable

from . import leds
from .functions import AMBER, BY_ID, OFF, state_label
from .paths import data_dir

HOLD_RISKY = 1.0
FLASH = 0.4
BLINK_HZ = 2.0


class PanelConfig:
    def __init__(self) -> None:
        self.path = data_dir() / "panel.json"
        d = {}
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self.active = bool(d.get("active", True))
        self.mappings: list[dict] = [m for m in d.get("mappings", []) if isinstance(m, dict) and m.get("function") in BY_ID][:200]
        # Joysticks & panels as a whole: off by default, on for anyone who already set up buttons.
        self.enabled = bool(d.get("enabled", bool(self.mappings)))

    def save(self) -> None:
        self.path.write_text(json.dumps({"enabled": self.enabled, "active": self.active, "mappings": self.mappings}, indent=2), encoding="utf-8")


def _color(c, default: str) -> str:
    try:
        return "".join(leds.snap(str(c)))
    except Exception:
        return default


class PanelEngine:
    def __init__(self, get_state: Callable[[], dict], get_actions: Callable[[], object | None],
                 get_tool: Callable[[], object | None], led_runner: Callable = leds.run) -> None:
        self.cfg = PanelConfig()
        self._get_state = get_state
        self._get_actions = get_actions
        self._get_tool = get_tool
        self._led_run = led_runner
        self._events: queue.Queue = queue.Queue()
        self._jobs: queue.Queue = queue.Queue()
        self._memo: dict[str, bool] = {}          # last state we set for functions the game does not report
        self._flash: dict[str, float] = {}
        self._held: dict[str, float] = {}         # risky mappings: press time
        self._led_last: dict[tuple, str] = {}
        self._driving: set[str] = set()           # devices whose LEDs we changed
        self.learn: dict | None = None
        self.log: list[dict] = []
        self.led_error: str | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        threading.Thread(target=self._loop, name="panel", daemon=True).start()
        threading.Thread(target=self._worker, name="panel-io", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    # ---------------------------------------------------------------- input from ButtonWatcher (any thread)

    def on_button(self, press: dict) -> None:
        self._events.put(press)

    # ---------------------------------------------------------------- setup API for the window

    def start_learn(self) -> None:
        self.learn = {"waiting": True, "since": time.time()}

    def cancel_learn(self) -> None:
        self.learn = None

    def save_mapping(self, m: dict) -> dict:
        f = BY_ID.get(m.get("function"))
        if not f:
            raise ValueError("Pick what the button should do")
        button = m.get("button")
        if f.kind != "led" and not isinstance(button, int):
            raise ValueError("Press a button first")
        led = m.get("led")
        led = int(led) if isinstance(led, (int, float)) or (isinstance(led, str) and led.isdigit()) else None
        if led is not None and not (1 <= led <= 255):
            raise ValueError("LED number must be 1-255")
        if f.kind == "led" and (led is None or not m.get("device_id")):
            raise ValueError("Pick a device and an LED")
        out = {
            "id": m.get("id") or secrets.token_hex(4),
            "device_id": ":".join(str(m.get("device_id") or "").split(":")[:2]).upper(),  # VID:PID, as button events report it
            "device_name": str(m.get("device_name") or "")[:60],
            "button": button if f.kind != "led" else None,
            "function": f.id,
            "mode": "switch" if m.get("mode") == "switch" else "button",
            "led": led,
            "on_color": _color(m.get("on_color"), f.on_color),
            "off_color": _color(m.get("off_color"), f.off_color),
            "moving_color": _color(m.get("moving_color"), AMBER),
            "idle_color": _color(m.get("idle_color"), OFF),
            "blink_moving": m.get("blink_moving", True) is not False,
            "reverse": bool(m.get("reverse")),
        }
        with self._lock:
            # One mapping per physical button.
            self.cfg.mappings = [x for x in self.cfg.mappings if x["id"] != out["id"] and not (
                out["button"] is not None and x.get("button") == out["button"] and x.get("device_id") == out["device_id"])]
            self.cfg.mappings.append(out)
            self.cfg.save()
            self._led_last.clear()
        self.learn = None
        return out

    def delete_mapping(self, mid: str) -> None:
        with self._lock:
            gone = [x for x in self.cfg.mappings if x["id"] == mid]
            self.cfg.mappings = [x for x in self.cfg.mappings if x["id"] != mid]
            self.cfg.save()
        for m in gone:
            if m.get("led"):
                self._jobs.put(("led", m["device_id"], 0, OFF))  # back to the device profile
                self._led_last.clear()

    def set_active(self, on: bool) -> None:
        self.cfg.active = bool(on)
        self.cfg.save()
        self._led_last.clear()

    def find(self, device_id: str, button: int) -> dict | None:
        for m in self.cfg.mappings:
            if m.get("device_id") == device_id and m.get("button") == button:
                return m
        return None

    def now(self, function_id: str, mid: str | None = None) -> dict:
        """What the game reports for a function right now, for the window."""
        f = BY_ID.get(function_id)
        if not f:
            return {}
        st = self._get_state() or {}
        v = f.state(st) if f.state else self._memo.get(mid or "")
        if f.state is None and v is None:
            return {"label": "Not reported by the game", "value": None}
        return {"label": state_label(f, v), "value": v}

    def status(self) -> dict:
        maps = []
        for m in self.cfg.mappings:
            x = dict(m)
            x["now"] = self.now(m["function"], m["id"])
            maps.append(x)
        return {"enabled": self.cfg.enabled, "active": self.cfg.active, "mappings": maps, "learn": self.learn,
                "log": self.log[:5], "led_error": self.led_error}

    # ---------------------------------------------------------------- the loop

    def _loop(self) -> None:
        last_led = 0.0
        while not self._stop.is_set():
            try:
                press = self._events.get(timeout=0.05)
                self._handle(press)
            except queue.Empty:
                pass
            now = time.time()
            for mid, t in list(self._held.items()):
                if now - t >= HOLD_RISKY:
                    self._held.pop(mid, None)
                    m = next((x for x in self.cfg.mappings if x["id"] == mid), None)
                    if m:
                        self._send(m, BY_ID[m["function"]].toggle)
            if now - last_led >= 0.25:
                last_led = now
                try:
                    self._update_leds(now)
                except Exception as e:  # never let a bad frame stop the panel
                    self.led_error = str(e)[:160]

    def _handle(self, p: dict) -> None:
        if self.learn and self.learn.get("waiting") and p.get("pressed"):
            dev = p.get("device_id") or ""
            self.learn = {"waiting": False, "device_id": dev, "device_name": p.get("device"), "button": p.get("button"),
                          "existing": self.find(dev, p.get("button"))}
            return
        if not (self.cfg.enabled and self.cfg.active):
            return
        m = self.find(p.get("device_id") or "", p.get("button"))
        if not m:
            return
        f = BY_ID[m["function"]]
        pressed = bool(p.get("pressed"))
        if f.risky:
            if pressed:
                self._held[m["id"]] = time.time()
            else:
                self._held.pop(m["id"], None)
            return
        if m.get("mode") == "switch":
            on = pressed != bool(m.get("reverse"))   # reverse: a lever whose button is held while up
            action = (f.on if on else f.off) or f.toggle
            self._memo[m["id"]] = on
            self._send(m, action)
            return
        if not pressed:
            return
        if f.on and f.off:
            cur = self._current(m, f, self._get_state())
            want_on = not cur if isinstance(cur, bool) else True
            self._memo[m["id"]] = want_on
            self._send(m, f.on if want_on else f.off)
        else:
            self._memo[m["id"]] = not self._memo.get(m["id"], False)
            self._send(m, f.toggle)

    def _current(self, m: dict, f, st: dict):
        v = f.state(st) if f.state else None
        if v == "moving":
            return None
        if v is None:
            return self._memo.get(m["id"])
        return v

    def _send(self, m: dict, action: str | None) -> None:
        if not action:
            return
        self._flash[m["id"]] = time.time() + FLASH
        self._jobs.put(("action", action, BY_ID[m["function"]].hold_ms, m["id"]))

    # ---------------------------------------------------------------- LEDs

    def _update_leds(self, now: float) -> None:
        st = self._get_state() or {}
        in_game = bool(st.get("in_game")) and self._get_actions() is not None
        lit = [m for m in self.cfg.mappings if m.get("led")]
        if not (self.cfg.enabled and self.cfg.active and in_game and lit):
            # Hand the panels back to their own profile once.
            for dev in list(self._driving):
                self._jobs.put(("led", dev, 0, OFF))
                self._driving.discard(dev)
            self._led_last.clear()
            return
        blink = int(now * BLINK_HZ * 2) % 2 == 0
        for m in lit:
            f = BY_ID[m["function"]]
            v = f.state(st) if f.state else self._memo.get(m["id"])
            if self._flash.get(m["id"], 0) > now and f.state is None:
                color = m["on_color"]
            elif v == "moving":
                color = m.get("moving_color", AMBER) if (blink or not m.get("blink_moving", True)) else OFF
            elif v is True:
                color = m["on_color"] if not (f.blink_when_on and not blink) else OFF
            elif v is False:
                color = m["off_color"]
            else:
                color = m.get("idle_color", OFF) if f.state else m["off_color"]
            key = (m["device_id"], m["led"])
            if self._led_last.get(key) != color:
                self._led_last[key] = color
                self._driving.add(m["device_id"])
                self._jobs.put(("led", m["device_id"], m["led"], color))

    # ---------------------------------------------------------------- slow work off the loop

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            if job[0] == "action":
                _, action, hold, mid = job
                acts = self._get_actions()
                ok, err = False, "Game not connected"
                if acts is not None:
                    try:
                        acts.trigger(action, hold)
                        ok, err = True, None
                    except Exception as e:
                        err = str(e)[:160]
                self.log.insert(0, {"action": action, "ok": ok, "error": err, "at": time.time()})
                del self.log[10:]
            elif job[0] == "led":
                _, dev, num, color = job
                ok, text = self._led_run(self._get_tool(), dev, num, color)
                self.led_error = None if ok else text
