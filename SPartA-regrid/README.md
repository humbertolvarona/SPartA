# SPartA-regrid (v2.0b)

Interactive **Python 3.14 + Tkinter 9.1** NetCDF spatial regridding tool for **SPartA**. Extracts the `(lon, lat)` grid from a reference NetCDF file and regrids one or more target NetCDF files so all forcing datasets share the exact same spatial grid.

## Features
- **Automatic Grid & Coordinate Detection**: Supports both 1D rectilinear and 2D curvilinear NetCDF grids, with optional longitude normalization (`[-180, 180]` ↔ `[0, 360]`).
- **11 Metocean Regridding Methods**:
  - `Bilinear (linear)`
  - `Nearest Neighbor (nearest)`
  - `Bicubic (cubic)`
  - `PCHIP Monotone (pchip, no overshoot)` — shape-preserving for salinity, concentration, ice fraction
  - `Quintic Spline (quintic)` — 5th-order smooth interpolation for velocity/vorticity fields
  - `Conservative Area-Mean (cos-lat weighted)` — mass/flux-conserving aggregation weighted by $\cos(\text{lat})$
  - `Cressman Objective Analysis (metocean)` — adaptive-radius meteorological/oceanographic objective analysis
  - `Gaussian / Barnes Analysis (metocean)` — Gaussian-weighted objective analysis
  - `RBF Thin-Plate Spline (rbf-tps)` — minimum-curvature surface interpolation across coastal gaps
  - `IDW (k=4 Inverse Distance)` and `IDW (k=8 Inverse Distance)`
- **Coastal NaN Filling**: Optional nearest-neighbor coastal fill to avoid missing values near land masks.
- **Preserves Dimensions & Metadata**: Keeps `time`, `depth`, coordinate arrays, and NetCDF variable/global attributes intact.

## Running

```bash
.venv/bin/python SPartA-regrid/sparta_regrid.py
```
