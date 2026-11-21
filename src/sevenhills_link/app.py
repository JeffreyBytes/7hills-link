"""The window (pywebview + a local HTML page in 7Net's look)."""

from __future__ import annotations

import threading
import webbrowser

from .core import Core
from .paths import resource

SITE = "https://www.7hills.space"


class JsApi:
    """Methods the page calls through window.pywebview.api."""

    def __init__(self, core: Core):
        self._core = core

    def status(self):
        return self._core.status()

    def enable_telemetry(self):
        r = self._core.enable_telemetry()
        return {"result": r, "status": self._core.status()}

    def rescan(self):
        self._core.scan()
        self._core.ensure_stream()
        return self._core.status()

    def set_channel(self, channel):
        self._core.set_channel(str(channel))
        return self._core.status()

    def start_link(self):
        return self._core.start_link()

    def open_link_page(self):
        link = self._core.link
        webbrowser.open(link["url"] if link else SITE + "/link")

    def unlink(self):
        self._core.unlink()
        return self._core.status()

    def set_share(self, patch):
        return self._core.set_share(dict(patch or {}))

    def set_bridge(self, enabled):
        return self._core.set_bridge(bool(enabled))

    def set_bridge_risky(self, allow):
        return self._core.set_bridge_risky(bool(allow))

    def new_bridge_key(self):
        return self._core.new_bridge_key()

    def scan_virpil(self):
        return self._core.scan_virpil()

    def set_virpil(self, device_id, selected):
        return self._core.set_virpil(str(device_id), bool(selected))

    def open_gremlin_folder(self):
        self._core.open_gremlin_folder()

    def open_dashboard(self):
        webbrowser.open(SITE + "/live")


def run_window() -> int:
    import webview  # pywebview

    core = Core()
    threading.Thread(target=core.run, name="core", daemon=True).start()
    html = resource("ui", "index.html").read_text(encoding="utf-8")
    webview.create_window("7Hills Link", html=html, js_api=JsApi(core), width=980, height=700, min_size=(760, 560), background_color="#0D0D0D")
    webview.start()
    core.stop()
    return 0
