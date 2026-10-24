#!/bin/bash
# Build "Local Audiobook Reader.app" inside the project folder. The bundle is a thin
# launcher that runs the project's virtual environment; it is not copied anywhere else.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$DIR/Local Audiobook Reader.app"
cd "$DIR"

mkdir -p assets
if [ ! -f assets/icon.png ]; then
    .venv/bin/python scripts/make_icon.py assets/icon.png
fi
ICONSET="$(mktemp -d)/AppIcon.iconset"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
    sips -z $s $s assets/icon.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) assets/icon.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
rm -rf "$(dirname "$ICONSET")"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Local Audiobook Reader</string>
    <key>CFBundleDisplayName</key><string>Local Audiobook Reader</string>
    <key>CFBundleIdentifier</key><string>local.audiobook-reader</string>
    <key>CFBundleVersion</key><string>1.0.0</string>
    <key>CFBundleShortVersionString</key><string>1.0.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>launcher</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>LSApplicationCategoryType</key><string>public.app-category.books</string>
    <key>CFBundleDocumentTypes</key>
    <array>
        <dict>
            <key>CFBundleTypeName</key><string>Book</string>
            <key>CFBundleTypeRole</key><string>Viewer</string>
            <key>LSHandlerRank</key><string>Alternate</string>
            <key>LSItemContentTypes</key>
            <array>
                <string>com.adobe.pdf</string>
                <string>org.idpf.epub-container</string>
                <string>public.plain-text</string>
                <string>org.openxmlformats.wordprocessingml.document</string>
            </array>
        </dict>
    </array>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/launcher" <<'LAUNCHER'
#!/bin/bash
# Resolve the project folder (the .app lives directly inside it).
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PROJECT="$(dirname "$APP_DIR")"
if [ ! -x "$PROJECT/.venv/bin/python" ]; then
    osascript -e 'display alert "Local Audiobook Reader" message "Середовище не встановлено. Запустіть scripts/setup.sh у теці проєкту."'
    exit 1
fi
export PYTHONPATH="$PROJECT/src"
export HF_HUB_DISABLE_TELEMETRY=1
exec "$PROJECT/.venv/bin/python" -m audiobook_reader "$@" >>"$PROJECT/data/launcher.log" 2>&1
LAUNCHER
chmod +x "$APP/Contents/MacOS/launcher"
mkdir -p "$DIR/data"
# Ad-hoc signature so macOS treats the locally built bundle consistently (no Apple ID needed).
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
echo "Створено: $APP"
