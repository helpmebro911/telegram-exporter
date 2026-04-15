$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $root "..")

python -m venv .venv
. .venv\Scripts\Activate.ps1

pip install -r requirements.txt
pip install pyinstaller

$iconPng = Join-Path (Get-Location) "assets\app_icon.png"
$iconIco = Join-Path (Get-Location) "icons\app.ico"
$iconArg = ""

if (Test-Path $iconPng) {
    pip install pillow
    python scripts\make_icons.py --in $iconPng --out $iconIco
    $iconArg = "--icon `"$iconIco`""
}

pyinstaller --windowed --onefile --name "TelegramExporter" $iconArg `
    --exclude-module app_legacy --exclude-module app `
    --collect-all customtkinter --collect-all telethon `
    --collect-all faster_whisper --collect-all ctranslate2 `
    --collect-all tokenizers --collect-all imageio_ffmpeg `
    --collect-all tg_exporter `
    --hidden-import tg_exporter.ui.app `
    --hidden-import tg_exporter.core.orchestrator `
    --hidden-import tg_exporter.services.transcription.factory `
    --hidden-import keyring.backends `
    main.py

Write-Host "EXE готов: dist\TelegramExporter.exe"
