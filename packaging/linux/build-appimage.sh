#!/usr/bin/env bash
# Build dist/7HillsLink-x86_64.AppImage (and its .sha256).
#
# Needs: Python with requirements.txt and pyinstaller installed, and appimagetool
# (https://github.com/AppImage/appimagetool) on PATH or in $APPIMAGETOOL.
# Run from anywhere: ./packaging/linux/build-appimage.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PYTHON="${PYTHON:-python3}"
APPIMAGETOOL="${APPIMAGETOOL:-appimagetool}"
BUILD="$ROOT/build/linux"
DIST="$ROOT/dist"
APPDIR="$BUILD/AppDir"
OUT="$DIST/7HillsLink-x86_64.AppImage"

rm -rf "$BUILD" "$DIST/7HillsLink" "$OUT" "$OUT.sha256"
mkdir -p "$BUILD" "$DIST"

"$PYTHON" -m PyInstaller --noconfirm --clean \
    --workpath "$BUILD/pyinstaller" --distpath "$BUILD/pyinstaller-dist" \
    "$HERE/7HillsLink.spec"

mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$BUILD/pyinstaller-dist/7HillsLink" "$APPDIR/usr/lib/"
install -m 755 "$HERE/AppRun" "$APPDIR/AppRun"
cp "$HERE/7hills-link.desktop" "$APPDIR/7hills-link.desktop"
cp "$HERE/7hills-link.desktop" "$APPDIR/usr/share/applications/"
# The icon is the tray icon's logo, drawn by the client itself.
PYTHONPATH="$ROOT/src" "$PYTHON" -c \
    "import sys; from sevenhills_link.tray import icon_image; icon_image(256).save(sys.argv[1])" \
    "$APPDIR/usr/share/icons/hicolor/256x256/apps/7hills-link.png"
cp "$APPDIR/usr/share/icons/hicolor/256x256/apps/7hills-link.png" "$APPDIR/7hills-link.png"
ln -sf 7hills-link.png "$APPDIR/.DirIcon"

# APPIMAGE_EXTRACT_AND_RUN: appimagetool is itself an AppImage, and CI runners have no FUSE.
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL" --no-appstream "$APPDIR" "$OUT"
(cd "$DIST" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256")
echo "built $OUT"
