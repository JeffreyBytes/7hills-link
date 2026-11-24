"""What is the player doing where they are? From the game's telemetry.

Game.log (location.py) says which place; the telemetry stream says what is
going on there. Together they answer "where am I" better than either alone:

  landed    seated in a ship that is landed
  flying    seated in a ship that has an altitude (so it is near a planet or moon)
  space     seated in a ship with no altitude (open space)
  on_foot   not seated; the game does not say whether inside a ship or outside
  eva       floating outside

Only that one word goes to 7Net with the place. The altitude is not sent
again: it is already in the ship's telemetry. The game flips "landed" a few
times while a ship settles, so a new state has to hold for a moment (Steady)
before it counts.
"""

from __future__ import annotations

STATES = ("landed", "flying", "space", "on_foot", "eva")
NO_ALTITUDE = 1e12      # the game sends FLT_MAX (about 3.4e38) as altitude in space
HOLD_S = 2.0            # a new state must last this long before it replaces the old one


def _tail(value, prefix: str) -> str:
    return str(value or "").replace(prefix, "").lower()


def altitude_of(frame: dict | None) -> float | None:
    """The ship's altitude above the ground in metres, or None (no ship, or in space)."""
    vs = ((frame or {}).get("vehicle") or {}).get("state") or {}
    alt = (((vs.get("flight") or {}).get("instruments")) or {}).get("altitude")
    if isinstance(alt, bool) or not isinstance(alt, (int, float)) or alt != alt or alt >= NO_ALTITUDE:
        return None
    return float(alt)


def state_of(frame: dict | None) -> str | None:
    """One of STATES for a telemetry frame, or None when it says nothing useful."""
    if not frame:
        return None
    st = (frame.get("actor") or {}).get("state") or {}
    loco = _tail(st.get("locomotion"), "ACTOR_LOCOMOTION_STATE_")
    vs = (frame.get("vehicle") or {}).get("state") or {}
    if loco == "seated" and vs.get("class_name"):
        if ((vs.get("flight") or {}).get("state") or {}).get("is_landed") is True:
            return "landed"
        return "flying" if altitude_of(frame) is not None else "space"
    if loco == "eva":
        return "eva"
    if loco and loco not in ("unspecified", "seated"):
        return "on_foot"
    # Seated with no ship data (the vehicle part can be empty in a seat): unknown.
    return None


class Steady:
    """Holds the state until a different one has lasted HOLD_S."""

    def __init__(self, hold: float = HOLD_S) -> None:
        self.hold = hold
        self.state: str | None = None
        self._next: tuple[str | None, float] | None = None

    def reset(self) -> None:
        self.state, self._next = None, None

    def feed(self, state: str | None, now: float) -> str | None:
        if state == self.state:
            self._next = None
        elif self.state is None and state is not None:
            self.state, self._next = state, None     # the first one counts at once
        elif self._next is None or self._next[0] != state:
            self._next = (state, now)
        elif now - self._next[1] >= self.hold:
            self.state, self._next = state, None
        return self.state


def altitude_text(m: float) -> str:
    return f"{m / 1000:.1f} km" if m >= 10000 else f"{round(m)} m"


def describe(state: str | None, confidence: str | None, place: str | None, altitude: float | None = None) -> str | None:
    """One line, worded as 7Net words it on /live (lib/live-situation.mjs).

    confidence: exact (a city or station), near (a planet or moon), area (a
    planet's jurisdiction), system.
    """
    if not state or not place:
        return None
    wide = confidence in ("area", "system")
    where = f"in the {place} area" if wide else f"at {place}"
    if state == "landed":
        return f"Landed {where}"
    if state == "flying":
        return f"Flying {where}" + (f", {altitude_text(altitude)} above the ground" if altitude is not None else "")
    if state == "space":
        return f"In space {where}" if wide else f"In space near {place}"
    if state == "on_foot":
        if wide:
            return f"On foot {where}"
        return f"On foot at {place}" if confidence == "exact" else f"On foot on or near {place}"
    if state == "eva":
        return f"On EVA {where}" if wide else f"On EVA near {place}"
    return None
