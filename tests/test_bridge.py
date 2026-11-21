"""The local bridge against a fake game that implements the action RPCs."""

import json
import threading
import time
import urllib.error
import urllib.request
from concurrent import futures
from pathlib import Path

import grpc
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from sevenhills_link import bridge as bridge_mod
from sevenhills_link import gamecfg
from sevenhills_link.actions import GameActions
from sevenhills_link.bridge import Bridge, state_from_frame

PKG = "sc.game.telemetry.v1"


def _fds():
    f = descriptor_pb2.FileDescriptorProto(name="sc/game/telemetry/v1/actions.proto", package=PKG, syntax="proto3")
    f.message_type.add(name="ListTriggerableActionsRequest")
    a = f.message_type.add(name="TriggerableAction")
    a.field.add(name="action_name", number=1, type=9, label=1)
    a.field.add(name="category", number=2, type=9, label=1)
    a.field.add(name="holdable", number=3, type=8, label=1)
    lr = f.message_type.add(name="ListTriggerableActionsResponse")
    lr.field.add(name="actions", number=1, type=11, label=3, type_name=f".{PKG}.TriggerableAction")
    t = f.message_type.add(name="TriggerGameActionRequest")
    t.field.add(name="action_name", number=1, type=9, label=1)
    t.field.add(name="hold_ms", number=2, type=13, label=1)
    f.message_type.add(name="TriggerGameActionResponse")
    s = f.service.add(name="GameTelemetryService")
    s.method.add(name="ListTriggerableActions", input_type=f".{PKG}.ListTriggerableActionsRequest", output_type=f".{PKG}.ListTriggerableActionsResponse")
    s.method.add(name="TriggerGameAction", input_type=f".{PKG}.TriggerGameActionRequest", output_type=f".{PKG}.TriggerGameActionResponse")
    fds = descriptor_pb2.FileDescriptorSet()
    fds.file.append(f)
    return fds


def _game(fds, received):
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fds.file[0])
    T = lambda n: message_factory.GetMessageClass(pool.FindMessageTypeByName(f"{PKG}.{n}"))
    TReq, LResp, TResp = T("TriggerGameActionRequest"), T("ListTriggerableActionsResponse"), T("TriggerGameActionResponse")

    def list_actions(req, ctx):
        r = LResp()
        r.actions.add(action_name="v_vtol_on", category="spaceship_movement")
        r.actions.add(action_name="v_self_destruct", category="spaceship_general")
        r.actions.add(action_name="v_invoke_ping", category="spaceship_radar", holdable=True)
        return r

    def trigger(req, ctx):
        received.append((req.action_name, req.hold_ms))
        return TResp()

    srv = grpc.server(futures.ThreadPoolExecutor(4))
    srv.add_generic_rpc_handlers([grpc.method_handlers_generic_handler(f"{PKG}.GameTelemetryService", {
        "ListTriggerableActions": grpc.unary_unary_rpc_method_handler(list_actions, request_deserializer=lambda b: b, response_serializer=lambda m: m.SerializeToString()),
        "TriggerGameAction": grpc.unary_unary_rpc_method_handler(trigger, request_deserializer=TReq.FromString, response_serializer=lambda m: m.SerializeToString()),
    })])
    port = srv.add_insecure_port("127.0.0.1:0")
    srv.start()
    return srv, port


FRAME = {
    "actor": {"state": {"locomotion": "ACTOR_LOCOMOTION_STATE_SEATED", "seat_name": "Pilot", "crew_role": "ACTOR_CREW_ROLE_PILOT"}},
    "vehicle": {"state": {"name": "ANVL_Hornet_123456789", "class_name": "ANVL_Hornet",
                          "flight": {"state": {"gear": "VEHICLE_COMPONENT_DEPLOYMENT_STATE_DEPLOYED", "is_landed": True}},
                          "master_mode": {"mode": "VEHICLE_MASTER_MODE_NAV", "spooled": False},
                          "power": {"engines": True, "weapons": False}, "shields": {"level": 0.5}}},
}


def _req(port, path, key=None, body=None, origin=None):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-7Hills-Key"] = key
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_state_from_frame():
    st = state_from_frame(FRAME)
    assert st["seated"] and st["ship"] == "ANVL_Hornet" and st["gear"] == "deployed" and st["master_mode"] == "nav"
    assert st["power"] == {"engines": True, "weapons": False} and st["crew_role"] == "pilot"
    assert state_from_frame(None) == {"in_game": False}


def test_bridge_end_to_end(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    received: list = []
    fds = _fds()
    game, gport = _game(fds, received)
    acts = GameActions(fds, gport)
    b = Bridge(lambda: FRAME, lambda: acts)
    b.cfg.port = _free_port()
    b.start()
    assert b.running
    port, key = b.cfg.port, b.cfg.key
    try:
        # No key, wrong key, and any web page are refused.
        assert _req(port, "/state")[0] == 401
        assert _req(port, "/state", key="nope")[0] == 401
        assert _req(port, "/state", key=key, origin="https://evil.example")[0] == 403
        assert _req(port, "/action", key=key, body={"name": "v_vtol_on"}, origin="null")[0] == 403

        code, st = _req(port, "/state", key=key)
        assert code == 200 and st["gear"] == "deployed"

        code, lst = _req(port, "/actions", key=key)
        names = {a["action_name"]: a for a in lst["actions"]}
        assert names["v_invoke_ping"]["holdable"] and names["v_self_destruct"]["blocked"]

        assert _req(port, "/action", key=key, body={"name": "v_vtol_on"})[0] == 200
        assert _req(port, "/action", key=key, body={"name": "v_invoke_ping", "hold_ms": 800})[0] == 200
        assert received == [("v_vtol_on", 0), ("v_invoke_ping", 800)]

        # Risky actions need the opt-in.
        assert _req(port, "/action", key=key, body={"name": "v_self_destruct"})[0] == 403
        assert ("v_self_destruct", 0) not in received
        b.cfg.allow_risky = True
        assert _req(port, "/action", key=key, body={"name": "v_self_destruct"})[0] == 200

        # Rate limit.
        time.sleep(1.1)
        codes = [_req(port, "/action", key=key, body={"name": "v_vtol_on"})[0] for _ in range(bridge_mod.MAX_PER_SECOND + 3)]
        assert 429 in codes and codes.count(200) <= bridge_mod.MAX_PER_SECOND

        assert b.status()["last"]["action"] == "v_vtol_on"
    finally:
        b.stop()
        acts.close()
        game.stop(0)
    assert not b.running


def test_config_persists_and_key_is_kept(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    b1 = Bridge(lambda: None, lambda: None)
    b1.cfg.enabled = True
    b1.cfg.save()
    b2 = Bridge(lambda: None, lambda: None)
    assert b2.cfg.enabled and b2.cfg.key == b1.cfg.key and not b2.cfg.allow_risky


def test_actions_line_only_when_bridge_is_on(tmp_path: Path):
    cfg = tmp_path / "user.cfg"
    cfg.write_text("grpc.client.server.enabled = 1\ngrpc.client.server.port = 50051\nserver.game.telemetry.enabled = 1\n")
    assert gamecfg.missing(cfg) == {}
    assert set(gamecfg.missing(cfg, with_actions=True)) == {gamecfg.ACTIONS_KEY}
    assert gamecfg.apply(cfg, with_actions=True) is True
    assert gamecfg.missing(cfg, with_actions=True) == {}


def test_virpil_devices_grouped(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from sevenhills_link import virpil

    class FakeHid:
        @staticmethod
        def enumerate(vid, pid):
            assert vid == 0x3344
            return [
                {"product_id": 0x4130, "serial_number": "FF01", "product_string": "VPC Stick MT-50CM2", "interface_number": 0},
                {"product_id": 0x4130, "serial_number": "FF01", "product_string": "", "interface_number": 1},
                {"product_id": 0x0259, "serial_number": "AA22", "product_string": "VPC Panel #2"},
            ]

    monkeypatch.setattr(virpil, "_hid", lambda: FakeHid)
    devs, err = virpil.list_devices()
    assert err is None
    assert [d["name"] for d in devs] == ["VPC Panel #2", "VPC Stick MT-50CM2"]
    assert devs[1]["id"] == "3344:4130:FF01"

    monkeypatch.setattr(virpil, "_hid", lambda: None)
    assert virpil.list_devices()[0] == [] and virpil.list_devices()[1]


def test_game_failed_status_is_an_error(tmp_path, monkeypatch):
    from sevenhills_link.actions import ActionError
    fds = _fds()
    f = fds.file[0]
    resp = next(m for m in f.message_type if m.name == "TriggerGameActionResponse")
    resp.field.add(name="status", number=1, type=9, label=1)
    received = []
    game, gport = _game(fds, received)
    acts = GameActions(fds, gport)
    import pytest
    # The fake game returns an empty status: treated as OK.
    assert acts.trigger("v_vtol_on") == {"status": ""}
    monkeypatch.setattr("sevenhills_link.actions.to_dict", lambda m: {"status": "TRIGGER_GAME_ACTION_STATUS_FAILED"})
    with pytest.raises(ActionError, match="FAILED"):
        acts.trigger("v_open_all_doors")
    acts.close(); game.stop(0)
