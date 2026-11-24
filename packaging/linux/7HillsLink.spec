# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Linux build (one folder, wrapped into an AppImage by build-appimage.sh).
#
# Only Python and the pip packages are bundled. GTK 3, WebKitGTK 4.1, AppIndicator and GStreamer come
# from the system: the page renders in the system's WebKit, and mixing it with a bundled GTK/GLib is
# fragile (and PyInstaller's GTK hook would copy every icon theme on the build machine).
import os
import re

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
SRC = os.path.join(ROOT, "src")

hiddenimports = [
    "keyring.backends.SecretService",
    "pystray._appindicator", "pystray._gtk", "pystray._xorg",
]
hiddenimports += collect_submodules("sevenhills_link")
hiddenimports += collect_submodules("webview.platforms.gtk")

a = Analysis(
    [os.path.join(ROOT, "run_client.py")],
    pathex=[SRC],
    binaries=[],
    datas=[
        (os.path.join(SRC, "sevenhills_link", "ui"), "sevenhills_link/ui"),
        (os.path.join(SRC, "sevenhills_link", "data"), "sevenhills_link/data"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join(SPECPATH, "rth_gtk.py")],
    excludes=[
        "PyQt6", "PyQt5", "PySide6", "qtpy",
        "webview.platforms.qt", "webview.platforms.android", "webview.platforms.cocoa",
        "webview.platforms.winforms", "webview.platforms.edgechromium", "webview.platforms.mshtml",
        "webview.platforms.cef",
    ],
    noarchive=False,
    optimize=0,
)

# --- Leave the GTK / WebKitGTK / AppIndicator / GStreamer stack to the system ---
# Kept at the top level: Python's own dependencies, and libraries vendored inside pip wheels.
KEEP = re.compile(r"^(libpython|libffi|libssl|libcrypto|libz\.|libbz2|liblzma|libexpat|libsqlite3|libmpdec"
                  r"|libreadline|libncursesw|libtinfo|libuuid|libstdc\+\+|libgcc_s)")
WHEEL = re.compile(r"-[0-9a-f]{8}\.so")              # auditwheel-renamed libs from manylinux wheels
EXT = re.compile(r"\.cpython-\d+[^/]*\.so$")          # Python extension modules
SYSTEM_DIRS = ("gi_typelibs/", "gio_modules/", "gst_plugins/", "lib/", "share/")


def keep_bin(entry):
    dest = entry[0]
    if dest.startswith(SYSTEM_DIRS):
        return False
    if "/" in dest:      # inside a package (PIL/, grpc/, pillow.libs/, gi/ ...)
        return True
    return bool(KEEP.match(dest) or WHEEL.search(dest) or EXT.search(dest))


a.binaries = [b for b in a.binaries if keep_bin(b)]
a.datas = [d for d in a.datas if not d[0].startswith(SYSTEM_DIRS)]
# These point GI, GTK and GStreamer at the bundled copies we just dropped.
DROP_RTH = {"pyi_rth_gi", "pyi_rth_gio", "pyi_rth_glib", "pyi_rth_gtk", "pyi_rth_gdkpixbuf", "pyi_rth_gstreamer"}
a.scripts = [s for s in a.scripts if s[0] not in DROP_RTH]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="7HillsLink",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="7HillsLink",
)
