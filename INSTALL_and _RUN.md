# SPartA & pSPartA (v2.0b) — Installation and Execution Guide

This guide provides complete, step-by-step instructions for installing dependencies, preparing input datasets, and running both the parallel **Python 3.14** edition (`pSPartA.py`) and the sequential edition (`SPartA.py`) of the **Simple-Particle Analysis model (SPartA)**.

---

## 1. System Requirements & Prerequisites

- **Python:** **Python 3.14** (recommended for `pSPartA.py`; also compatible with free-threaded `python3.14t` for zero-copy multi-core threading).
- **Operating System:** macOS, Linux, or Windows.
- **CPU & RAM:** Multi-core CPU (all logical cores are automatically utilized by `pSPartA.py` via `os.process_cpu_count()`); at least 4 GB of available RAM (depending on NetCDF grid dimensions and time steps).
- **Geospatial C Libraries (if building from source):** `cartopy`, `rasterio`, and `geopandas` rely on GEOS, PROJ, and GDAL. Installing via prebuilt wheels (`pip` or `uv`) on macOS/Linux usually bundles these automatically; if compiling from source on macOS, install them first via Homebrew:
  ```bash
  brew install proj geos gdal
  ```

---

## 2. Repository Layout

```text
SPartA/
├── SPartA.py                     # Sequential Lagrangian particle-tracking model
├── pSPartA.py                    # Multi-core parallel edition (Python 3.14)
├── requirements.txt              # Python package dependencies
├── SPartA_macos.spec             # PyInstaller spec for macOS
├── SPartA_linux.spec             # PyInstaller spec for Linux
├── SPartA_windows.spec           # PyInstaller spec for Windows
├── icons/                        # OS-specific application icons
│   ├── sparta.icns               # macOS icon
│   ├── sparta.png                # Linux icon (512x512 RGBA)
│   └── sparta.ico                # Windows multi-resolution icon
├── *.tab                         # 13 RGB color palette files (35 colors each)
└── samples/
    ├── test1.conf                # Use case 1: FOCURR (1-year passive currents)
    ├── test2.conf                # Use case 2: LARVAE (forward 7 particles)
    ├── test3.conf                # Use case 3: LARVAE (12 particles)
    ├── test4.conf                # Use case 4: LARVAE (28 particles)
    ├── test5.conf                # Use case 5: FOCURR (Euler integration)
    ├── test6.conf                # Use case 6: FOCURR_RK4 (4th-order Runge-Kutta)
    ├── test7.conf                # Use case 7: DECAY_TRACER (exponential decay)
    ├── test8.conf                # Use case 8: SUBSURFACE (settling / depth threshold)
    ├── test9.conf                # Use case 9: FOCURR_RK2 (2nd-order Runge-Kutta)
    ├── test10.conf               # Use case 10: RESIDENCE_TIME (domain residence)
    ├── test11.conf               # Use case 11: OKUBO (scale-dependent diffusivity)
    ├── test12.conf               # Use case 12: LARVAE (backtracking mode)
    ├── inputs/
    │   ├── 12hrClimHYCOM_CURR_1year.nc
    │   ├── 12hrClimHYCOM_CURR_1year.txt
    │   ├── test1.csv .. test5.csv # Initial particle release coordinates
    │   └── islands.obj           # Geographic markers/labels overlay
    └── outputs/
        └── test1/ .. test12/     # Output figures, NetCDF tracks, and summary CSVs
```

---

## 3. Installation

Navigate to the project root directory first:

```bash
cd /Users/humbertovarona/Lavoro/Papers/SPartA
```

### Option A: Standard Python 3.14 `venv` + `pip` (Recommended)

```bash
# 1. Create the virtual environment using Python 3.14
/opt/homebrew/bin/python3.14 -m venv .venv

# 2. Activate the virtual environment
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows (Command Prompt)

# 3. Upgrade pip and install all required packages
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Option B: Fast Installation with `uv`

```bash
uv venv --python /opt/homebrew/bin/python3.14 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### Option C: Conda / Mamba

```bash
conda create -n sparta python=3.14 -y
conda activate sparta
pip install -r requirements.txt
```

### Verify the Installation

Run the following command inside your activated environment to confirm all required libraries load without errors:

```bash
python -c "import numpy, scipy, netCDF4, cartopy, matplotlib, rasterio, geopandas, shapely, psutil, prettytable, tabulate; print('All SPartA dependencies installed successfully!')"
```

---

## 4. Preparing Inputs and Outputs

Ensure your configuration (`.conf`) JSON file points to valid directories and files:

1. **Hydrodynamic NetCDF (`Inputs->hydrodynamic_file`):** Must contain longitude, latitude, time, zonal velocity (`u`), and meridional velocity (`v`). Variable names are specified in `Inputs->htd_paramlist` (e.g., `["lon", "lat", "time", "water_u", "water_v"]`).
2. **Initial Particle Positions (`Inputs->particles_file`):** A headerless CSV file with 3 columns per row:
   ```csv
   NE_01,-30,-6
   NE_02,-30,-7
   NE_03,-30,-8
   ```
3. **Optional Fields (model-dependent):**
   - `wind_file` & `wind_paramlist`: Required for `CURWIND`, `GNOME`, `OPENDRIFT`, `MEDSLIK2`, `OSCAR`, `uPLASTIC`, `LEEWAY`, `SARGASSUM`, `ICEFLOES`, and `DEBRIS`.
   - `stokes_file` & `stokes_paramlist`: Optional Stokes drift fields for `OPENDRIFT`, `MEDSLIK2`, `uPLASTIC`, `LARVAE`, `SARGASSUM`, and `DEBRIS`.
   - `seawater_properties_file` & `swp_paramlist`: Required if `Physics->seawater_properties` is `1` (recommended for `uPLASTIC` to compute UNESCO EOS-80 seawater density $\rho_w(S, T)$).
4. **Output Directory (`Outputs->output_directory`):** Must exist prior to running and end with a trailing slash `/` (e.g., `/Users/humbertovarona/Lavoro/Papers/SPartA/samples/outputs/test2/`).

---

## 5. Running `pSPartA.py` (Parallel) and `SPartA.py` (Sequential)

Both scripts share the exact same **3 command-line modes**: `run`, `test`, and `view`.

### 5.1 Mode 1: `run <config.conf>` (Full Simulation)

Runs the full Lagrangian simulation, exports trajectories to NetCDF4, and generates the map (PNG/TIFF/JPEG/PDF/GeoTIFF/Shapefile).

- **Run the included `samples/test2.conf` (`LARVAE` model, 7 particles) in parallel:**
  ```bash
  python pSPartA.py run samples/test2.conf
  ```
- **Run with free-threaded Python 3.14t (if installed, uses shared-memory `ThreadPoolExecutor`):**
  ```bash
  python3.14t pSPartA.py run samples/test2.conf
  ```
- **Run sequentially with `SPartA.py`:**
  ```bash
  python SPartA.py run samples/test2.conf
  ```

### 5.2 Mode 2: `test <1|2>` (Built-in Test Suites)

Automatically loads `test1.conf` or `test2.conf` from the current working directory, runs the simulation, prints CPU temperature (if supported by the OS), and saves all outputs:

```bash
cd samples
python ../pSPartA.py test 2
```

### 5.3 Mode 3: `view <config.conf>` (Post-Processing & Visualization)

Loads an existing NetCDF trajectory file (`Outputs->track_file`) without re-running the physics, optionally applies `Analysis->time_interval_filter`, saves the map, and displays it interactively:

```bash
python pSPartA.py view samples/test2.conf
```

---

## 6. Supported `model_type` Options

Set `General->model_type` in your `.conf` file to any of the **18 implemented models**:

| `model_type` | Domain / Application | Required NetCDF Inputs |
| :--- | :--- | :--- |
| `FOCURR` | Passive surface ocean currents (Euler) | Hydrodynamic (`u, v`) |
| `FOCURR_RK2` | Passive surface ocean currents (2nd-order Runge-Kutta) | Hydrodynamic (`u, v`) |
| `FOCURR_RK4` | Passive surface ocean currents (4th-order Runge-Kutta) | Hydrodynamic (`u, v`) |
| `DECAY_TRACER` | Passive tracer with first-order exponential decay $C(t) = C_0 e^{-\lambda t}$ | Hydrodynamic (`u, v`) |
| `SUBSURFACE` | Subsurface drift with vertical settling / depth threshold | Hydrodynamic (`u, v`) |
| `RESIDENCE_TIME` | Domain residence-time tracking (stops on boundary exit) | Hydrodynamic (`u, v`) |
| `OKUBO` | Scale-dependent turbulent diffusion (Okubo 4/3 power law) | Hydrodynamic (`u, v`) |
| `CURWIND` | Oil spill drift (PETROMAR-3D Eqs. 1–2) | Hydrodynamic + Wind |
| `GNOME` | NOAA leeway rotation + uniform diffusion | Hydrodynamic + Wind |
| `OPENDRIFT` | OpenOil currents + Stokes + wind drag | Hydrodynamic + Wind (+ optional Stokes) |
| `MEDSLIK2` | Isotropic angular Brownian dispersion | Hydrodynamic + Wind (+ optional Stokes) |
| `OSCAR` | SINTEF oil spill drift | Hydrodynamic + Wind |
| `uPLASTIC` | Microplastics + EOS-80 biofouling sink | Hydrodynamic + Wind (+ optional Stokes, T/S) |
| `LARVAE` | Ichthyoplankton active swimming + PLD/mortality | Hydrodynamic (+ optional Stokes) |
| `LEEWAY` | Maritime Search and Rescue (SAR) | Hydrodynamic + Wind |
| `SARGASSUM` | Sargassum drift + biomass balance | Hydrodynamic + Wind (+ optional Stokes) |
| `ICEFLOES` | Iceberg drift + Coriolis + volume ablation | Hydrodynamic + Wind |
| `DEBRIS` | Floating debris with category windage $C_k$ | Hydrodynamic + Wind (+ optional Stokes) |

---

## 7. Parallelization Behavior (`pSPartA.py`)

When `pSPartA.py` runs:
1. It queries `os.process_cpu_count()` (falling back to `os.cpu_count()`) to determine the number of available CPU cores.
2. If the Python 3.14 GIL is disabled (`python3.14t`), it spawns a `ThreadPoolExecutor` with zero-copy shared memory. Otherwise, it spawns a `ProcessPoolExecutor` with `_init_worker` (compatible with `spawn` on macOS and Windows).
3. Each worker caches the `cKDTree` spatial index once, and `as_completed()` reports particle completion progress in real time when `General->verbose > 0`.

---

## 8. Building Standalone Executables with PyInstaller

Pre-configured PyInstaller `.spec` files and OS-specific icons are included in the repository to package both `pSPartA` (parallel) and `SPartA` (sequential) together with all geospatial libraries (`cartopy`, `geopandas`, `rasterio`, `pyproj`, `shapely`, `netCDF4`, `scipy`) and `*.tab` color palettes into `dist/SPartA/`.

| Platform | Spec File | Icon File | Output Executables |
| :--- | :--- | :--- | :--- |
| **macOS** | `SPartA_macos.spec` | `icons/sparta.icns` | `dist/SPartA/pSPartA`, `dist/SPartA/SPartA` |
| **Linux** | `SPartA_linux.spec` | `icons/sparta.png` | `dist/SPartA/pSPartA`, `dist/SPartA/SPartA` |
| **Windows** | `SPartA_windows.spec` | `icons/sparta.ico` | `dist\SPartA\pSPartA.exe`, `dist\SPartA\SPartA.exe` |

> **Note:** PyInstaller does not cross-compile across operating systems. Run each `.spec` file natively on the target OS inside an activated Python environment that already has `requirements.txt` installed.

### 8.1 macOS (`SPartA_macos.spec`)

```bash
# 1. Activate your virtual environment
source .venv/bin/activate

# 2. Install PyInstaller
pip install pyinstaller

# 3. Build the macOS bundle (dist/SPartA/)
pyinstaller --clean --noconfirm SPartA_macos.spec

# 4. Run the compiled executable
./dist/SPartA/pSPartA run samples/test2.conf
```

- If macOS Gatekeeper blocks execution on another machine, remove the quarantine attribute with:
  ```bash
  xattr -dr com.apple.quarantine dist/SPartA/
  ```

### 8.2 Linux (`SPartA_linux.spec`)

```bash
# 1. Activate your virtual environment
source .venv/bin/activate

# 2. Install PyInstaller (and ensure binutils / libpython dev libraries are available)
pip install pyinstaller

# 3. Build the Linux bundle (dist/SPartA/)
pyinstaller --clean --noconfirm SPartA_linux.spec

# 4. Run the compiled executable
./dist/SPartA/pSPartA run samples/test2.conf
```

- On Ubuntu/Debian, if PyInstaller reports missing shared libraries (`libpython3.x.so` or `objdump`), install `binutils` and `python3-dev` (or `libpython3.14-dev`).

### 8.3 Windows (`SPartA_windows.spec`)

Open **Command Prompt** or **PowerShell** in the repository root:

```bat
REM 1. Activate your virtual environment
.venv\Scripts\activate

REM 2. Install PyInstaller
pip install pyinstaller

REM 3. Build the Windows bundle (dist\SPartA\)
pyinstaller --clean --noconfirm SPartA_windows.spec

REM 4. Run the compiled executable
dist\SPartA\pSPartA.exe run samples\test2.conf
```

- `pSPartA.py` calls `multiprocessing.freeze_support()` at startup so `ProcessPoolExecutor` works safely inside frozen Windows and macOS executables.

---

## 9. Troubleshooting

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| `ModuleNotFoundError: No module named 'scipy'` | Wrong Python interpreter or virtual environment not activated. | Run `source .venv/bin/activate` and verify `which python`. |
| `Error: wind file not found for <MODEL> model.` | Selected model requires wind data, but `wind_file` is empty or missing. | Set `Inputs->wind_file` and `Inputs->wind_paramlist`, or use `FOCURR` / `LARVAE`. |
| `File ... does not exist.` | Relative paths in `.conf` do not match the current working directory. | Use absolute paths (as in `samples/test2.conf`) or run from the expected directory. |
| Particles stop immediately (`NaN`) | Initial coordinates lie on land or outside `[lon_min, lon_max] × [lat_min, lat_max]`. | Check `particles_file` coordinates against the NetCDF bounds and try `auxiliary_interpolation_method: "k12"`. |
| `Outputs` fail to write | Target `output_directory` does not exist or lacks a trailing `/`. | Create the directory with `mkdir -p` and ensure `output_directory` ends with `/`. |
