"""LED command building and joystick id parsing (no hardware needed)."""

from pathlib import Path

import pytest

from sevenhills_link import leds
from sevenhills_link.panel_input import vid_pid_from_guid


def test_snap_to_virpil_levels():
    assert leds.snap("#00FF00") == ("00", "FF", "00")
    assert leds.snap("12a0ff") == ("00", "80", "FF")
    assert leds.snap("606060") == ("40", "40", "40")
    with pytest.raises(ValueError):
        leds.snap("fff")


def test_command(tmp_path: Path):
    tool = tmp_path / "VPC_LED_Control.exe"
    assert leds.command(tool, "3344:80CC:FF01", 5, "FF0000") == [str(tool), "3344", "80CC", "5", "FF", "00", "00"]
    with pytest.raises(ValueError):
        leds.command(tool, "nonsense", 1, "FF0000")


def test_run_without_tool():
    ok, text = leds.run(None, "3344:80CC", 1, "FF0000")
    assert not ok and "not found" in text


def test_find_tool(tmp_path: Path, monkeypatch):
    d = tmp_path / "VPC Software Suite" / "tools"
    d.mkdir(parents=True)
    (d / "VPC_LED_Control.exe").write_bytes(b"x")
    (tmp_path / "Other").mkdir()
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "none"))
    assert leds.find_tool() == d / "VPC_LED_Control.exe"


def test_guid():
    # SDL GUID: bus 0x0003 (USB), vendor 0x3344, product 0x80CC, little-endian
    assert vid_pid_from_guid("03000000" "4433" "0000" "cc80" "0000" "00000000") == (0x3344, 0x80CC)
    assert vid_pid_from_guid("bad") == (None, None)


# ---------------------------------------------------------------- panel engine

import time as _time

from sevenhills_link import scbinds
from sevenhills_link.panel import PanelEngine


class FakeActions:
    def __init__(self):
        self.sent = []

    def trigger(self, name, hold=0):
        self.sent.append((name, hold))
        return {}


def _engine(tmp_path, monkeypatch, state):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    acts = FakeActions()
    led_calls = []
    eng = PanelEngine(lambda: state, lambda: acts, lambda: "tool", led_runner=lambda tool, dev, n, c: (led_calls.append((dev, n, c)) or (True, "")))
    eng.start()
    return eng, acts, led_calls


def _press(eng, button, pressed=True, dev="3344:0259"):
    eng.on_button({"device": "VPC Panel #2", "device_id": dev, "button": button, "pressed": pressed, "at": _time.time()})


def test_learn_and_push_button_follows_game(tmp_path, monkeypatch):
    state = {"in_game": True, "seated": True, "gear": "deployed", "power": {"shield_generators": False}}
    eng, acts, leds_ = _engine(tmp_path, monkeypatch, state)
    eng.start_learn()
    _press(eng, 7)
    _time.sleep(0.2)
    assert eng.learn["button"] == 7 and eng.learn["device_id"] == "3344:0259"
    eng.save_mapping({"device_id": "3344:0259:AA22", "device_name": "VPC Panel #2", "button": 7, "function": "gear", "led": 7})
    assert eng.learn is None and eng.cfg.mappings[0]["device_id"] == "3344:0259"

    _press(eng, 7)              # gear is down -> retract
    _time.sleep(0.3)
    state["gear"] = "retracted"
    _press(eng, 7)              # gear is up -> deploy
    _time.sleep(0.6)
    assert [a for a, _ in acts.sent] == ["v_retract_landing_system", "v_deploy_landing_system"]
    # LED went to the off colour (red) when the gear was up
    assert ("3344:0259", 7, "FF0000") in leds_
    eng.stop()


def test_switch_and_risky_hold(tmp_path, monkeypatch):
    state = {"in_game": True, "seated": True}
    eng, acts, _ = _engine(tmp_path, monkeypatch, state)
    eng.save_mapping({"device_id": "3344:0259", "button": 1, "function": "decoupled", "mode": "switch"})
    eng.save_mapping({"device_id": "3344:0259", "button": 2, "function": "eject"})
    _press(eng, 1, True); _press(eng, 1, False)
    _press(eng, 2, True); _time.sleep(0.3); _press(eng, 2, False)   # too short: nothing
    _press(eng, 2, True); _time.sleep(1.3)
    sent = [a for a, _ in acts.sent]
    assert sent == ["v_ifcs_vector_decoupling_on", "v_ifcs_vector_decoupling_off", "v_eject"]
    eng.stop()


def test_leds_released_when_game_stops(tmp_path, monkeypatch):
    state = {"in_game": True, "seated": True, "lights": True}
    eng, _, leds_ = _engine(tmp_path, monkeypatch, state)
    eng.save_mapping({"device_id": "3344:0259", "button": 3, "function": "lights", "led": 3, "on_color": "FFFFFF"})
    _time.sleep(0.4)
    assert ("3344:0259", 3, "FFFFFF") in leds_
    state["in_game"] = False
    _time.sleep(0.4)
    assert leds_[-1][1] == 0    # reset to the device's own profile
    eng.stop()


def test_scbinds(tmp_path):
    p = scbinds.actionmaps_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text("""<ActionMaps><ActionProfiles>
      <options type="joystick" instance="2" Product=" VPC Panel #2  {02593344-0000-0000-0000-504944564944}"/>
      <actionmap name="spaceship_movement"><action name="v_toggle_landing_system"><rebind input="js2_button7"/></action></actionmap>
    </ActionProfiles></ActionMaps>""")
    assert scbinds.bindings(tmp_path) == {"3344:0259": {7: ["v_toggle_landing_system"]}}
