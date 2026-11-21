"""Read the telemetry API's protobuf definitions straight out of StarCitizen.exe.

The game embeds its FileDescriptorProtos (sc/game/telemetry/v1/*.proto). Reading
them from the installed exe means the client always matches the installed
build, also after a patch. The result is cached per exe size + modified time.
"""

from __future__ import annotations

import mmap
import re
from pathlib import Path

from google.protobuf import descriptor_pb2

from .paths import data_dir

NEEDLE = b"sc/game/telemetry"
SERVICE = "sc.game.telemetry.v1.GameTelemetryService"

# FileDescriptorProto field number → wire type (0 varint, 2 length-delimited)
_FDP_FIELDS = {1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2, 7: 2, 8: 2, 9: 2, 10: 0, 11: 0, 12: 2, 14: 0}


def _varint(b, i: int) -> tuple[int, int]:
    shift = result = 0
    while i < len(b):
        c = b[i]
        i += 1
        result |= (c & 0x7F) << shift
        if not c & 0x80:
            return result, i
        shift += 7
        if shift > 63:
            break
    raise ValueError("bad varint")


def _walk(b, start: int, limit: int = 4 << 20) -> bytes:
    """Follow fields from start while they look like a FileDescriptorProto."""
    i, end = start, min(len(b), start + limit)
    seen_name = False
    while i < end:
        try:
            tag, j = _varint(b, i)
        except ValueError:
            break
        field, wt = tag >> 3, tag & 7
        if _FDP_FIELDS.get(field) != wt or (field == 1 and seen_name):
            break
        try:
            if wt == 0:
                _, j = _varint(b, j)
            else:
                ln, j = _varint(b, j)
                j += ln
        except ValueError:
            break
        if j > end:
            break
        seen_name |= field == 1
        i = j
    return bytes(b[start:i])


def extract(exe: Path) -> descriptor_pb2.FileDescriptorSet:
    found: dict[str, descriptor_pb2.FileDescriptorProto] = {}
    with open(exe, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as data:
        for m in re.finditer(re.escape(NEEDLE), data):
            name_start = m.start()
            for back in (2, 3):
                s = name_start - back
                if s < 0 or data[s] != 0x0A:
                    continue
                try:
                    ln, j = _varint(data, s + 1)
                except ValueError:
                    continue
                if j != name_start or not bytes(data[name_start:name_start + ln]).endswith(b".proto"):
                    continue
                fdp = descriptor_pb2.FileDescriptorProto()
                try:
                    fdp.ParseFromString(_walk(data, s))
                except Exception:
                    continue
                prev = found.get(fdp.name)
                if prev is None or fdp.ByteSize() > prev.ByteSize():
                    found[fdp.name] = fdp
    # Dependencies first, so a descriptor pool can load them in order.
    ordered: list[descriptor_pb2.FileDescriptorProto] = []
    pending = dict(found)
    while pending:
        progressed = False
        for name, fdp in list(pending.items()):
            if all(d in [o.name for o in ordered] or d not in found for d in fdp.dependency):
                ordered.append(fdp)
                del pending[name]
                progressed = True
        if not progressed:
            ordered.extend(pending.values())
            break
    fds = descriptor_pb2.FileDescriptorSet()
    fds.file.extend(ordered)
    return fds


def has_service(fds: descriptor_pb2.FileDescriptorSet) -> bool:
    for f in fds.file:
        for s in f.service:
            if f"{f.package}.{s.name}" == SERVICE:
                return True
    return False


def load(exe: Path) -> descriptor_pb2.FileDescriptorSet:
    st = exe.stat()
    cache = data_dir() / f"protoset-{st.st_size}-{int(st.st_mtime)}.bin"
    if cache.exists():
        fds = descriptor_pb2.FileDescriptorSet()
        fds.ParseFromString(cache.read_bytes())
        if has_service(fds):
            return fds
    fds = extract(exe)
    if not has_service(fds):
        raise RuntimeError("This Star Citizen build has no telemetry service")
    cache.write_bytes(fds.SerializeToString())
    return fds
