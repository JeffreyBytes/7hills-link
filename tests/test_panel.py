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
