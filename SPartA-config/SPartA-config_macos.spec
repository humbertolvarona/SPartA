# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for SPartA-config on macOS."""

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

block_cipher = None

datas = [
    ("icons/sparta_config.icns", "icons"),
]
for pkg in ("cartopy", "pyproj", "shapely", "matplotlib"):
    datas += collect_data_files(pkg)

binaries = []
for pkg in ("pyproj", "shapely"):
    binaries += collect_dynamic_libs(pkg)

hiddenimports = (
    collect_submodules("pyproj")
    + collect_submodules("cartopy")
    + [
        "tkinter",
        "tkinter.ttk",
        "tkinter.font",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "matplotlib.backends.backend_tkagg",
        "matplotlib.backends.backend_agg",
        "matplotlib.widgets",
        "shapely",
        "shapely.strtree",
    ]
)

a = Analysis(
    ["sparta_config.py"],
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
    name="SPartA-config",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icons/sparta_config.icns",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SPartA-config",
)

app = BUNDLE(
    coll,
    name="SPartA-config.app",
    icon="icons/sparta_config.icns",
    bundle_identifier="org.sparta.config",
)
