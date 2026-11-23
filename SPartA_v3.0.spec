# -*- mode: python ; coding: utf-8 -*-
"""Unified cross-platform PyInstaller spec for SPartA v3.0 (macOS, Unix/Linux, Windows)."""

import sys
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

block_cipher = None

if sys.platform == "darwin":
    icon_ext = "icns"
elif sys.platform.startswith("win"):
    icon_ext = "ico"
else:
    icon_ext = "png"

datas = [
    ("*.tab", "."),
    ("SPartA-GUI/*.tab", "SPartA-GUI"),
    ("SPartA-GUI/maps", "SPartA-GUI/maps"),
]
for pkg in ("cartopy", "geopandas", "rasterio", "pyproj", "shapely", "matplotlib", "netCDF4", "gsw", "PIL"):
    datas += collect_data_files(pkg)

binaries = []
for pkg in ("rasterio", "pyproj", "shapely", "netCDF4", "gsw"):
    binaries += collect_dynamic_libs(pkg)

hiddenimports = (
    collect_submodules("rasterio")
    + collect_submodules("pyproj")
    + collect_submodules("cartopy")
    + collect_submodules("netCDF4")
    + collect_submodules("gsw")
    + [
        "cftime",
        "scipy.spatial.transform._rotation_groups",
        "scipy.special._cdflib",
        "scipy._lib.messagestream",
        "matplotlib.backends.backend_agg",
        "matplotlib.backends.backend_tkagg",
        "geopandas",
        "pyogrio",
        "shapely",
        "psutil",
        "prettytable",
        "tabulate",
        "PIL",
        "tkinter",
    ]
)

if sys.platform == "darwin":
    hiddenimports.append("matplotlib.backends.backend_macosx")

TARGETS = [
    ("SPartA", "SPartA.py", ".", f"icons/sparta.{icon_ext}", True),
    ("pSPartA", "pSPartA.py", ".", f"icons/sparta.{icon_ext}", True),
    ("operSPartA", "operSPartA.py", ".", f"icons/sparta.{icon_ext}", True),
    ("configOper", "configOper.py", ".", f"icons/sparta.{icon_ext}", True),
    ("SPartA-config", "SPartA-config/sparta_config.py", "SPartA-config", f"SPartA-config/icons/sparta_config.{icon_ext}", False),
    ("SPartA-GUI", "SPartA-GUI/sparta_gui.py", "SPartA-GUI", f"SPartA-GUI/icons/sparta_gui.{icon_ext}", False),
    ("SPartA-regrid", "SPartA-regrid/sparta_regrid.py", "SPartA-regrid", f"SPartA-regrid/icons/sparta_regrid.{icon_ext}", False),
    ("SPartA-reftime", "SPartA-reftime/sparta_reftime.py", "SPartA-reftime", f"SPartA-reftime/icons/sparta_reftime.{icon_ext}", False),
    ("SPartA-joinvars", "SPartA-joinvars/sparta_joinvars.py", "SPartA-joinvars", f"SPartA-joinvars/icons/sparta_joinvars.{icon_ext}", False),
]

analyses = []
exes = []
collect_args = []

for name, script, pathex, icon_path, is_console in TARGETS:
    a = Analysis(
        [script],
        pathex=[".", pathex],
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
    analyses.append((a, name, name))
    pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=is_console,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon_path,
    )
    exes.append(exe)
    collect_args.extend([exe, a.binaries, a.zipfiles, a.datas])

MERGE(*analyses)

coll = COLLECT(
    *collect_args,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SPartA_v3.0",
)
