"""Linux / Wine: finding the game inside prefixes, --game-dir, and the launch-env check."""

import os
from pathlib import Path

import pytest

from sevenhills_link import detect, gamecfg
from sevenhills_link.__main__ import _take_game_dirs

linux_only = pytest.mark.skipif(os.name == "nt", reason="Wine prefixes are a Linux thing")


def _channel(root: Path, ch: str) -> Path:
    exe = root / ch / "Bin64" / "StarCitizen.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    return exe


def _prefix(base: Path) -> tuple[Path, Path]:
    root = base / "drive_c" / "Program Files" / "Roberts Space Industries" / "StarCitizen"
    _channel(root, "LIVE")
    _channel(root, "PTU")
    return base, root


def test_wine_to_unix(tmp_path: Path):
    p = detect.wine_to_unix(r"C:\Program Files\Roberts Space Industries\StarCitizen", tmp_path)
    assert p == tmp_path / "drive_c" / "Program Files" / "Roberts Space Industries" / "StarCitizen"
    assert detect.wine_to_unix(r"C:\\Games\\StarCitizen", tmp_path) == tmp_path / "drive_c" / "Games" / "StarCitizen"
    assert detect.wine_to_unix(r"Z:\home\me\sc", tmp_path) == Path("/home/me/sc")
    assert detect.wine_to_unix("not a path", tmp_path) is None


def test_roots_for_accepts_root_channel_exe_and_prefix(tmp_path: Path):
    prefix, root = _prefix(tmp_path / "pfx")
    assert detect.roots_for(root) == [root]
    assert detect.roots_for(root / "PTU") == [root]
    assert detect.roots_for(root / "LIVE" / "Bin64" / "StarCitizen.exe") == [root]
    assert root in detect.roots_for(prefix)


def test_game_dir_env_finds_installs(tmp_path: Path, monkeypatch):
    _, root = _prefix(tmp_path / "pfx")
    monkeypatch.setenv(detect.ENV_DIR, str(root / "LIVE"))
    monkeypatch.setattr(detect, "launcher_roots", lambda: [])
    monkeypatch.setattr(detect, "common_roots", lambda: [])
    monkeypatch.setattr(detect, "running_game_folders", lambda: [])
    found = detect.find_installs()
    assert [i.channel for i in found] == ["LIVE", "PTU"]
    assert detect.find_installs([]) == []   # an explicit empty list does not read the env


@linux_only
def test_prefix_under_home_is_scanned(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("WINEPREFIX", raising=False)
    monkeypatch.delenv(detect.ENV_DIR, raising=False)
    monkeypatch.setattr(detect, "running_game_folders", lambda: [])
    _, root = _prefix(tmp_path / "Games" / "star-citizen")
    assert tmp_path / "Games" / "star-citizen" in detect.wine_prefixes()
    found = detect.find_installs()
    assert {i.channel for i in found} == {"LIVE", "PTU"}
    assert all(str(i.folder).startswith(str(root)) for i in found)


@linux_only
def test_launcher_paths_are_mapped_into_the_prefix(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("WINEPREFIX", raising=False)
    prefix = tmp_path / "Games" / "sc"
    root = prefix / "drive_c" / "Games" / "RSI" / "StarCitizen"
    _channel(root, "LIVE")
    launcher = prefix / "drive_c" / "users" / "me" / "AppData" / "Roaming" / "rsilauncher"
    launcher.mkdir(parents=True)
    (launcher / "settings.json").write_text('{"library":"C:\\\\Games\\\\RSI\\\\StarCitizen"}')
    assert root in detect.launcher_roots()


def test_take_game_dirs():
    argv = ["--headless", "--game-dir", "/a", "--game-dir=/b c"]
    assert _take_game_dirs(argv) == ["/a", "/b c"]
    assert argv == ["--headless"]


@linux_only
def test_env_check_reads_the_running_game(monkeypatch):
    monkeypatch.delenv(gamecfg.ENV_NAME, raising=False)
    monkeypatch.setattr(detect, "running_game_env", lambda name: None)
    assert gamecfg.env_enabled() is None          # nothing to check yet
    monkeypatch.setattr(detect, "running_game_env", lambda name: "true")
    assert gamecfg.env_enabled() is True
    monkeypatch.setattr(detect, "running_game_env", lambda name: "0")
    assert gamecfg.env_enabled() is False
    assert gamecfg.env_manual() is True
    assert gamecfg.enable_env() is False
