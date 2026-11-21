"""Send triggerable actions to the game (ListTriggerableActions / TriggerGameAction).

Request and response types come from the descriptors read out of StarCitizen.exe,
so field names follow the installed build. The game only accepts actions when
user.cfg has server.game.telemetry.trigger.actions.enabled = 1.
"""

from __future__ import annotations

import threading
import time

import grpc
from google.protobuf import descriptor_pool, message_factory

from .protoset import SERVICE
from .stream import to_dict


class ActionError(Exception):
    pass


class GameActions:
    def __init__(self, fds, port: int):
        pool = descriptor_pool.DescriptorPool()
        for f in fds.file:
            pool.Add(f)
        self._svc = pool.FindServiceByName(SERVICE)
        self.port = port
        self._channel: grpc.Channel | None = None
        self._lock = threading.Lock()
        self._list_cache: tuple[float, list[dict]] | None = None

    def _method(self, name: str):
        m = self._svc.methods_by_name.get(name)
        if m is None:
            raise ActionError(f"This game build has no {name}")
        Req = message_factory.GetMessageClass(m.input_type)
        Resp = message_factory.GetMessageClass(m.output_type)
        with self._lock:
            if self._channel is None:
                self._channel = grpc.insecure_channel(f"127.0.0.1:{self.port}")
            ch = self._channel
        call = ch.unary_unary(f"/{SERVICE}/{name}", request_serializer=lambda x: x.SerializeToString(), response_deserializer=Resp.FromString)
        return Req, call

    def list(self, max_age: float = 30.0) -> list[dict]:
        """The actions this build accepts: [{action_name, category, holdable}]."""
        if self._list_cache and time.time() - self._list_cache[0] < max_age:
            return self._list_cache[1]
        Req, call = self._method("ListTriggerableActions")
        try:
            resp = to_dict(call(Req(), timeout=3))
        except grpc.RpcError as e:
            raise ActionError(_rpc_text(e)) from e
        items = next((v for v in resp.values() if isinstance(v, list)), [])
        out = [{"action_name": a.get("action_name"), "category": a.get("category"), "holdable": bool(a.get("holdable"))}
               for a in items if isinstance(a, dict) and a.get("action_name")]
        self._list_cache = (time.time(), out)
        return out

    def trigger(self, name: str, hold_ms: int = 0) -> dict:
        Req, call = self._method("TriggerGameAction")
        fields = {f.name for f in Req.DESCRIPTOR.fields}
        req = Req()
        if "action_name" not in fields:
            raise ActionError("Unexpected TriggerGameAction request in this build")
        req.action_name = name
        if hold_ms and "hold_ms" in fields:
            req.hold_ms = int(hold_ms)
        try:
            return to_dict(call(req, timeout=3))
        except grpc.RpcError as e:
            raise ActionError(_rpc_text(e)) from e

    def close(self) -> None:
        with self._lock:
            if self._channel is not None:
                self._channel.close()
                self._channel = None


def _rpc_text(e: grpc.RpcError) -> str:
    try:
        code = e.code().name
        detail = e.details() or ""
    except Exception:
        return str(e)[:200]
    if code == "UNAVAILABLE":
        return "Game not reachable (is it running with telemetry on?)"
    if code in ("PERMISSION_DENIED", "FAILED_PRECONDITION", "UNIMPLEMENTED"):
        return f"{code}: actions may be switched off in user.cfg ({detail[:120]})"
    return f"{code}: {detail[:160]}"
