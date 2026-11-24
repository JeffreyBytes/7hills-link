"""Where is the player? Read from the game's Game.log, turned into one place.

The game writes Game.log next to its exe (for example ...\\StarCitizen\\LIVE\\Game.log).
A few of its lines say where you are, roughly:

  <Join PU> ... shard[...]                      the shard you joined (a new session)
  <Planet CPU Maps Loaded> Planet '...'         a planet or moon being loaded; alone it
                                                means you are close to it, in a batch it
                                                is just streaming
  Added notification "Entered X Jurisdiction"   inside a planet company's space (UEE: none)
  Added notification "Entering/Leaving Armistice Zone"
  ATC '..._Port_Lawful-Orison'                  a port's air traffic control woke up
  <Update Inventory Location> ... Landing [a] -> [b]   arrived at / left a landing area

From these the tracker keeps one best guess, from most to least precise:
a port (city or station), a planet or moon, a planet's jurisdiction, the system.
Only the place id from places.json is sent to 7Net, with how sure it is, the
shard and the game's own location number. Never coordinates, never log lines.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from .paths import resource

BURST_S = 3.0           # planets loaded this close together are streaming, not where you are
PORT_HINT_S = 600.0     # an ATC hint counts for this long when you then land or enter armistice

RE_TS = re.compile(r"^<(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z>")
RE_JOIN = re.compile(r"<Join PU>.*?shard\[([^\]]+)\]")
RE_PLANET = re.compile(r"<Planet CPU Maps Loaded> Planet '([^']+)'")
RE_NOTICE = re.compile(r'<SHUDEvent_OnNotification> Added notification "([^"]*)')
RE_ATC = re.compile(r"<ATC_Reset_VehiclesBeingStoredCleared> ATC '([^']+)'")
RE_INV = re.compile(r"<Update Inventory Location>.*?Landing \[(\d+)\] -> \[(\d+)\]\. Location \[(\d+)\] -> \[(\d+)\]")
RE_JURIS = re.compile(r"^Entered (.+?) Jurisdiction", re.I)

# Jurisdiction notice text -> planet name in places.json. "UEE" is Stanton space
# outside the planet companies (Lagrange points, the space between planets).
JURISDICTION = {
    "hurston dynamics": "Hurston",
    "crusader industries": "Crusader",
    "arccorp": "ArcCorp",
    "microtech": "microTech",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _ts(line: str) -> float | None:
    m = RE_TS.match(line)
    if not m:
        return None
    try:
        return datetime.fromisoformat(m.group(1) + "+00:00").timestamp()
    except ValueError:
        return None


class Places:
    """The place list (data/places.json, the same file 7Net uses)."""

    def __init__(self, places: list[dict]) -> None:
        self.by_id = {p["id"]: p for p in places}
        # Planets and moons match the name the game uses for them exactly
        # (OOC_Stanton_2a_Cellin, pyro5a, Nyx1, ...).
        self.bodies: dict[str, str] = {}
        # Ports match as part of a longer name (ATC_DataManager_Port_Lawful-Orison):
        # cities, stations and rest stops, longest first, at least 5 letters.
        ports: list[tuple[str, str]] = []
        for p in places:
            keys = [_norm(k) for k in p.get("match", [])]
            if p["kind"] in ("planet", "moon"):
                for k in keys:
                    self.bodies.setdefault(k, p["id"])
            if p["kind"] in ("city", "station") or (p["kind"] == "lpoint" and p.get("station")):
                for k in keys:
                    if len(k) >= 5:
                        ports.append((k, p["id"]))
        self.ports = sorted(ports, key=lambda kv: -len(kv[0]))
        self.planets_by_name = {_norm(p["name"]): p["id"] for p in places if p["kind"] == "planet"}

    @classmethod
    def load(cls, path: Path | None = None) -> "Places":
        path = path or resource("data", "places.json")
        return cls(json.loads(Path(path).read_text(encoding="utf-8"))["places"])

    def body(self, game_name: str) -> str | None:
        return self.bodies.get(_norm(game_name))

    def port(self, text: str) -> str | None:
        t = _norm(text)
        return next((pid for k, pid in self.ports if k in t), None)

    def system_of(self, pid: str | None) -> str | None:
        return pid.split("/", 1)[0] if pid else None

    def within(self, pid: str | None, area: str | None) -> bool:
        return bool(pid and area and (pid == area or pid.startswith(area + "/")))

    def path_names(self, pid: str | None) -> list[str]:
        out = []
        while pid:
            p = self.by_id.get(pid)
            if not p:
                break
            out.insert(0, p["name"])
            pid = p.get("parent")
        return out


class Tracker:
    """Keeps the best guess of where the player is, fed one Game.log line at a time."""

    def __init__(self, places: Places) -> None:
        self.places = places
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.shard: str | None = None
        self.system: str | None = None
        self.jur_area: str | None = None      # planet id from the last jurisdiction notice
        self.body: str | None = None          # planet or moon loaded on its own
        self.port: str | None = None          # city or station
        self.armistice = False
        self.landing: str | None = None       # the game's landing-area number while inside one
        self.raw_id: str | None = None
        self._port_hint: tuple[float, str] | None = None
        self._landing_ports: dict[str, str] = {}   # landing-area number -> port, learnt this session
        self._pending: tuple[float, str, float] | None = None   # (log time, body, wall time)
        self._burst_until = 0.0

    # ------------------------------------------------------------ feeding

    def feed(self, line: str) -> None:
        ts = _ts(line)
        if ts is None:
            return
        with self._lock:
            self._settle(ts)
            m = RE_JOIN.search(line)
            if m:
                self.reset()
                self.shard = m.group(1)[:64]
                return
            m = RE_PLANET.search(line)
            if m:
                pid = self.places.body(m.group(1))
                if pid:
                    self._planet(ts, pid)
                return
            m = RE_NOTICE.search(line)
            if m:
                self._notice(ts, m.group(1))
                return
            m = RE_ATC.search(line)
            if m:
                pid = self.places.port(m.group(1))
                if pid:
                    self._port_hint = (ts, pid)
                    if self.landing:
                        self._landing_ports.setdefault(self.landing, pid)
                    if self.armistice or self.landing:
                        self._set_port(pid)
                return
            m = RE_INV.search(line)
            if m:
                _, landing_to, _, loc_to = m.groups()
                self.raw_id = loc_to if loc_to != "0" else None
                if landing_to != "0":
                    # Arrived in a landing area (a city or station): the port whose ATC
                    # woke up shortly before, or the one this number belonged to earlier.
                    self.landing = landing_to
                    pid = self._landing_ports.get(landing_to) or self._fresh_hint(ts)
                    if pid:
                        self._landing_ports[landing_to] = pid
                        self._set_port(pid)
                else:
                    self.landing = None
                    if not self.armistice:
                        self.port = None

    def tick(self) -> None:
        """Settle a lone planet load once nothing else came for a while (wall clock)."""
        with self._lock:
            if self._pending and time.time() - self._pending[2] >= BURST_S:
                self._set_body(self._pending[1])

    def _settle(self, ts: float) -> None:
        if self._pending and ts - self._pending[0] >= BURST_S:
            self._set_body(self._pending[1])

    def _set_body(self, pid: str) -> None:
        # Only a lone load says where you are; the batches at join load planets
        # of every system, so they set neither the body nor the system.
        self.body = pid
        self.system = self.places.system_of(pid)
        self._pending = None

    def _planet(self, ts: float, pid: str) -> None:
        if ts < self._burst_until:
            self._burst_until = ts + BURST_S
            return
        if self._pending and ts - self._pending[0] < BURST_S:
            self._pending = None
            self._burst_until = ts + BURST_S
            return
        self._pending = (ts, pid, time.time())

    def _notice(self, ts: float, text: str) -> None:
        m = RE_JURIS.match(text.strip())
        if m:
            who = m.group(1).strip()
            if who.upper() == "UEE":
                self.jur_area = None
                self.system = self.system or "stanton"
            else:
                pid = self.places.planets_by_name.get(_norm(JURISDICTION.get(who.lower(), who)))
                if pid:
                    self.jur_area = pid
                    self.system = self.places.system_of(pid)
                    if self.body and not self.places.within(self.body, pid):
                        self.body = None
            return
        low = text.lower()
        if low.startswith("entering armistice zone"):
            self.armistice = True
            pid = (self._landing_ports.get(self.landing) if self.landing else None) or self._fresh_hint(ts)
            if pid:
                self._set_port(pid)
        elif low.startswith("leaving armistice zone"):
            self.armistice = False
            # Still inside the landing area (flying around the city): keep the port.
            if not self.landing:
                self.port = None

    def _fresh_hint(self, ts: float) -> str | None:
        if self._port_hint and ts - self._port_hint[0] <= PORT_HINT_S:
            return self._port_hint[1]
        return None

    def _set_port(self, pid: str) -> None:
        self.port = pid
        self.system = self.places.system_of(pid)

    # ------------------------------------------------------------ reading

    def snapshot(self) -> dict | None:
        """What goes to 7Net: the best place and how sure it is, or None."""
        with self._lock:
            if self.port:
                pid, conf, src = self.port, "exact", "port"
            elif self.body:
                pid, conf, src = self.body, "near", "planet"
            elif self.jur_area:
                pid, conf, src = self.jur_area, "area", "jurisdiction"
            elif self.system:
                pid, conf, src = self.system, "system", "system"
            else:
                return None
            return {"place_id": pid, "confidence": conf, "source": src, "armistice": self.armistice,
                    "shard": self.shard, "raw_id": self.raw_id}

    def describe(self) -> str | None:
        snap = self.snapshot()
        if not snap:
            return None
        return " › ".join(self.places.path_names(snap["place_id"]))


class GameLogFollower:
    """Reads Game.log from the start, then follows it; starts over when the game makes a new one."""

    def __init__(self, path: Path, tracker: Tracker, poll: float = 1.0) -> None:
        self.path = Path(path)
        self.tracker = tracker
        self.poll = poll
        self.error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="gamelog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        pos = 0
        ident = None
        buf = b""
        while not self._stop.is_set():
            try:
                st = self.path.stat()
            except OSError:
                self.error = "no Game.log yet"
                self._stop.wait(self.poll * 5)
                continue
            now_ident = getattr(st, "st_birthtime", None) or st.st_ctime
            if ident is None or now_ident != ident or st.st_size < pos:
                # A new game start writes a new Game.log.
                if ident is not None:
                    self.tracker.reset()
                ident, pos, buf = now_ident, 0, b""
            if st.st_size > pos:
                try:
                    with open(self.path, "rb") as f:
                        f.seek(pos)
                        data = f.read(8 * 1024 * 1024)
                    pos += len(data)
                    buf += data
                    *lines, buf = buf.split(b"\n")
                    for raw in lines:
                        self.tracker.feed(raw.decode("utf-8", errors="replace"))
                    self.error = None
                except OSError as e:
                    self.error = str(e)[:200]
            self.tracker.tick()
            self._stop.wait(self.poll)
