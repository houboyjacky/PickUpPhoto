#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
PYTHON_INPUT="${PYTHON_BIN:-.venv/bin/python}"
PYTHON="$(command -v "$PYTHON_INPUT")"
if [[ "$(uname -s)" != Darwin || "$("$PYTHON" -c 'import platform; print(platform.machine())')" != arm64 ]]; then
    echo "請使用 Apple Silicon macOS 與 arm64 Python 建置。" >&2
    exit 1
fi

VERSION="$("$PYTHON" -c 'from pickupphoto import __version__; print(__version__)')"
OUTPUT="${DMG_OUTPUT_DIR:-$PWD}"
mkdir -p "$OUTPUT"
OUTPUT="$(cd "$OUTPUT" && pwd)"
DMG="PickUpPhoto_v${VERSION}_AppleSilicon.dmg"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

FACE_ARGS=()
if "$PYTHON" -c 'from pickupphoto.analysis.face_focus import is_available; assert is_available()' >/dev/null 2>&1; then
    FACE_ARGS=(--collect-all mediapipe)
fi

PYINSTALLER_CONFIG_DIR="$BUILD_DIR/cache" "$PYTHON" -m PyInstaller \
    --windowed --noconfirm --clean --target-architecture arm64 \
    --name PickUpPhoto --icon "$PWD/app_icon.icns" \
    --osx-bundle-identifier com.jackyphoto.pickupphoto \
    --paths "$PWD" --workpath "$BUILD_DIR/build" --distpath "$BUILD_DIR/dist" \
    --specpath "$BUILD_DIR" \
    --add-data "$PWD/pickupphoto/web/static:pickupphoto/web/static" \
    --collect-all rawpy --exclude-module dearpygui ${FACE_ARGS[@]+"${FACE_ARGS[@]}"} \
    "$PWD/pickupphoto/__main__.py"

APP="$BUILD_DIR/dist/PickUpPhoto.app"
PLIST="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $VERSION" "$PLIST"
codesign --force --sign - "$APP"
codesign --verify --deep --strict "$APP"
lipo -verify_arch arm64 "$APP/Contents/MacOS/PickUpPhoto"

echo "=== 驗證封裝後的 .app 與網頁資源 ==="
"$PYTHON" scripts/smoke_macos_app.py "$APP"

mkdir "$BUILD_DIR/dmg"
ditto "$APP" "$BUILD_DIR/dmg/PickUpPhoto.app"
ln -s /Applications "$BUILD_DIR/dmg/Applications"
hdiutil create -volname "PickUpPhoto" -srcfolder "$BUILD_DIR/dmg" -format UDZO "$BUILD_DIR/$DMG"
hdiutil verify "$BUILD_DIR/$DMG"
mv -f "$BUILD_DIR/$DMG" "$OUTPUT/$DMG"
(cd "$OUTPUT" && shasum -a 256 "$DMG" > "$DMG.sha256")
echo "DMG $OUTPUT/$DMG"
