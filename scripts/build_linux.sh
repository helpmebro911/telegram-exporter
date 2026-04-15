#!/usr/bin/env bash
# Linux build: onedir PyInstaller bundle → tar.gz.
# В отличие от macOS/Windows не собираем .deb/.rpm/AppImage — для простоты
# распространяем архив, который пользователь распаковывает и запускает
# ./TelegramExporter/Telegram\ Exporter.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV_DIR="${VENV_DIR:-.venv}"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

# Иконка опциональна. Linux-таскбары обычно читают .png из ресурсов приложения,
# так что .icns/.ico не нужен; .png отдаём через assets/.
ICON_PNG="${ICON_PNG:-$ROOT/assets/app_icon.png}"
ICON_ARG=()
if [ -f "$ICON_PNG" ]; then
  ICON_ARG=(--icon "$ICON_PNG")
fi

pyinstaller --windowed --name "Telegram Exporter" "${ICON_ARG[@]}" \
  --exclude-module app_legacy \
  --exclude-module app \
  --collect-all customtkinter \
  --collect-all telethon \
  --collect-all faster_whisper \
  --collect-all ctranslate2 \
  --collect-all tokenizers \
  --collect-all imageio_ffmpeg \
  --collect-all tg_exporter \
  --hidden-import tg_exporter.ui.app \
  --hidden-import tg_exporter.core.orchestrator \
  --hidden-import tg_exporter.services.transcription.factory \
  --hidden-import keyring.backends \
  main.py

APP_DIR="dist/Telegram Exporter"
ARCHIVE_NAME="${ARCHIVE_NAME:-TelegramExporter-linux-x86_64.tar.gz}"
ARCHIVE_PATH="dist/$ARCHIVE_NAME"

if [ ! -d "$APP_DIR" ]; then
  echo "Ошибка: PyInstaller не создал $APP_DIR" >&2
  exit 1
fi

rm -f "$ARCHIVE_PATH"
tar -czf "$ARCHIVE_PATH" -C "dist" "Telegram Exporter"

echo "Архив готов: $ARCHIVE_PATH"
