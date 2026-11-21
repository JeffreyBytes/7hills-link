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

    def led_test(self, device_id, number, color):
        return self._core.led_test(str(device_id), int(number), str(color))

    def led_reset(self, device_id):
        return self._core.led_reset(str(device_id))

    def browse_led_tool(self):
        import webview
        w = getattr(self, "_window", None)
        if w is None:
            return self._core.status()
        picked = w.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=("VPC LED Control (VPC_LED_Control.exe)", "All files (*.*)"))
        if picked:
            return self._core.set_led_tool(picked[0])
        return self._core.status()

    def set_joysticks(self, on):
        return self._core.set_joysticks(bool(on))

    def panel_catalog(self):
        from .functions import catalog
        return catalog()

    def panel_now(self, function_id):
        return self._core.panel.now(str(function_id))

    def panel_learn(self):
        self._core.panel.start_learn()
        return self._core.status()

    def panel_cancel(self):
        self._core.panel.cancel_learn()
        return self._core.status()

    def panel_save(self, mapping):
        return self._core.panel_save(dict(mapping or {}))

    def panel_delete(self, mid):
        self._core.panel.delete_mapping(str(mid))
        return self._core.status()

    def panel_active(self, on):
        self._core.panel.set_active(bool(on))
        return self._core.status()

    def open_gremlin_folder(self):
        self._core.open_gremlin_folder()

    def open_dashboard(self):
        webbrowser.open(SITE + "/live")


def run_window() -> int:
    import webview  # pywebview

    core = Core()
    threading.Thread(target=core.run, name="core", daemon=True).start()
    html = resource("ui", "index.html").read_text(encoding="utf-8")
    js = JsApi(core)
    window = webview.create_window("7Hills Link", html=html, js_api=js, width=980, height=700, min_size=(760, 560), background_color="#0D0D0D")
    js._window = window
    webview.start()
    core.stop()
    return 0
