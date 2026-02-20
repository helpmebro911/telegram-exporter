#!/usr/bin/env bash
# Сборка под Intel (x86_64) macOS.
# На Mac с Apple Silicon (M1/M2) запускает сборку через Rosetta (arch -x86_64).
# Нужен x86_64 Python: например, установите Python с python.org (Intel) или используйте CI.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export VENV_DIR="${VENV_DIR:-.venv_intel}"
export DMG_NAME="${DMG_NAME:-TelegramExporter-mac-intel.dmg}"

echo "Сборка для Intel (x86_64). DMG: $DMG_NAME"
arch -x86_64 bash -c "cd \"$ROOT\" && chmod +x ./scripts/build_mac.sh && ./scripts/build_mac.sh"
echo "Готово: dist/$DMG_NAME"
