# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for SPartA-regrid on Windows."""

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

block_cipher = None

datas = [
    ("icons/sparta_regrid.ico", "icons"),
]
for pkg in ("netCDF4",):
    datas += collect_data_files(pkg)

binaries = []
for pkg in ("netCDF4",):
    binaries += collect_dynamic_libs(pkg)

hiddenimports = (
    collect_submodules("netCDF4")
    + [
        "cftime",
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "scipy.interpolate",
        "scipy.spatial",
        "scipy.spatial.transform._rotation_groups",
        "scipy.special._cdflib",
        "scipy._lib.messagestream",
    ]
)

a = Analysis(
    ["sparta_regrid.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SPartA-regrid",
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
    icon="icons/sparta_regrid.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SPartA-regrid",
)
