"""The window (pywebview + a local HTML page in 7Net's look)."""

from __future__ import annotations

import os
import sys
import threading
import webbrowser

from . import updater
from .core import Core
from .paths import resource

SITE = "https://www.7hills.space"

# The org's channels, as on the 7Net public site (lib/cms.ts). Only these open from the window.
LINKS = {
    "site": SITE,
    "discord": "https://discord.gg/7hills",
    "youtube": "https://www.youtube.com/@7hillsindustries",
    "spotify": "https://open.spotify.com/artist/2Y8asDjzVsVYEUFS1xnyk9",
    "apple": "https://music.apple.com/us/artist/7hills-industries/1843073599",
    "rsi": "https://robertsspaceindustries.com/en/orgs/7HILLS",
}


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

    def update_now(self):
        self._core.updates.install()
        return self._core.status()

    def check_updates(self):
        self._core.updates.check_now()
        return self._core.status()

    def set_auto_update(self, on):
        self._core.updates.set_auto(bool(on))
        return self._core.status()

    def set_sound(self, muted=None, volume=None):
        return self._core.set_sound(muted if muted is None else bool(muted), volume if volume is None else float(volume))

    def open_link(self, key):
        url = LINKS.get(str(key))
        if url:
            webbrowser.open(url)

    def open_dashboard(self):
        webbrowser.open(SITE + "/live")


def run_window(updated_from: str | None = None) -> int:
    import webview  # pywebview

    # The jingle plays without a click on the page; WebView2 needs this to allow it.
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--autoplay-policy=no-user-gesture-required")
    core = Core()
    html = resource("ui", "index.html").read_text(encoding="utf-8")
    try:
        import base64
        jingle = base64.b64encode(resource("ui", "intro.mp3").read_bytes()).decode("ascii")
        html = html.replace("{{INTRO_SRC}}", "data:audio/mpeg;base64," + jingle)
    except OSError:
        html = html.replace("{{INTRO_SRC}}", "")
    window = webview.create_window("7Hills Link", html=html, js_api=JsApi(core), width=980, height=700, min_size=(760, 560), background_color="#0D0D0D")

    def install(new_exe):
        # Swaps the exe and starts the new one; on success close this window and exit.
        if updater.install(new_exe):
            tray.stop()
            core.stop()
            try:
                window.destroy()
            finally:
                os._exit(0)
    core.updates.install_hook = install

    # Tray: minimizing hides the window; the gold 7 in the tray brings it back.
    from .tray import Tray

    def show_window():
        try:
            window.show()
            window.restore()
        except Exception:
            pass

    def quit_app():
        tray.stop()
        core.stop()
        try:
            window.destroy()
        except Exception:
            os._exit(0)

    tray = Tray(show_window, lambda: webbrowser.open(SITE + "/live"), quit_app)
    if tray.available:
        window.events.minimized += lambda *_: window.hide()

    def tray_title_loop():
        while True:
            try:
                st = core.status()
                state = "in game" if st.get("game_connected") else "game not running"
                tray.set_title(f"7Hills Link v{st.get('version')} · {state}")
            except Exception:
                pass
            threading.Event().wait(5)

    def started():
        threading.Thread(target=core.run, name="core", daemon=True).start()
        tray.start()
        threading.Thread(target=tray_title_loop, name="tray-title", daemon=True).start()
        if updated_from:
            threading.Thread(target=updater.cleanup, name="update-cleanup", daemon=True).start()

    webview.start(started)
    tray.stop()
    core.stop()
    return 0
