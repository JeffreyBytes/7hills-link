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
