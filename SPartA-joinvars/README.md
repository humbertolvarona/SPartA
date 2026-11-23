# SPartA-joinvars (v1.0)

Interactive **Python 3.14 + Tkinter 9.1** GUI tool for joining multiple NetCDF files into a single NetCDF file.

## Features
- **Merge Variables (`merge_vars`)**: Combines variables from multiple NetCDF files sharing a grid/coordinates into one file, with configurable duplicate-variable policies (`Keep first`, `Overwrite`, `Rename`).
- **Concatenate Along Dimension (`concat_dim`)**: Concatenates files along a dimension (such as `time` or `ocean_time`), with optional coordinate sorting, automatic CF time-axis re-encoding across different reference origins, and an `UNLIMITED` dimension option.
- **Auto Mode (`auto`)**: Automatically resolves whether to merge variables, concatenate along a dimension, or run a hybrid join (concatenate time slices per variable group, then merge all variables).
- **Granular Variable Selection**: Inspects dimensions, data variables, and time ranges for each file and lets you choose which variables to include.
- **Chunked Copy & Immediate Cancellation**: Copies large variables in memory-bounded chunks with a determinate progress bar and a **Stop** button that cleans up partial output files.
- **Format & Compression**: Supports `NETCDF4`, `NETCDF4_CLASSIC`, `NETCDF3_64BIT_OFFSET`, and `NETCDF3_CLASSIC`, with configurable `zlib` compression (levels 1–9).

## Running

```bash
.venv/bin/python SPartA-joinvars/sparta_joinvars.py
```
