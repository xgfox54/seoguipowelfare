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
        ("wiki/search/welfare.db", "wiki/search"),
        ("wiki/search/manifest.json", "wiki/search"),
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
    a.binaries,
    a.datas,
    [],
    name="복지업무비서",
    icon="assets/bokjitalk.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
