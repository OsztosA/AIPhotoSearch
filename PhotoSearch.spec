# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

chromadb_datas, chromadb_binaries, chromadb_hiddenimports = collect_all("chromadb")
heif_datas, heif_binaries, heif_hiddenimports = collect_all("pillow_heif")

analysis = Analysis(
    ["main.py"],
    pathex=[],
    binaries=chromadb_binaries + heif_binaries,
    datas=chromadb_datas + heif_datas,
    hiddenimports=chromadb_hiddenimports + heif_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="PhotoSearch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    name="PhotoSearch",
)
