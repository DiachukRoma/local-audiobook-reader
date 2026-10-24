#!/bin/bash
# Build a self-contained "Local Audiobook Reader.app" and a .dmg installer for macOS (Apple Silicon).
# Unlike scripts/build_app.sh, the result does not need Python or the project folder and can be
# copied to any Mac. Output: dist/Local Audiobook Reader.app and dist/Local-Audiobook-Reader-<ver>-macOS.dmg
#
#   scripts/build_macos.sh              # with the speech model inside (~0.8 GB, works offline at once)
#   scripts/build_macos.sh --no-model   # smaller; the app downloads the model on first start
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

BUNDLE_MODEL=1
for arg in "$@"; do
    case "$arg" in
        --no-model) BUNDLE_MODEL=0 ;;
        *) echo "Невідомий параметр: $arg" >&2; exit 2 ;;
    esac
done

PY="${PYTHON:-python3}"
if [ ! -x .venv/bin/python ]; then
    "$PY" -m venv .venv
fi
VPY=.venv/bin/python
"$VPY" -m pip install --quiet --upgrade pip
"$VPY" -m pip install --quiet -r requirements.txt -r requirements-build.txt
VERSION="$("$VPY" -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
ARCH="$(uname -m)"
APP_NAME="Local Audiobook Reader"

mkdir -p assets build
[ -f assets/icon.png ] || "$VPY" scripts/make_icon.py assets/icon.png
ICONSET="build/AppIcon.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
    sips -z $s $s assets/icon.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) assets/icon.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o build/AppIcon.icns

if [ "$BUNDLE_MODEL" = 1 ]; then
    "$VPY" scripts/download_model.py
fi

echo "Збирання $APP_NAME $VERSION ($ARCH)…"
BUNDLE_MODEL="$BUNDLE_MODEL" APP_ICON="$DIR/build/AppIcon.icns" \
    "$VPY" -m PyInstaller --noconfirm --clean --log-level WARN \
    --distpath dist --workpath build/pyinstaller packaging/audiobook_reader.spec
rm -rf "dist/$APP_NAME"  # intermediate folder; the .app bundle is the result

APP="dist/$APP_NAME.app"
# Ad-hoc signature (no Apple ID needed). For distribution without Gatekeeper warnings,
# sign with a Developer ID certificate and notarize instead.
codesign --force --deep --sign - "$APP"

DMG="dist/Local-Audiobook-Reader-$VERSION-macOS-$ARCH.dmg"
STAGE="build/dmg"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

echo
echo "Готово:"
echo "  $DIR/$APP"
echo "  $DIR/$DMG  ← інсталятор: відкрийте й перетягніть програму в «Програми»"
