$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $root "..")

python -m venv .venv
. .venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install requirements failed" }

python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed" }

python -c "import customtkinter, telethon, faster_whisper, keyring, keyring.backends; print('deps OK')"
if ($LASTEXITCODE -ne 0) { throw "dependency import smoke-test failed" }

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
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

$exePath = "dist\TelegramExporter.exe"
if (-not (Test-Path $exePath)) { throw "EXE not produced at $exePath" }
$exeSize = (Get-Item $exePath).Length
Write-Host "EXE size: $([math]::Round($exeSize / 1MB, 1)) MB"
# Sanity check: broken bundles without customtkinter/faster-whisper come out ~15 MB.
# A healthy bundle is 60+ MB. Fail the build if we're below the threshold.
if ($exeSize -lt (40 * 1MB)) { throw "EXE too small ($exeSize bytes) - likely missing dependencies" }

Write-Host "EXE ready: $exePath"
Write-Host "Open installer\\TelegramExporter.iss in Inno Setup to compile installer."
