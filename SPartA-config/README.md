# SPartA-config (v2.0b)

Interactive **Python 3.14 + Tkinter 9.1** configuration editor for SPartA `.conf` JSON files (`samples/test1.conf`–`samples/test12.conf`).

## Features
- **Complete Parameter Coverage**: Edits all 9 sections (`General`, `Inputs`, `Numerical_methods`, `Physics`, `Parameters`, `Coefficients`, `Outputs`, `Analysis`, `Plots`) and all 81 parameters across the 18 implemented SPartA models.
- **Map Rectangle Selectors**: Draw `Plots->study_region` and `Physics->residence_bbox` directly on a 10m Cartopy map (`Select on Map...`).
- **Integrated Particle CSV Editor (`Edit CSV...`)**: Add/edit/delete particles, pick coordinates on map, or generate random/grid/transect ocean-only particle sets (10m Natural Earth land exclusion) and preview them on the map.
- **Integrated Map Objects Editor (`Edit .obj...`)**: Edit `mark`, `text`, `circle`, `fcircle`, `tcircle`, `rectangle`, `frectangle`, and `trectangle` overlays with dynamic `Arg1–Arg6` labels, SPartA DMS coordinate conversion (`32˚25"17.0W`), and map preview.
- **21 Legend Positions**: Supports both inside and outside (`outside upper/lower/left/right ...`) Matplotlib legend placements.

## Running from Source

```bash
cd SPartA-config
python3.14 -m venv .venv
source .venv/bin/activate        # macOS / Linux (or .venv\Scripts\activate on Windows)
pip install -r requirements.txt
python sparta_config.py
```

## Building Standalone Executables with PyInstaller

```bash
# macOS
pyinstaller --clean --noconfirm SPartA-config_macos.spec

# Linux
pyinstaller --clean --noconfirm SPartA-config_linux.spec

# Windows
pyinstaller --clean --noconfirm SPartA-config_windows.spec
```
