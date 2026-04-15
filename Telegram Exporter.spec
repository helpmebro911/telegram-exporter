# -*- mode: python ; coding: utf-8 -*-
import os
import platform
from PyInstaller.utils.hooks import collect_all

# target_arch определяется переменной окружения TARGET_ARCH
# (передаётся из CI matrix / build-скрипта). Если не задано — используем
# архитектуру текущего хоста, чтобы не пытаться собрать universal/чужой срез
# при отсутствии соответствующих бинарных колёс зависимостей.
_host_arch = platform.machine().lower()
_env_arch = (os.environ.get("TARGET_ARCH") or "").strip().lower()
if _env_arch in ("x86_64", "arm64", "universal2"):
    TARGET_ARCH = _env_arch
elif _host_arch in ("arm64", "aarch64"):
    TARGET_ARCH = "arm64"
else:
    TARGET_ARCH = "x86_64"

datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('telethon')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('faster_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ctranslate2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tokenizers')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('imageio_ffmpeg')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tg_exporter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + [
        'tg_exporter.ui.app',
        'tg_exporter.core.orchestrator',
        'tg_exporter.services.transcription.factory',
        'keyring.backends',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['app_legacy', 'app'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Telegram Exporter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=TARGET_ARCH,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icons/app.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Telegram Exporter',
)
app = BUNDLE(
    coll,
    name='Telegram Exporter.app',
    icon='icons/app.icns',
    bundle_identifier=None,
)
