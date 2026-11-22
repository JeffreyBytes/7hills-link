"""End to end without Windows: a fake game (gRPC) and a fake 7Net (HTTP)."""

import json
import threading
import time
from concurrent import futures
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import grpc
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

from sevenhills_link import api, core, detect, protoset
from sevenhills_link.stream import GameStream


def _fds():
    f = descriptor_pb2.FileDescriptorProto(name="sc/game/telemetry/v1/api.proto", package="sc.game.telemetry.v1", syntax="proto3")
    f.message_type.add(name="TelemetryStreamRequest")
    ev = f.message_type.add(name="GameEvent")
    ev.field.add(name="type", number=1, type=9, label=1)
    evf = f.message_type.add(name="EventsFrame")
    evf.field.add(name="events", number=1, type=11, label=3, type_name=".sc.game.telemetry.v1.GameEvent")
    r = f.message_type.add(name="TelemetryStreamResponse")
    r.field.add(name="speed", number=3, type=2, label=1)
    r.field.add(name="events", number=5, type=11, label=1, type_name=".sc.game.telemetry.v1.EventsFrame")
    s = f.service.add(name="GameTelemetryService")
    s.method.add(name="TelemetryStream", input_type=".sc.game.telemetry.v1.TelemetryStreamRequest", output_type=".sc.game.telemetry.v1.TelemetryStreamResponse", server_streaming=True)
    fds = descriptor_pb2.FileDescriptorSet()
    fds.file.append(f)
    return fds


def _game_server(fds):
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fds.file[0])
    Resp = message_factory.GetMessageClass(pool.FindMessageTypeByName("sc.game.telemetry.v1.TelemetryStreamResponse"))

    def stream(req, ctx):
        for i in range(10_000):
            m = Resp(speed=float(i))
            if i == 3:
                m.events.events.add(type="GAME_EVENT_TYPE_ACTOR_ENTER_SEAT")
            yield m
            time.sleep(0.02)

    srv = grpc.server(futures.ThreadPoolExecutor(4))
    srv.add_generic_rpc_handlers([grpc.method_handlers_generic_handler("sc.game.telemetry.v1.GameTelemetryService", {
        "TelemetryStream": grpc.unary_stream_rpc_method_handler(stream, request_deserializer=lambda b: b, response_serializer=lambda m: m.SerializeToString()),
    })])
    port = srv.add_insecure_port("127.0.0.1:0")
    srv.start()
    return srv, port


class FakeNet(BaseHTTPRequestHandler):
    ingests: list = []
    approved = False

    def log_message(self, *a):
        pass

    def _json(self, code, body):
        b = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/telemetry/link/start":
            return self._json(200, {"code": "ABCD-2345", "poll_secret": "s", "url": "http://x/link?code=ABCD-2345", "expires_in": 60})
        if self.path == "/api/telemetry/link/poll":
            return self._json(200, {"status": "linked", "token": "7hl_test", "device_name": "PC"} if FakeNet.approved else {"status": "pending"})
        if self.path == "/api/telemetry/ingest":
            if self.headers.get("Authorization") != "Bearer 7hl_test":
                return self._json(401, {"error": "Unauthorized"})
            FakeNet.ingests.append(body)
            return self._json(200, {"ok": True})
        self._json(404, {})

    def do_GET(self):
        if self.path == "/api/telemetry/device/settings":
            return self._json(200, {"settings": {"share_org": False}, "member": {"handle": "TheBanjolorian"}, "device": {"name": "PC"}})
        self._json(404, {})

    do_PATCH = do_GET


def test_stream_and_upload(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    fds = _fds()
    game, gport = _game_server(fds)
    web = ThreadingHTTPServer(("127.0.0.1", 0), FakeNet)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    monkeypatch.setattr(api, "BASE", f"http://127.0.0.1:{web.server_address[1]}")
    monkeypatch.setattr(api, "load_token", lambda: None)
    monkeypatch.setattr(api, "save_token", lambda t: None)
    monkeypatch.setattr(core.webbrowser, "open", lambda url: None)

    # Pretend there is one install whose exe yields our descriptors.
    inst = detect.Install("PTU", tmp_path / "PTU")
    (tmp_path / "PTU" / "Bin64").mkdir(parents=True)
    inst.exe.write_bytes(b"x")
    inst.user_cfg.write_text(f"grpc.client.server.enabled = 1\ngrpc.client.server.port = {gport}\nserver.game.telemetry.enabled = 1\n")
    monkeypatch.setattr(detect, "find_installs", lambda extra_roots=None: [inst])
    monkeypatch.setattr(detect, "running_channel", lambda: "PTU")
    monkeypatch.setattr(protoset, "load", lambda exe: fds)
    monkeypatch.setattr(core.gamecfg, "env_enabled", lambda: True)
    monkeypatch.setattr(core, "MIN_GAP", 0.2)

    c = core.Core()
    t = threading.Thread(target=c.run, daemon=True)
    t.start()
    time.sleep(1)
    st = c.status()
    assert st["game_found"] and st["cfg_ok"] and st["game_connected"] and not st["linked"]

    c.start_link()
    assert c.status()["link"]["code"] == "ABCD-2345"
    FakeNet.approved = True
    time.sleep(3)
    st = c.status()
    assert st["linked"] and st["member"]["handle"] == "TheBanjolorian"

    time.sleep(1.5)
    assert FakeNet.ingests, "nothing uploaded"
    last = FakeNet.ingests[-1]
    assert last["frame"]["speed"] > 0 and last["client_version"]
    assert any("GAME_EVENT_TYPE_ACTOR_ENTER_SEAT" in b["events"] for b in FakeNet.ingests)
    c.stop()
    game.stop(0)
    web.shutdown()


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_stream_falls_back_to_the_port_that_answers():
    """The game may ignore the user.cfg port (4.x LIVE serves on 2942): try the next one and stay there."""
    fds = _fds()
    game, gport = _game_server(fds)
    dead = _free_port()
    s = GameStream(fds, [dead, gport])
    s.start()
    try:
        for _ in range(100):
            if s.connected:
                break
            time.sleep(0.1)
        assert s.connected and s.port == gport and s.error is None
    finally:
        s.stop()
        game.stop(0)
