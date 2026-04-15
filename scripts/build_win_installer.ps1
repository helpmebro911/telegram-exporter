$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $root "..")

python -m venv .venv
. .venv\Scripts\Activate.ps1

pip install -r requirements.txt
pip install pyinstaller

$iconPng = Join-Path (Get-Location) "assets\app_icon.png"
$iconIco = Join-Path (Get-Location) "icons\app.ico"

$pyinstallerArgs = @(
    "--windowed", "--onefile", "--name", "TelegramExporter",
    "--exclude-module", "app_legacy", "--exclude-module", "app",
    "--collect-all", "customtkinter",
    "--collect-all", "telethon",
    "--collect-all", "faster_whisper",
    "--collect-all", "ctranslate2",
    "--collect-all", "tokenizers",
    "--collect-all", "imageio_ffmpeg",
    "--collect-all", "tg_exporter",
    "--hidden-import", "tg_exporter.ui.app",
    "--hidden-import", "tg_exporter.core.orchestrator",
    "--hidden-import", "tg_exporter.services.transcription.factory",
    "--hidden-import", "keyring.backends"
)

if (Test-Path $iconPng) {
    python -m pip install pillow
    python scripts\make_icons.py --in $iconPng --out $iconIco
    $pyinstallerArgs += @("--icon", "$iconIco")
}

$pyinstallerArgs += "main.py"

pyinstaller @pyinstallerArgs

Write-Host "EXE ready: dist\TelegramExporter.exe"
Write-Host "Open installer\\TelegramExporter.iss in Inno Setup to compile installer."
