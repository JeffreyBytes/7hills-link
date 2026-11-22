"""Tray icon: a gold "7". Minimizing or closing the window hides it to the tray.

Uses pystray (Windows notification area). If pystray or Pillow is missing,
the client runs without a tray icon and minimizes as usual.
"""

from __future__ import annotations

from typing import Callable

GOLD = (240, 180, 67, 255)


# The 7Hills "7" (same shape as the 7Net app icon), on a 512 grid.
LOGO = [(65, 91), (446, 91), (256, 421), (214, 349), (325, 157), (103, 157)]


def icon_image(size: int = 64):
    from PIL import Image, ImageDraw

    big = size * 4   # draw large and scale down for smooth edges
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Stretch the shape to fill the icon: its bounding box is x 65..446, y 91..421.
    x0, x1, y0, y1 = 65, 446, 91, 421
    scale = big * 0.96 / max(x1 - x0, y1 - y0)
    ox = (big - (x1 - x0) * scale) / 2
    oy = (big - (y1 - y0) * scale) / 2
    d.polygon([(ox + (x - x0) * scale, oy + (y - y0) * scale) for x, y in LOGO], fill=GOLD)
    return img.resize((size, size), Image.LANCZOS)


class Tray:
    def __init__(self, on_open: Callable[[], None], on_dashboard: Callable[[], None], on_quit: Callable[[], None],
                 on_mute: Callable[[], None] | None = None, is_muted: Callable[[], bool] | None = None) -> None:
        self.icon = None
        try:
            import pystray

            items = [
                pystray.MenuItem("Open 7Hills Link", lambda *_: on_open(), default=True),
                pystray.MenuItem("Open my dashboard", lambda *_: on_dashboard()),
            ]
            if on_mute and is_muted:
                items.append(pystray.MenuItem("Mute music", lambda *_: on_mute(), checked=lambda _item: is_muted()))
            menu = pystray.Menu(
                *items,
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", lambda *_: on_quit()),
            )
            self.icon = pystray.Icon("7HillsLink", icon_image(), "7Hills Link", menu)
        except Exception:
            self.icon = None

    @property
    def available(self) -> bool:
        return self.icon is not None

    @property
    def backend(self) -> str:
        return type(self.icon).__module__.rsplit(".", 1)[-1] if self.icon else ""

    @property
    def can_hide(self) -> bool:
        """Safe to hide the window to the tray. Not on Linux's X11 (XEmbed) backend: under a
        StatusNotifier proxy (KDE Wayland) its clicks never arrive and it has no menu, so a
        hidden window could not be brought back. With PyGObject pystray uses AppIndicator."""
        return self.icon is not None and self.backend != "_xorg"

    def start(self) -> None:
        if self.icon:
            try:
                if self.backend == "_xorg":
                    # pystray 0.19.5 on X11: run_detached() starts a second setup thread that is
                    # never released, so stop() waits 5 s. Running run() in one thread avoids it.
                    import threading
                    threading.Thread(target=self.icon.run, name="tray", daemon=True).start()
                else:
                    self.icon.run_detached()
            except Exception:
                self.icon = None

    def set_title(self, text: str) -> None:
        if self.icon:
            try:
                self.icon.title = text[:120]
            except Exception:
                pass

    def stop(self) -> None:
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
