from pathlib import Path

from google.protobuf import descriptor_pb2

from sevenhills_link import gamecfg, protoset
from sevenhills_link.core import _summary


def test_patch_keeps_other_lines_and_replaces_wrong_values(tmp_path: Path):
    cfg = tmp_path / "user.cfg"
    cfg.write_text("r_DisplayInfo = 0\n-- comment\nserver.game.telemetry.enabled = 0\n")
    assert set(gamecfg.missing(cfg)) == {"grpc.client.server.enabled", "grpc.client.server.port", "server.game.telemetry.enabled"}
    assert gamecfg.apply(cfg) is True
    text = cfg.read_text()
    assert "r_DisplayInfo = 0" in text and "-- comment" in text
    assert "server.game.telemetry.enabled = 1" in text and "server.game.telemetry.enabled = 0" not in text
    assert gamecfg.missing(cfg) == {}
    assert gamecfg.apply(cfg) is False


def test_player_port_is_kept(tmp_path: Path):
    cfg = tmp_path / "user.cfg"
    cfg.write_text("grpc.client.server.port = 50999\n")
    assert "grpc.client.server.port" not in gamecfg.missing(cfg)
    assert gamecfg.port_of(cfg) == 50999


def _fake_exe(tmp_path: Path) -> Path:
    types = descriptor_pb2.FileDescriptorProto(name="sc/game/telemetry/v1/types.proto", package="sc.game.telemetry.v1", syntax="proto3")
    types.message_type.add(name="VehicleFrame")
    api = descriptor_pb2.FileDescriptorProto(name="sc/game/telemetry/v1/api.proto", package="sc.game.telemetry.v1", syntax="proto3", dependency=["sc/game/telemetry/v1/types.proto"])
    api.message_type.add(name="TelemetryStreamRequest")
    r = api.message_type.add(name="TelemetryStreamResponse")
    r.field.add(name="vehicle", number=3, type=11, label=1, type_name=".sc.game.telemetry.v1.VehicleFrame")
    s = api.service.add(name="GameTelemetryService")
    s.method.add(name="TelemetryStream", input_type=".sc.game.telemetry.v1.TelemetryStreamRequest", output_type=".sc.game.telemetry.v1.TelemetryStreamResponse", server_streaming=True)
    exe = tmp_path / "StarCitizen.exe"
    # api first in the file, so the extractor has to order dependencies itself
    exe.write_bytes(b"\x00junk" * 500 + api.SerializeToString() + b"\xff\xfe" * 100 + types.SerializeToString() + b"\xff\xff\xff tail")
    return exe


def test_protoset_extracts_and_orders(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    exe = _fake_exe(tmp_path)
    fds = protoset.load(exe)
    assert [f.name for f in fds.file] == ["sc/game/telemetry/v1/types.proto", "sc/game/telemetry/v1/api.proto"]
    assert protoset.has_service(fds)
    assert any(p.name.startswith("protoset-") for p in (tmp_path / "7HillsLink").iterdir())


def test_summary():
    frame = {"actor": {"state": {"locomotion": "ACTOR_LOCOMOTION_STATE_SEATED", "seat_name": "X"}},
             "vehicle": {"state": {"class_name": "AEGS_Idris_M", "flight": {"state": {"gear": "VEHICLE_COMPONENT_DEPLOYMENT_STATE_RETRACTED"}},
                                   "master_mode": {"mode": "VEHICLE_MASTER_MODE_SCM"}, "power": {"powerplants": True, "engines": True}}}}
    s = _summary(frame)
    assert s["ship"] == "AEGS Idris M" and s["gear"] == "retracted" and s["mode"] == "SCM" and s["power_on"]


def test_uploads_on_change_at_most_4_per_second(tmp_path, monkeypatch):
    import threading, time
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from sevenhills_link import core as core_mod

    class FakeStream:
        connected = True
        def __init__(self):
            self.lock = threading.Lock(); self.frame = {"n": 0}; self.at = time.time(); self.events = []
        def pending(self, since):
            with self.lock: return self.at > since, bool(self.events)
        def take(self):
            with self.lock:
                ev, self.events = self.events, []
                return dict(self.frame), self.at, ev
        def stop(self): pass

    sent = []
    monkeypatch.setattr(core_mod.api, "ingest", lambda token, frame, events: sent.append((time.time(), frame, events)))
    c = core_mod.Core()
    monkeypatch.setattr(c, "scan", lambda: None)
    monkeypatch.setattr(c, "ensure_stream", lambda: None)
    monkeypatch.setattr(c, "refresh_settings", lambda force=False: None)
    c.token = "7hl_test"
    s = FakeStream(); c.stream = s
    t = threading.Thread(target=c.run, daemon=True); t.start()
    # 2 s: the frame changes 20 times a second for 1 s, then stays the same.
    end = time.time() + 1.0
    while time.time() < end:
        with s.lock: s.frame = {"n": s.frame["n"] + 1}; s.at = time.time()
        time.sleep(0.05)
    with s.lock: s.events.append("GAME_EVENT_TYPE_ACTOR_ENTER_SEAT"); s.at = time.time()
    time.sleep(1.0)
    c.stop()
    changing = [x for x in sent if x[0] < end + 0.01]
    assert 3 <= len(changing) <= 5, len(changing)                 # ~4 a second, not 20
    assert any("GAME_EVENT_TYPE_ACTOR_ENTER_SEAT" in e for _, _, e in sent)
    assert len(sent) <= len(changing) + 1                         # unchanged frame is not resent
    gaps = [b[0] - a[0] for a, b in zip(sent, sent[1:])]
    assert min(gaps) >= 0.24


def test_sound_and_prefs_survive_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from sevenhills_link import core as core_mod
    c = core_mod.Core()
    assert c.status()["sound"] == {"muted": False, "volume": 0.6}
    assert c.status()["prefs"] == {"start_with_windows": True, "tray": True, "play_on_start": True}
    c.prefs.set("play_on_start", False)
    c.prefs.set("start_with_windows", False)          # no registry outside the packaged exe
    c.set_sound(muted=True, volume=1.7)
    c2 = core_mod.Core()
    assert c2.sound_muted and c2.sound_volume == 1.0
    assert c2.prefs.as_dict() == {"start_with_windows": False, "tray": True, "play_on_start": False}
