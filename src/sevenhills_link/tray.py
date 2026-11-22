"""Tray icon: a gold "7". Minimizing the window hides it to the tray.

Uses pystray (Windows notification area). If pystray or Pillow is missing,
the client runs without a tray icon and minimizes as usual.
"""

from __future__ import annotations

from typing import Callable

GOLD = (240, 180, 67, 255)
DARK = (13, 13, 13, 255)


def icon_image(size: int = 64):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = size // 5
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=GOLD)
    font = None
    for name in ("arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(name, int(size * 0.78))
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    box = d.textbbox((0, 0), "7", font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1]), "7", font=font, fill=DARK)
    return img


class Tray:
    def __init__(self, on_open: Callable[[], None], on_dashboard: Callable[[], None], on_quit: Callable[[], None]) -> None:
        self.icon = None
        try:
            import pystray

            menu = pystray.Menu(
                pystray.MenuItem("Open 7Hills Link", lambda *_: on_open(), default=True),
                pystray.MenuItem("Open my dashboard", lambda *_: on_dashboard()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", lambda *_: on_quit()),
            )
            self.icon = pystray.Icon("7HillsLink", icon_image(), "7Hills Link", menu)
        except Exception:
            self.icon = None

    @property
    def available(self) -> bool:
        return self.icon is not None

    def start(self) -> None:
        if self.icon:
            try:
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
