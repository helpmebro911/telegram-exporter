#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV_DIR="${VENV_DIR:-.venv}"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

pip install -r requirements.txt
pip install pyinstaller

ICON_PNG="${ICON_PNG:-$ROOT/assets/app_icon.png}"
ICON_DIR="$ROOT/icons"
ICON_ICNS="$ICON_DIR/app.icns"
ICON_ARG=""

if [ -f "$ICON_PNG" ]; then
  mkdir -p "$ICON_DIR"
  ICONSET="$ICON_DIR/app.iconset"
  rm -rf "$ICONSET"
  mkdir -p "$ICONSET"
  sips -z 16 16   "$ICON_PNG" --out "$ICONSET/icon_16x16.png" >/dev/null
  sips -z 32 32   "$ICON_PNG" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
  sips -z 32 32   "$ICON_PNG" --out "$ICONSET/icon_32x32.png" >/dev/null
  sips -z 64 64   "$ICON_PNG" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
  sips -z 128 128 "$ICON_PNG" --out "$ICONSET/icon_128x128.png" >/dev/null
  sips -z 256 256 "$ICON_PNG" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
  sips -z 256 256 "$ICON_PNG" --out "$ICONSET/icon_256x256.png" >/dev/null
  sips -z 512 512 "$ICON_PNG" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
  sips -z 512 512 "$ICON_PNG" --out "$ICONSET/icon_512x512.png" >/dev/null
  sips -z 1024 1024 "$ICON_PNG" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
  iconutil -c icns "$ICONSET" -o "$ICON_ICNS"
  ICON_ARG="--icon \"$ICON_ICNS\""
fi

eval "pyinstaller --windowed --name \"Telegram Exporter\" $ICON_ARG \
  --target-arch universal2 \
  --exclude-module app_legacy \
  --collect-all customtkinter \
  --collect-all telethon \
  --collect-all faster_whisper \
  --collect-all ctranslate2 \
  --collect-all tokenizers \
  --collect-all imageio_ffmpeg \
  app.py"

APP_PATH="dist/Telegram Exporter.app"
DMG_NAME="${DMG_NAME:-TelegramExporter.dmg}"
DMG_PATH="dist/$DMG_NAME"

rm -f "$DMG_PATH"
hdiutil create -volname "Telegram Exporter" -srcfolder "$APP_PATH" -ov -format UDZO "$DMG_PATH"

echo "DMG готов: $DMG_PATH"
