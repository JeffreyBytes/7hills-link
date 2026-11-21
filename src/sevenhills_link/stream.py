"""Read the game's TelemetryStream and keep the latest frame for the uploader."""

from __future__ import annotations

import threading
import time

import grpc
from google.protobuf import descriptor_pool, json_format, message_factory

from .protoset import SERVICE

METHOD = f"/{SERVICE}/TelemetryStream"


def to_dict(msg) -> dict:
    try:
        return json_format.MessageToDict(msg, always_print_fields_with_no_presence=True, preserving_proto_field_name=True)
    except TypeError:  # older protobuf
        return json_format.MessageToDict(msg, including_default_value_fields=True, preserving_proto_field_name=True)


class GameStream:
    """Background thread: connect to 127.0.0.1:<port>, keep the newest frame, reconnect on loss."""

    def __init__(self, fds, port: int):
        pool = descriptor_pool.DescriptorPool()
        for f in fds.file:
            pool.Add(f)
        self._req = message_factory.GetMessageClass(pool.FindMessageTypeByName("sc.game.telemetry.v1.TelemetryStreamRequest"))
        self._resp = message_factory.GetMessageClass(pool.FindMessageTypeByName("sc.game.telemetry.v1.TelemetryStreamResponse"))
        self.port = port
        self._lock = threading.Lock()
        self._frame: dict | None = None
        self._frame_at = 0.0
        self._events: list[str] = []
        self.connected = False
        self.frames = 0
        self.fps = 0.0
        self.error: str | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="game-stream", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def take(self) -> tuple[dict | None, float, list[str]]:
        """Latest frame, when it arrived, and the game events seen since the last take."""
        with self._lock:
            ev, self._events = self._events, []
            return self._frame, self._frame_at, ev

    def _run(self) -> None:
        while not self._stop.is_set():
            channel = grpc.insecure_channel(f"127.0.0.1:{self.port}")
            try:
                call = channel.unary_stream(METHOD, request_serializer=lambda m: m.SerializeToString(), response_deserializer=self._resp.FromString)
                window_start, window_n = time.time(), 0
                for msg in call(self._req()):
                    if self._stop.is_set():
                        break
                    frame = to_dict(msg)
                    events = [e.get("type") for e in (frame.get("events") or {}).get("events", []) if isinstance(e, dict) and e.get("type")]
                    with self._lock:
                        self._frame, self._frame_at = frame, time.time()
                        self._events.extend(events[:20])
                        del self._events[:-100]
                    self.connected, self.error = True, None
                    self.frames += 1
                    window_n += 1
                    if time.time() - window_start >= 2:
                        self.fps = window_n / (time.time() - window_start)
                        window_start, window_n = time.time(), 0
            except grpc.RpcError as e:
                self.error = e.code().name if hasattr(e, "code") else str(e)
            except Exception as e:  # keep the thread alive whatever happens
                self.error = str(e)[:200]
            finally:
                self.connected, self.fps = False, 0.0
                channel.close()
            self._stop.wait(3)
