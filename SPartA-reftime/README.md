# SPartA-reftime (v2.0b)

Interactive **Python 3.14 + Tkinter 9.1** NetCDF temporal refinement and coarsening tool for **SPartA** and Lagrangian particle-tracking models.

## Features
- **Automatic CF Time Detection**: Detects time coordinate variables (`time`, `ocean_time`, `MT`, `valid_time`, etc.), parses CF calendars (`standard`, `gregorian`, `proleptic_gregorian`, `noleap`, `360_day`, `julian`), and identifies native temporal resolution ($\Delta t$) and regularity.
- **Logical Temporal Combinations for Lagrangian Models**:
  - **Refinement (Upsampling, $\Delta t_{\text{dst}} < \Delta t_{\text{src}}$)**: E.g., daily (24 h) data can be refined to `12 h`, `8 h`, `6 h`, `4 h`, `3 h`, `2 h`, `1 h`, `30 min`, `15 min`, `10 min`, or `5 min`.
  - **Coarsening (Downsampling, $\Delta t_{\text{dst}} > \Delta t_{\text{src}}$)**: E.g., `1 h` data can be coarsened to `2 h`, `3 h`, `4 h`, `6 h`, `8 h`, `12 h`, `1 day (24 h)`, `2 days`, `3 days`, `5 days`, or `7 days`.
  - **Custom & Non-Divisor Steps**: Optional custom interval in hours or toggle to display all standard metocean steps.
- **Lagrangian-Ready Temporal Methods**:
  - *Refinement*: `Linear Interpolation (C0, bound-preserving)`, `PCHIP Monotone (C1, no overshoot)`, `Cubic Spline (C2, smooth velocities)`, `Akima Spline (C1, low oscillation)`, `Nearest Neighbor (stepwise)`, and `Forward-Fill / Previous (zero-order hold)`.
  - *Coarsening*: `Time-Bin Mean (flux/velocity average)`, `Subsample / Snapshot (exact or nearest)`, `Time-Bin Median`, `Time-Bin Max`, `Time-Bin Min`, `Linear Resample`, and `PCHIP Monotone Resample`.
- **Customizable Output Suffix & Folder**: Editable output suffix (default `_reftime`) with live output filename preview and overwrite protection.
- **Responsive Progress Bar & Stop Button**: Chunked processing keeps memory bounded, updates the determinate progress bar smoothly, and allows immediate cancellation with automatic cleanup of partial output files.

## Running

```bash
.venv/bin/python SPartA-reftime/sparta_reftime.py
```
