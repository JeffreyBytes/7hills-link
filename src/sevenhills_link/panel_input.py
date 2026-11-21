"""Watch joystick and panel buttons so the window can show which one was pressed.

Uses SDL through pygame-ce, which reads every button a device has (Virpil panels
can have more than the 32 that the old Windows joystick API reports). Runs in
its own thread with background events on, so presses count while the game has
focus. Only reads input; never sends anything to the devices.
"""

from __future__ import annotations

import collections
import os
import threading
import time

VIRPIL_VID = 0x3344


def vid_pid_from_guid(guid: str) -> tuple[int | None, int | None]:
    """SDL joystick GUIDs carry the USB ids little-endian: bytes 4-5 = vendor, 8-9 = product."""
    g = (guid or "").strip().lower()
    if len(g) != 32:
        return None, None
    try:
        b = bytes.fromhex(g)
    except ValueError:
        return None, None
    vid = b[4] | (b[5] << 8)
    pid = b[8] | (b[9] << 8)
    return (vid or None), (pid or None)


class ButtonWatcher:
    def __init__(self) -> None:
        self.available = False
        self.error: str | None = None
        self.devices: dict[int, dict] = {}  # SDL instance id -> {name, vid, pid, buttons}
        self.presses: collections.deque = collections.deque(maxlen=12)
        self.listeners: list = []  # called with each press dict, from this watcher's thread
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="panel-input", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.available = False
        self.devices.clear()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def _run(self) -> None:
        os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        try:
            import pygame
            pygame.display.init()
            pygame.joystick.init()
        except Exception as e:
            self.error = f"Button reading is not available: {e}"[:200]
            return
        self.available = True
        sticks: dict[int, object] = {}
        try:
            while not self._stop.is_set():
                for ev in pygame.event.get():
                    if ev.type == pygame.JOYDEVICEADDED:
                        try:
                            j = pygame.joystick.Joystick(ev.device_index)
                            j.init()
                            vid, pid = vid_pid_from_guid(j.get_guid())
                            sticks[j.get_instance_id()] = j
                            self.devices[j.get_instance_id()] = {"name": j.get_name(), "vid": vid, "pid": pid, "buttons": j.get_numbuttons()}
                        except Exception:
                            pass
                    elif ev.type == pygame.JOYDEVICEREMOVED:
                        sticks.pop(ev.instance_id, None)
                        self.devices.pop(ev.instance_id, None)
                    elif ev.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):
                        d = self.devices.get(ev.instance_id) or {}
                        press = {
                            "device": d.get("name") or "Joystick",
                            "device_id": _device_id(d),
                            "virpil": d.get("vid") == VIRPIL_VID,
                            "button": int(ev.button) + 1,  # 1-based, like Windows and the VPC tool
                            "pressed": ev.type == pygame.JOYBUTTONDOWN,
                            "at": time.time(),
                        }
                        self.presses.appendleft(press)
                        for cb in list(self.listeners):
                            try:
                                cb(press)
                            except Exception:
                                pass
                time.sleep(0.02)
        finally:
            try:
                pygame.joystick.quit()
                pygame.display.quit()
            except Exception:
                pass

    def status(self) -> dict:
        last = self.presses[0] if self.presses else None
        return {
            "available": self.available,
            "error": self.error,
            "devices": [dict(d, device_id=_device_id(d)) for d in list(self.devices.values())],
            "last": dict(last, ago=round(time.time() - last["at"], 1)) if last else None,
            "recent": [dict(p, ago=round(time.time() - p["at"], 1)) for p in list(self.presses)[:6]],
        }


def _device_id(d: dict) -> str | None:
    if not d.get("vid") or not d.get("pid"):
        return None
    return f"{d['vid']:04X}:{d['pid']:04X}"
