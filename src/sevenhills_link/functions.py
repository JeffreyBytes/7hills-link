"""What a panel button can do, and what its LED shows.

Each function knows the game actions it sends and how to read its state from
the bridge's compact state (bridge.state_from_frame). State is True (on),
False (off), "moving" (gear/VTOL on the way), or None (not known right now,
e.g. not seated, or the game does not report it).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

GREEN, RED, AMBER, BLUE, VIOLET, CYAN, WHITE, DIM, OFF = "00FF00", "FF0000", "FF8000", "0040FF", "8000FF", "00FFFF", "FFFFFF", "404040", "000000"
WARN = ("major_on", "minor_on", "on")


@dataclass(frozen=True)
class Function:
    id: str
    group: str
    label: str
    kind: str                               # state | action | led (LED only, no button)
    on: str | None = None                   # action that turns it on
    off: str | None = None                  # action that turns it off
    toggle: str | None = None               # fallback when the state is unknown / momentary action
    state: Callable[[dict], object] | None = None
    on_color: str = GREEN
    off_color: str = RED
    hold_ms: int = 0
    risky: bool = False                     # needs a 1 s hold on the button
    blink_when_on: bool = False             # warnings
    note: str = field(default="")


def _seated(st: dict) -> bool:
    return bool(st.get("seated"))


def _deploy(key: str):
    def f(st: dict):
        if not _seated(st):
            return None
        v = st.get(key)
        if v == "deployed":
            return True
        if v == "retracted":
            return False
        if v in ("deploying", "retracting"):
            return "moving"
        return None
    return f


def _power(key: str):
    def f(st: dict):
        if not _seated(st):
            return None
        v = (st.get("power") or {}).get(key)
        return v if isinstance(v, bool) else None
    return f


def _flag(key: str, src: str | None = None):
    def f(st: dict):
        if not _seated(st):
            return None
        d = st.get(src) if src else st
        v = (d or {}).get(key)
        return v if isinstance(v, bool) else None
    return f


def _warn(key: str):
    def f(st: dict):
        if not _seated(st):
            return None
        v = (st.get("annunciators") or {}).get(key)
        return None if v is None else v in WARN
    return f


def _master(st: dict):
    if not _seated(st):
        return None
    m = st.get("master_mode")
    return True if m == "scm" else False if m == "nav" else None


def _flight_ready(st: dict):
    if not _seated(st):
        return None
    p = st.get("power") or {}
    return bool(p.get("powerplants") and p.get("engines"))


def _num_below(key: str, limit: float):
    def f(st: dict):
        if not _seated(st):
            return None
        v = st.get(key)
        return v < limit if isinstance(v, (int, float)) else None
    return f


FUNCTIONS: list[Function] = [
    # Flight
    Function("gear", "Flight", "Landing gear", "state", "v_deploy_landing_system", "v_retract_landing_system", "v_toggle_landing_system", _deploy("gear"), GREEN, RED),
    Function("vtol", "Flight", "VTOL", "state", "v_vtol_on", "v_vtol_off", "v_vtol_toggle", _deploy("vtol"), GREEN, DIM),
    Function("master", "Flight", "SCM / NAV mode", "state", "v_master_mode_set_scm", "v_master_mode_set_nav", "v_master_mode_cycle", _master, RED, BLUE, note="On = SCM, off = NAV"),
    Function("quantum", "Flight", "Quantum drive", "state", None, None, "v_toggle_qdrive_engagement", _flag("quantum_spooled"), BLUE, DIM),
    Function("decoupled", "Flight", "Decoupled mode", "action", "v_ifcs_vector_decoupling_on", "v_ifcs_vector_decoupling_off", "v_ifcs_vector_decoupling_toggle", None, VIOLET, DIM, note="The game does not report this state; the LED shows what the switch last sent"),
    Function("gsafe", "Flight", "G-safe", "action", "v_ifcs_gsafe_on", "v_ifcs_gsafe_off", "v_ifcs_toggle_gforce_safety", None, GREEN, DIM),
    Function("prox", "Flight", "Proximity assist", "action", "v_ifcs_proximity_assist_on", "v_ifcs_proximity_assist_off", "v_ifcs_proximity_assist_toggle", None, GREEN, DIM),
    Function("atc", "Flight", "ATC / landing request", "action", toggle="v_atc_request", on_color=CYAN, off_color=DIM),
    Function("dock", "Flight", "Docking request", "action", toggle="v_toggle_docking_request", on_color=CYAN, off_color=DIM),
    # Power
    Function("power", "Power", "Ship power", "state", "v_power_set_on", "v_power_set_off", "v_power_toggle", _power("powerplants"), GREEN, RED),
    Function("shields", "Power", "Shields", "state", "v_power_set_shields_on", "v_power_set_shields_off", "v_power_toggle_shields", _power("shield_generators"), BLUE, RED),
    Function("thrusters", "Power", "Thrusters", "state", "v_power_set_thrusters_on", "v_power_set_thrusters_off", "v_power_toggle_thrusters", _power("engines"), GREEN, RED),
    Function("weapons", "Power", "Weapons", "state", "v_power_set_weapons_on", "v_power_set_weapons_off", "v_power_toggle_weapons", _power("weapons"), AMBER, DIM),
    # Ship
    Function("flightready", "Ship", "Flight ready", "action", toggle="v_flightready", state=_flight_ready, on_color=GREEN, off_color=AMBER),
    Function("lights", "Ship", "Lights", "state", "v_lights_on", "v_lights_off", "v_lights", _flag("lights"), WHITE, DIM),
    Function("doors_open", "Ship", "Open / close all doors", "action", "v_open_all_doors", "v_close_all_doors", "v_toggle_all_doors", None, GREEN, DIM),
    Function("doors_lock", "Ship", "Lock / unlock all doors", "action", "v_lock_all_doors", "v_unlock_all_doors", "v_toggle_all_doorlocks", None, RED, GREEN),
    Function("ports_lock", "Ship", "Lock / unlock ports", "action", "v_lock_all_ports", "v_unlock_all_ports", "v_toggle_all_portlocks", None, RED, GREEN),
    # Seat
    Function("nightvision", "Seat", "Night vision", "state", "v_light_amplification_on", "v_light_amplification_off", "v_light_amplification_toggle", _flag("flight_light_amplification", "ifcs"), GREEN, DIM),
    Function("mode_guns", "Seat", "Guns mode", "action", toggle="v_set_guns_mode", on_color=AMBER, off_color=DIM),
    Function("mode_scan", "Seat", "Scan mode", "action", toggle="v_set_scan_mode", on_color=CYAN, off_color=DIM),
    Function("mode_mining", "Seat", "Mining mode", "action", toggle="v_set_mining_mode", on_color=VIOLET, off_color=DIM),
    Function("mode_salvage", "Seat", "Salvage mode", "action", toggle="v_set_salvage_mode", on_color=VIOLET, off_color=DIM),
    Function("mode_quantum", "Seat", "Quantum mode", "action", toggle="v_set_quantum_mode", on_color=BLUE, off_color=DIM),
    Function("eject", "Seat", "Eject", "action", toggle="v_eject", on_color=RED, off_color=RED, risky=True),
    Function("self_destruct", "Seat", "Self-destruct", "action", toggle="v_self_destruct", on_color=RED, off_color=RED, risky=True),
    # Combat
    Function("ping", "Combat", "Radar ping (hold)", "action", toggle="v_invoke_ping", on_color=CYAN, off_color=DIM, hold_ms=800),
    Function("hail", "Combat", "Hail target", "action", toggle="v_target_hail", on_color=CYAN, off_color=DIM),
    # Player
    Function("mobiglas", "Player", "mobiGlas", "action", toggle="mobiglas", on_color=CYAN, off_color=DIM),
    Function("flashlight", "Player", "Flashlight", "action", toggle="toggle_flashlight", on_color=WHITE, off_color=DIM),
    Function("starmap", "Player", "Star map", "action", toggle="v_starmap", on_color=CYAN, off_color=DIM),
    # LED only
    Function("warn_missile", "Warnings (LED only)", "Missile warning", "led", state=_warn("misl"), on_color=RED, off_color=OFF, blink_when_on=True),
    Function("warn_hit", "Warnings (LED only)", "Taking hits", "led", state=_warn("hit"), on_color=RED, off_color=OFF, blink_when_on=True),
    Function("warn_shields", "Warnings (LED only)", "Shields low", "led", state=_num_below("shields", 0.1), on_color=RED, off_color=OFF, blink_when_on=True),
    Function("warn_hull", "Warnings (LED only)", "Hull below 50%", "led", state=_num_below("hull", 0.5), on_color=AMBER, off_color=OFF),
    Function("seated", "Warnings (LED only)", "Seated in a ship", "led", state=lambda st: bool(st.get("seated")) if st.get("in_game") else None, on_color=GREEN, off_color=OFF),
]

BY_ID = {f.id: f for f in FUNCTIONS}


def catalog() -> list[dict]:
    """For the window: grouped list with defaults."""
    return [{"id": f.id, "group": f.group, "label": f.label, "kind": f.kind, "on_color": f.on_color, "off_color": f.off_color,
             "risky": f.risky, "has_state": f.state is not None, "has_on_off": bool(f.on and f.off), "note": f.note} for f in FUNCTIONS]
