# -*- mode: python ; coding: utf-8 -*-

hiddenimports = [
    "Plan_SIFT.sift_tracker",
    "tools.fetch_17173_all_points",
    "tools.fetch_17173_icons",
    "tools.fetch_17173_points",
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
]


a = Analysis(
    ["main_island.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GMT-N",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
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
    upx=True,
    upx_exclude=[],
    name="GMT-N",
)
