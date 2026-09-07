# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("uvicorn")
hiddenimports += collect_submodules("webview")

a = Analysis(
    ["welfare_launcher.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("web", "web"),
        ("assets/bokjitalk.ico", "assets"),
        ("wiki/kb-v120/welfare.db", "wiki/kb-v120"),
        ("wiki/kb-v120/manifest.json", "wiki/kb-v120"),
        ("config.yaml.example", "."),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="welfare_assistant",
    icon="assets/bokjitalk.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    version="file_version_info.txt",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="welfare_assistant",
)
