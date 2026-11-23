# Simple-Particle Analysis Model (SPartA, pSPartA & operSPartA)

Lagrangian particle-tracking model for simulating and analyzing individual particle trajectories at the surface of oceans, lakes, and rivers.

- **Version:** 3.0 (with `pSPartA.py` parallel edition for Python 3.14)
- **Release Date:** November 22, 2023
- **DOI:** [10.5281/zenodo.24444691](https://doi.org/10.5281/zenodo.24444691)
- **License:** MIT

---

## Repository Contents

| File | Description |
| :--- | :--- |
| `SPartA.py` | Sequential Lagrangian particle-tracking model (`FOCURR`). |
| `pSPartA.py` | Multi-core parallel edition for **Python 3.14** (`ProcessPoolExecutor` / free-threaded `ThreadPoolExecutor` with real-time progress and per-worker `cKDTree` caching). |
| `operSPartA.py` | Multi-core parallel edition for Python 3.14 (ProcessPoolExecutor / free-threaded ThreadPoolExecutor with real-time progress and per-worker cKDTree caching), specifically designed for operational oceanography applications.. |
| `requirements.txt` | Python package dependencies. |
| `SPartA_Manual_Usuario.docx` | Full technical, physical-mathematical, and user manual (in Spanish, with editable OMML equations). |
| `darkcolors.tab`, `lightcolors.tab`, `mixedcolors.tab`, `mixedcolors2.tab` | RGB color palette tables for trajectory plotting. |

---

## Key Features

- **Lagrangian Advection (`FOCURR`):** Explicit Euler integration of 2D surface velocity fields $(u, v)$ in geographic coordinates $(\lambda, \phi)$ with spherical Earth metric conversion.
- **Forward & Backward Tracking:** Supports time-reversed (*backtracking*) simulations (`invert_vector_fields`) by reversing the velocity time series and negating $(u, v)$.
- **Two-Stage Spatial Interpolation:**
  - Primary interpolation via `scipy.interpolate.griddata` (`linear`, `nearest`, `cubic`).
  - Automatic fallback to $k$-nearest neighbors (`k4`, `k12`, `k16`) using `scipy.spatial.cKDTree` near coastlines or domain boundaries.
- **Stochastic & Oscillatory Dispersion:** Supports `RANDOMWALK`, `UNIFORM`, `RANDOM`, `ANORM`, `MAS`, `DMAS`, `WEINER`/`WIENER`, and `POISSON` formulations.
- **Diagnostics & Seawater Properties:** Optional surface transport calculation ($T = \|\mathbf{u}\| \Delta x \Delta y$) and interpolation of temperature and salinity along particle paths.
- **Flexible Outputs:** Exports trajectories to **NetCDF4** and generates **Cartopy** maps in PNG, TIFF, JPEG, PDF, **GeoTIFF**, and **Shapefile** (single-layer or per-particle multi-layer).

---

## Installation

1. **Create a Python 3.14 virtual environment** (recommended) and install dependencies:

   ```bash
   python3.14 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Prepare input and output directories** (if using sample datasets):

   ```bash
   mkdir -p inputs outputs
   mv 2hrClimHYCOM_CURR_nov.nc inputs/
   mv test1.conf inputs/
   mv test2.conf inputs/
   ```

---

## How to Run

Both `SPartA.py` (Sequential), `pSPartA.py` (Parallel across all CPU cores), and `operSPartA.py` (Operational parallel across all CPU cores) share the same CLI interface:

### 1. Run a Simulation
```bash
python3.14 pSPartA.py run inputs/<config.conf>
# or sequential:
python SPartA.py run inputs/<config.conf>
```

### 2. Run Built-in Tests
```bash
python3.14 pSPartA.py test 1   # or 2 (loads test1.conf / test2.conf)
```

### 3. Visualize Existing Results
```bash
python3.14 pSPartA.py view inputs/<config.conf>
```

---

## Configuration (`.conf`)

Simulations are configured using a JSON `.conf` file organized into nine sections:

- `General`: `model_name`, `description`, `model_type` (`"FOCURR"`), `verbose` (`0`–`2`).
- `Inputs`: `input_directory`, `hydrodynamic_file`, `htd_paramlist`, `seawater_properties_file`, `swp_paramlist`, `wind_file`, `wind_paramlist`, `particles_file` (CSV: `name,lon,lat`), `active_particles`, `coast_file`, `objects_files`.
- `Numerical_methods`: `interpolation_method` (`linear`/`nearest`/`cubic`), `auxiliary_interpolation_method` (`k4`/`k12`/`k16`).
- `Physics`: `invert_vector_fields`, `compute_transport`, `seawater_properties`, `horizdiff`, `currcoef`, `windwavecoef`, `random_term`, `rt_method`.
- `Parameters`: `start_time`, `stop_time`, `time_step`.
- `Coefficients`: `C1`, `C2`.
- `Outputs`: `output_directory`, `track_file`, `report_file`, `activate_multilayer_shapefile`, `particle_map_file`.
- `Analysis`: `time_interval_filter`, `time_range`.
- `Plots`: `study_region`, `dpi`, `particles_to_show`, `plot_objects`, `track_lines`, `show_particle_label`, `label_color`, `label_fontsize`, `tack_linewidth`, `track_linestyle`, `track_colortable`, `legend_position`, `legend_fontsize`, `legend_numcol`, `hidden_legend`.

---

## Parallel Execution (`pSPartA.py`)

`pSPartA.py` automatically detects all available CPU cores via `os.process_cpu_count()`:
- **Standard Python 3.14:** Uses `concurrent.futures.ProcessPoolExecutor` with per-worker initialization (`_init_worker`).
- **Free-threaded Python 3.14 (`python3.14t`):** Automatically detects `sys._is_gil_enabled() == False` and switches to `concurrent.futures.ThreadPoolExecutor` with zero-copy shared memory.
- Progress is reported in real time as particles complete using `concurrent.futures.as_completed`.

## License and Mandatory Citation

This software (**Simple-Particle Analysis Model: SPartA, pSPartA & operSPartA**, Version 3.0) is freely available for academic, research, educational, governmental, and commercial use under the **Apache License, Version 2.0**, supplemented by an **Additional Mandatory Citation and Attribution Clause** (`LICENSE_CLAUSE.txt`).

### NOTICE — Mandatory Citation Requirement

By downloading, executing, modifying, or redistributing this software (in whole or in part), you agree to the terms of the Apache License 2.0 and the supplemental citation conditions specified in the `NOTICE` and `LICENSE_CLAUSE.txt` files. **If you use this software to generate results, trajectories, maps, datasets, or analyses included in any scientific publication, technical report, thesis, presentation, or derivative work, you are strictly required to cite the following reference:**

> Varona, H. L., Calzada, A. E., Noriega, C. E., Herold-Garcia, S., Lira, S. M. A., de Lima, C. D. M., Araujo, J., de Luna, E. O., Bruto, L., Rodriguez, A., & Araujo, M. (2023). *Simple-Particle Analysis Model (SPartA, pSPartA & operSPartA)* (Version 3.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.24444691

```bibtex
@software{varona_2023_sparta,
  author       = {Varona, Humberto L. and
                  Calzada, Amilcar E. and
                  Noriega, Carlos E. and
                  Herold-Garcia, Silena and
                  M. A. Lira, Simone and
                  D. M. de Lima, Cynthia and
                  Araujo, Julia and
                  Luna, Emerson Ozias de and
                  Bruto, Leonardo and
                  Rodriguez, Alejandro and
                  Araujo, Moacyr},
  title        = {{Simple-Particle Analysis Model (SPartA, pSPartA \& operSPartA)}},
  month        = nov,
  year         = 2023,
  publisher    = {Zenodo},
  version      = {3.0},
  doi          = {10.5281/zenodo.24444691},
  url          = {[https://doi.org/10.5281/zenodo.24444691](https://doi.org/10.5281/zenodo.24444691)}
}

