# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for SPartA & pSPartA on Windows."""

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

block_cipher = None

datas = [
    ("*.tab", "."),
]
for pkg in ("cartopy", "geopandas", "rasterio", "pyproj", "shapely", "matplotlib", "netCDF4"):
    datas += collect_data_files(pkg)

binaries = []
for pkg in ("rasterio", "pyproj", "shapely", "netCDF4"):
    binaries += collect_dynamic_libs(pkg)

hiddenimports = (
    collect_submodules("rasterio")
    + collect_submodules("pyproj")
    + collect_submodules("cartopy")
    + collect_submodules("netCDF4")
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
    ]
)

a_parallel = Analysis(
    ["pSPartA.py"],
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

a_seq = Analysis(
    ["SPartA.py"],
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

MERGE(
    (a_parallel, "pSPartA", "pSPartA"),
    (a_seq, "SPartA", "SPartA"),
)

pyz_parallel = PYZ(a_parallel.pure, a_parallel.zipped_data, cipher=block_cipher)
pyz_seq = PYZ(a_seq.pure, a_seq.zipped_data, cipher=block_cipher)

exe_parallel = EXE(
    pyz_parallel,
    a_parallel.scripts,
    [],
    exclude_binaries=True,
    name="pSPartA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icons/sparta.ico",
)

exe_seq = EXE(
    pyz_seq,
    a_seq.scripts,
    [],
    exclude_binaries=True,
    name="SPartA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icons/sparta.ico",
)

coll = COLLECT(
    exe_parallel,
    a_parallel.binaries,
    a_parallel.zipfiles,
    a_parallel.datas,
    exe_seq,
    a_seq.binaries,
    a_seq.zipfiles,
    a_seq.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SPartA",
)
