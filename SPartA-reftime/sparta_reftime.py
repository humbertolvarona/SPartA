import ctypes
import ctypes.util
import glob
import os
import queue
import threading
import time
import tkinter as tk
import warnings
from tkinter import filedialog, messagebox, ttk

import cftime
import netCDF4 as nc
import numpy as np
from scipy.interpolate import Akima1DInterpolator, CubicSpline, PchipInterpolator

TIME_CANDIDATES = ("time", "t", "ocean_time", "mt", "valid_time", "time_counter")

STANDARD_TIME_STEPS = [
    ("5 min", 300.0, "_5min"),
    ("10 min", 600.0, "_10min"),
    ("15 min", 900.0, "_15min"),
    ("20 min", 1200.0, "_20min"),
    ("30 min", 1800.0, "_30min"),
    ("1 h", 3600.0, "_1h"),
    ("2 h", 7200.0, "_2h"),
    ("3 h", 10800.0, "_3h"),
    ("4 h", 14400.0, "_4h"),
    ("6 h", 21600.0, "_6h"),
    ("8 h", 28800.0, "_8h"),
    ("12 h", 43200.0, "_12h"),
    ("1 day (24 h)", 86400.0, "_1d"),
    ("2 days (48 h)", 172800.0, "_2d"),
    ("3 days (72 h)", 259200.0, "_3d"),
    ("5 days (pentad)", 432000.0, "_5d"),
    ("7 days (weekly)", 604800.0, "_7d"),
]

REFINE_METHODS = [
    "Linear Interpolation (C0, bound-preserving)",
    "PCHIP Monotone (C1, no overshoot)",
    "Cubic Spline (C2, smooth velocities)",
    "Akima Spline (C1, low oscillation)",
    "Nearest Neighbor (stepwise)",
    "Forward-Fill / Previous (zero-order hold)",
]

COARSEN_METHODS = [
    "Time-Bin Mean (flux/velocity average)",
    "Subsample / Snapshot (exact or nearest)",
    "Time-Bin Median (outlier-robust)",
    "Time-Bin Max (extreme forcing)",
    "Time-Bin Min (minimum per interval)",
    "Linear Resample",
    "PCHIP Monotone Resample",
]

def silence_hdf5_thread():
    nc_dir = os.path.dirname(nc.__file__)
    patterns = [
        os.path.join(nc_dir, "*hdf5*"),
        os.path.join(nc_dir, ".dylibs", "*hdf5*"),
        os.path.join(nc_dir, "..", "netCDF4.libs", "*hdf5*"),
        os.path.join(nc_dir, "..", "netCDF4*.libs", "*hdf5*"),
    ]
    candidates = []
    for pat in patterns:
        candidates.extend(glob.glob(pat))
    sys_hdf5 = ctypes.util.find_library("hdf5")
    if sys_hdf5:
        candidates.append(sys_hdf5)
    for lib_path in candidates:
        try:
            lib = ctypes.CDLL(lib_path)
            if hasattr(lib, "H5Eset_auto2"):
                lib.H5Eset_auto2(ctypes.c_int64(0), None, None)
                return True
        except OSError:
            pass
    return False

def format_duration(seconds):
    if seconds < 60:
        return f"{seconds:.1f} s"
    if seconds < 3600:
        mins = seconds / 60.0
        return f"{mins:.0f} min" if abs(mins - round(mins)) < 1e-3 else f"{mins:.2f} min"
    if seconds < 86400:
        hrs = seconds / 3600.0
        return f"{hrs:.0f} h" if abs(hrs - round(hrs)) < 1e-3 else f"{hrs:.2f} h"
    days = seconds / 86400.0
    return f"{days:.0f} d" if abs(days - round(days)) < 1e-3 else f"{days:.2f} d"

def detect_time_var(ds):
    vars_lower = {k.lower(): k for k in ds.variables.keys()}
    for cand in TIME_CANDIDATES:
        if cand in vars_lower:
            return vars_lower[cand]
    for k, v in ds.variables.items():
        std = str(getattr(v, "standard_name", "")).lower()
        axis = str(getattr(v, "axis", "")).upper()
        units = str(getattr(v, "units", "")).lower()
        if std == "time" or axis == "T" or " since " in units:
            return k
    return ""

def parse_time_axis(ds, time_var_name):
    t_var = ds.variables[time_var_name]
    raw_vals = np.asarray(t_var[:], dtype=float)
    units = getattr(t_var, "units", None)
    calendar = getattr(t_var, "calendar", "standard")

    if raw_vals.ndim != 1 or raw_vals.size < 2:
        raise ValueError(f"Time variable '{time_var_name}' must be 1D with at least 2 time steps.")

    if units and " since " in str(units):
        dates = cftime.num2date(raw_vals, units=units, calendar=calendar)
        t0_str = dates[0].strftime("%Y-%m-%d %H:%M:%S")
        sec_units = f"seconds since {t0_str}"
        src_sec = np.asarray(cftime.date2num(dates, units=sec_units, calendar=calendar), dtype=float)
    else:

        dates = None
        src_sec = raw_vals - raw_vals[0]
        sec_units = None

    diffs = np.diff(src_sec)
    if np.any(diffs <= 0):
        raise ValueError("Time axis must be strictly increasing.")

    dt_median = float(np.median(diffs))
    is_regular = bool(np.all(np.abs(diffs - dt_median) <= max(1.0, 1e-4 * dt_median)))

    return {
        "var_name": time_var_name,
        "dim_name": t_var.dimensions[0],
        "raw_vals": raw_vals,
        "units": units,
        "calendar": calendar,
        "dates": dates,
        "src_sec": src_sec,
        "dt_sec": dt_median,
        "is_regular": is_regular,
        "total_sec": float(src_sec[-1] - src_sec[0]),
    }

def _is_clean_multiple(large_val, small_val, tol=1.0):
    if small_val <= 0:
        return False
    rem = large_val % small_val
    return min(rem, small_val - rem) <= tol

def get_logical_target_steps(src_dt_sec, is_regular=True, include_all=False):
    entries = []
    for label, sec, suffix in STANDARD_TIME_STEPS:
        if abs(sec - src_dt_sec) < 1.0 and is_regular:
            continue
        if sec < src_dt_sec:
            if include_all or not is_regular or _is_clean_multiple(src_dt_sec, sec):
                entries.append({
                    "display": f"Refine  ->  {label}",
                    "label": label,
                    "seconds": sec,
                    "mode": "refine",
                    "suffix": suffix,
                })
        else:
            if include_all or not is_regular or _is_clean_multiple(sec, src_dt_sec):
                entries.append({
                    "display": f"Coarsen ->  {label}",
                    "label": label,
                    "seconds": sec,
                    "mode": "coarsen",
                    "suffix": suffix,
                })

    if not entries and not include_all:
        return get_logical_target_steps(src_dt_sec, is_regular=False, include_all=True)

    return entries

def build_target_time_grid(time_info, target_dt_sec):
    total_sec = time_info["total_sec"]

    n_steps = int(np.floor((total_sec + 1.0) / target_dt_sec)) + 1
    if n_steps < 2:
        n_steps = 2
    dst_sec = np.arange(n_steps, dtype=float) * target_dt_sec
    dst_sec = dst_sec[dst_sec <= total_sec + 1.0]
    if dst_sec.size < 2:
        dst_sec = np.array([0.0, total_sec], dtype=float)

    units = time_info["units"]
    calendar = time_info["calendar"]
    dates = time_info["dates"]

    if units and " since " in str(units) and dates is not None:
        t0_str = dates[0].strftime("%Y-%m-%d %H:%M:%S")
        sec_units = f"seconds since {t0_str}"
        dst_dates = cftime.num2date(dst_sec, units=sec_units, calendar=calendar)
        dst_vals = np.asarray(cftime.date2num(dst_dates, units=units, calendar=calendar), dtype=float)
    else:
        dst_dates = None
        dst_vals = time_info["raw_vals"][0] + dst_sec

    return dst_sec, dst_vals, dst_dates

def _interp_1d_valid(src_t, y_1d, dst_t, method):
    valid = ~np.isnan(y_1d)
    n_valid = int(np.sum(valid))
    if n_valid == 0:
        return np.full(dst_t.shape, np.nan, dtype=float)
    if n_valid == 1:
        return np.full(dst_t.shape, float(y_1d[valid][0]), dtype=float)

    tv = src_t[valid]
    yv = y_1d[valid]

    if method.startswith("Linear"):
        return np.interp(dst_t, tv, yv, left=np.nan, right=np.nan)
    elif method.startswith("Nearest"):
        idx = np.searchsorted(tv, dst_t)
        idx_l = np.clip(idx - 1, 0, n_valid - 1)
        idx_r = np.clip(idx, 0, n_valid - 1)
        choose_r = np.abs(tv[idx_r] - dst_t) < np.abs(dst_t - tv[idx_l])
        nearest = np.where(choose_r, idx_r, idx_l)
        out = yv[nearest].astype(float)
        out[(dst_t < tv[0]) | (dst_t > tv[-1])] = np.nan
        return out
    elif method.startswith("Forward-Fill"):
        idx = np.searchsorted(tv, dst_t, side="right") - 1
        out = np.full(dst_t.shape, np.nan, dtype=float)
        in_range = (idx >= 0) & (dst_t <= tv[-1])
        out[in_range] = yv[idx[in_range]]
        return out
    elif method.startswith("PCHIP"):
        interp = PchipInterpolator(tv, yv, extrapolate=False)
        return interp(dst_t)
    elif method.startswith("Cubic"):
        if n_valid >= 4:
            interp = CubicSpline(tv, yv, bc_type="not-a-knot", extrapolate=False)
            return interp(dst_t)
        return np.interp(dst_t, tv, yv, left=np.nan, right=np.nan)
    elif method.startswith("Akima"):
        if n_valid >= 5:
            interp = Akima1DInterpolator(tv, yv)
            out = interp(dst_t)
            out[(dst_t < tv[0]) | (dst_t > tv[-1])] = np.nan
            return out
        elif n_valid >= 3:
            interp = PchipInterpolator(tv, yv, extrapolate=False)
            return interp(dst_t)
        return np.interp(dst_t, tv, yv, left=np.nan, right=np.nan)

    return np.interp(dst_t, tv, yv, left=np.nan, right=np.nan)

def _interpolate_block(src_t, block_2d, dst_t, method, cancel_event=None):
    nt_dst = dst_t.size
    n_cols = block_2d.shape[1]
    out = np.full((nt_dst, n_cols), np.nan, dtype=np.float32)

    all_nan = np.all(np.isnan(block_2d), axis=0)
    if np.all(all_nan):
        return out

    any_nan = np.any(np.isnan(block_2d), axis=0)
    clean_cols = ~any_nan

    if np.any(clean_cols):
        yc = block_2d[:, clean_cols].astype(float)
        if method.startswith("Linear"):

            idx = np.searchsorted(src_t, dst_t, side="right") - 1
            idx = np.clip(idx, 0, src_t.size - 2)
            t0 = src_t[idx][:, None]
            t1 = src_t[idx + 1][:, None]
            w = (dst_t[:, None] - t0) / np.maximum(t1 - t0, 1e-12)
            res = yc[idx, :] * (1.0 - w) + yc[idx + 1, :] * w
            oob = (dst_t < src_t[0]) | (dst_t > src_t[-1])
            res[oob, :] = np.nan
            out[:, clean_cols] = res.astype(np.float32)
        elif method.startswith("Nearest"):
            idx = np.searchsorted(src_t, dst_t)
            idx_l = np.clip(idx - 1, 0, src_t.size - 1)
            idx_r = np.clip(idx, 0, src_t.size - 1)
            choose_r = np.abs(src_t[idx_r] - dst_t) < np.abs(dst_t - src_t[idx_l])
            nearest = np.where(choose_r, idx_r, idx_l)
            res = yc[nearest, :]
            oob = (dst_t < src_t[0]) | (dst_t > src_t[-1])
            res[oob, :] = np.nan
            out[:, clean_cols] = res.astype(np.float32)
        elif method.startswith("Forward-Fill"):
            idx = np.searchsorted(src_t, dst_t, side="right") - 1
            res = np.full((nt_dst, yc.shape[1]), np.nan, dtype=float)
            in_range = (idx >= 0) & (dst_t <= src_t[-1])
            res[in_range, :] = yc[idx[in_range], :]
            out[:, clean_cols] = res.astype(np.float32)
        elif method.startswith("PCHIP"):
            interp = PchipInterpolator(src_t, yc, axis=0, extrapolate=False)
            out[:, clean_cols] = interp(dst_t).astype(np.float32)
        elif method.startswith("Cubic"):
            if src_t.size >= 4:
                interp = CubicSpline(src_t, yc, axis=0, bc_type="not-a-knot", extrapolate=False)
                out[:, clean_cols] = interp(dst_t).astype(np.float32)
            else:
                interp = PchipInterpolator(src_t, yc, axis=0, extrapolate=False)
                out[:, clean_cols] = interp(dst_t).astype(np.float32)
        elif method.startswith("Akima"):
            if src_t.size >= 5:
                interp = Akima1DInterpolator(src_t, yc, axis=0)
                res = interp(dst_t)
                res[(dst_t < src_t[0]) | (dst_t > src_t[-1]), :] = np.nan
                out[:, clean_cols] = res.astype(np.float32)
            else:
                interp = PchipInterpolator(src_t, yc, axis=0, extrapolate=False)
                out[:, clean_cols] = interp(dst_t).astype(np.float32)

    partial_cols = np.where(any_nan & (~all_nan))[0]
    for idx_p, col in enumerate(partial_cols):
        if cancel_event is not None and (idx_p % 64 == 0) and cancel_event.is_set():
            raise InterruptedError("Stopped by user.")
        out[:, col] = _interp_1d_valid(src_t, block_2d[:, col], dst_t, method).astype(np.float32)

    return out

def _coarsen_block(src_t, block_2d, dst_t, target_dt_sec, method, cancel_event=None):
    if method.startswith("Linear"):
        return _interpolate_block(src_t, block_2d, dst_t, "Linear", cancel_event=cancel_event)
    if method.startswith("PCHIP"):
        return _interpolate_block(src_t, block_2d, dst_t, "PCHIP", cancel_event=cancel_event)
    if method.startswith("Subsample"):
        return _interpolate_block(src_t, block_2d, dst_t, "Nearest", cancel_event=cancel_event)

    nt_dst = dst_t.size
    n_cols = block_2d.shape[1]
    out = np.full((nt_dst, n_cols), np.nan, dtype=np.float32)

    valid_cols = ~np.all(np.isnan(block_2d), axis=0)
    if not np.any(valid_cols):
        return out

    half_dt = 0.5 * target_dt_sec
    sub_block = block_2d[:, valid_cols]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for i, tc in enumerate(dst_t):
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("Stopped by user.")

            mask = (src_t >= tc - half_dt - 1e-6) & (src_t < tc + half_dt - 1e-6)
            if not np.any(mask):
                continue
            sub = sub_block[mask, :]
            if method.startswith("Time-Bin Mean"):
                out[i, valid_cols] = np.nanmean(sub, axis=0).astype(np.float32)
            elif method.startswith("Time-Bin Median"):
                out[i, valid_cols] = np.nanmedian(sub, axis=0).astype(np.float32)
            elif method.startswith("Time-Bin Max"):
                out[i, valid_cols] = np.nanmax(sub, axis=0).astype(np.float32)
            elif method.startswith("Time-Bin Min"):
                out[i, valid_cols] = np.nanmin(sub, axis=0).astype(np.float32)
    return out

def _get_chunk_plan(var_shape, t_axis, target_chunks=50, max_spatial_per_chunk=200_000):
    other_axes = [ax for ax in range(len(var_shape)) if ax != t_axis]
    if not other_axes:
        return None, [(0, 1)]
    chunk_ax = max(other_axes, key=lambda ax: var_shape[ax])
    ax_len = var_shape[chunk_ax]
    other_prod = 1
    for ax in other_axes:
        if ax != chunk_ax:
            other_prod *= max(1, int(var_shape[ax]))
    max_batch_mem = max(1, max_spatial_per_chunk // max(1, other_prod))
    batch = min(max(1, (ax_len + target_chunks - 1) // target_chunks), max_batch_mem)
    ranges = [(s, min(ax_len, s + batch)) for s in range(0, ax_len, batch)]
    return chunk_ax, ranges

def count_work_units(src_path, time_dim_name, selected_vars):
    total = 0
    with nc.Dataset(src_path, "r") as ds:
        for vname in selected_vars:
            if vname not in ds.variables:
                continue
            var = ds.variables[vname]
            if time_dim_name not in var.dimensions or var.ndim == 0:
                continue
            if var.ndim == 1:
                total += 1
            else:
                t_axis = var.dimensions.index(time_dim_name)
                _, ranges = _get_chunk_plan(var.shape, t_axis)
                total += len(ranges)
    return max(1, total)

def refine_netcdf_time(
    src_path,
    out_path,
    time_var_name,
    target_dt_sec,
    method,
    mode="refine",
    selected_vars=None,
    progress_cb=None,
    cancel_event=None,
    chunk_cb=None,
):
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    with nc.Dataset(src_path, "r") as ds_in:
        time_info = parse_time_axis(ds_in, time_var_name)
        time_dim = time_info["dim_name"]
        src_t = time_info["src_sec"]
        dst_t, dst_vals, _ = build_target_time_grid(time_info, target_dt_sec)
        nt_dst = dst_vals.size

        if selected_vars is None:
            selected_vars = [
                k for k, v in ds_in.variables.items()
                if k != time_var_name and time_dim in v.dimensions
            ]

        with nc.Dataset(out_path, "w", format=ds_in.data_model) as ds_out:

            for attr in ds_in.ncattrs():
                ds_out.setncattr(attr, ds_in.getncattr(attr))
            prev_hist = str(getattr(ds_in, "history", "")).strip()
            hist_line = (
                f"SPartA-reftime: {mode} time from {format_duration(time_info['dt_sec'])} "
                f"to {format_duration(target_dt_sec)} using '{method}'."
            )
            ds_out.setncattr("history", f"{prev_hist}\n{hist_line}".strip())

            for dname, dim in ds_in.dimensions.items():
                if dname == time_dim:
                    ds_out.createDimension(dname, nt_dst)
                else:
                    ds_out.createDimension(dname, None if dim.isunlimited() else len(dim))

            for vname, var in ds_in.variables.items():
                if vname == time_var_name:
                    v_out = ds_out.createVariable(vname, var.dtype, var.dimensions, zlib=True, complevel=2)
                    for a in var.ncattrs():
                        v_out.setncattr(a, var.getncattr(a))
                    v_out[:] = dst_vals.astype(var.dtype)
                elif time_dim not in var.dimensions:
                    v_out = ds_out.createVariable(vname, var.dtype, var.dimensions, zlib=True, complevel=2)
                    for a in var.ncattrs():
                        v_out.setncattr(a, var.getncattr(a))
                    v_out[:] = var[:]

            for vname in selected_vars:
                if cancel_event is not None and cancel_event.is_set():
                    raise InterruptedError("Stopped by user.")

                var = ds_in.variables[vname]
                if time_dim not in var.dimensions or var.ndim == 0:
                    continue

                t_axis = var.dimensions.index(time_dim)
                fill_val = np.float32(np.nan) if np.issubdtype(var.dtype, np.floating) else None
                out_dtype = "f4" if np.issubdtype(var.dtype, np.floating) else var.dtype

                if fill_val is not None:
                    v_out = ds_out.createVariable(
                        vname, out_dtype, var.dimensions, zlib=True, complevel=2, fill_value=fill_val
                    )
                else:
                    v_out = ds_out.createVariable(vname, out_dtype, var.dimensions, zlib=True, complevel=2)

                for a in var.ncattrs():
                    if a != "_FillValue":
                        v_out.setncattr(a, var.getncattr(a))

                if var.ndim == 1:
                    raw = np.asarray(var[:], dtype=float)
                    if np.ma.isMaskedArray(var[:]):
                        raw = var[:].filled(np.nan).astype(float)
                    block = raw[:, None]
                    res = (
                        _interpolate_block(src_t, block, dst_t, method)
                        if mode == "refine"
                        else _coarsen_block(src_t, block, dst_t, target_dt_sec, method)
                    )
                    v_out[:] = res[:, 0].astype(v_out.dtype)
                    if chunk_cb:
                        chunk_cb()
                    continue

                chunk_ax, ranges = _get_chunk_plan(var.shape, t_axis)
                n_chunks = len(ranges)

                for c_idx, (start, stop) in enumerate(ranges):
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError("Stopped by user.")

                    slicer = [slice(None)] * var.ndim
                    slicer[chunk_ax] = slice(start, stop)
                    raw_chunk = var[tuple(slicer)]
                    if np.ma.isMaskedArray(raw_chunk):
                        arr = raw_chunk.filled(np.nan).astype(float)
                    else:
                        arr = np.asarray(raw_chunk, dtype=float)

                    arr_t_first = np.moveaxis(arr, t_axis, 0)
                    trailing_shape = arr_t_first.shape[1:]
                    flat = arr_t_first.reshape(arr_t_first.shape[0], -1)

                    if mode == "refine":
                        res_flat = _interpolate_block(src_t, flat, dst_t, method, cancel_event=cancel_event)
                    else:
                        res_flat = _coarsen_block(src_t, flat, dst_t, target_dt_sec, method, cancel_event=cancel_event)

                    res_t_first = res_flat.reshape((nt_dst,) + trailing_shape)
                    res_chunk = np.moveaxis(res_t_first, 0, t_axis)

                    v_out[tuple(slicer)] = res_chunk.astype(v_out.dtype)

                    if chunk_cb:
                        chunk_cb()
                    if progress_cb and (c_idx % max(1, n_chunks // 10) == 0 or c_idx == n_chunks - 1):
                        progress_cb(f"{vname}: chunk {c_idx + 1}/{n_chunks}")

class SPartARefTimeApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SPartA-reftime v3.0 — Temporal NetCDF Refiner")
        self.geometry("980x760")
        self.minsize(860, 650)

        self.input_path_var = tk.StringVar()
        self.time_var_var = tk.StringVar()
        self.time_info_var = tk.StringVar(value="No NetCDF file loaded.")

        self.target_step_var = tk.StringVar()
        self.show_all_steps_var = tk.BooleanVar(value=False)
        self.use_custom_step_var = tk.BooleanVar(value=False)
        self.custom_hours_var = tk.StringVar(value="1.0")
        self.mode_badge_var = tk.StringVar(value="Mode: —")
        self.method_var = tk.StringVar(value=REFINE_METHODS[0])

        self.out_dir_var = tk.StringVar()
        self.suffix_var = tk.StringVar(value="_reftime")
        self.out_preview_var = tk.StringVar(value="Output file: —")

        self.progress_pct_var = tk.StringVar(value="0%")

        self.loaded_time_info = None
        self.logical_entries = []
        self.var_check_vars = {}

        self.msg_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.is_running = False
        self._total_chunks = 1

        self._build_ui()
        self._bind_traces()
        self._poll_queue()

    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        main = ttk.Frame(self, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        lf_in = ttk.LabelFrame(main, text="1. Input NetCDF File", padding=10)
        lf_in.pack(fill=tk.X, pady=(0, 8))

        r_file = ttk.Frame(lf_in)
        r_file.pack(fill=tk.X, pady=(0, 6))
        ttk.Entry(r_file, textvariable=self.input_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(r_file, text="Select NetCDF...", command=self._browse_input).pack(side=tk.RIGHT)

        r_meta = ttk.Frame(lf_in)
        r_meta.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(r_meta, text="Time variable:").pack(side=tk.LEFT)
        self.cmb_time_var = ttk.Combobox(r_meta, textvariable=self.time_var_var, state="readonly", width=16)
        self.cmb_time_var.pack(side=tk.LEFT, padx=(6, 14))
        self.cmb_time_var.bind("<<ComboboxSelected>>", lambda _e: self._refresh_time_metadata())
        ttk.Label(r_meta, textvariable=self.time_info_var, foreground="#1E3A5F").pack(side=tk.LEFT, fill=tk.X, expand=True)

        r_vars_hdr = ttk.Frame(lf_in)
        r_vars_hdr.pack(fill=tk.X, pady=(2, 2))
        ttk.Label(r_vars_hdr, text="Time-dependent variables to process:").pack(side=tk.LEFT)
        ttk.Button(r_vars_hdr, text="Select All", command=lambda: self._toggle_all_vars(True)).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(r_vars_hdr, text="Deselect All", command=lambda: self._toggle_all_vars(False)).pack(side=tk.RIGHT)

        self.vars_frame = ttk.Frame(lf_in)
        self.vars_frame.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(self.vars_frame, text="Load a NetCDF file to inspect variables.", foreground="#666666").pack(anchor=tk.W)

        lf_time = ttk.LabelFrame(main, text="2. Temporal Resolution & Lagrangian Interpolation / Aggregation", padding=10)
        lf_time.pack(fill=tk.X, pady=(0, 8))

        r_step = ttk.Frame(lf_time)
        r_step.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(r_step, text="Target time step:").pack(side=tk.LEFT)
        self.cmb_target_step = ttk.Combobox(r_step, textvariable=self.target_step_var, state="readonly", width=26)
        self.cmb_target_step.pack(side=tk.LEFT, padx=(6, 12))
        self.cmb_target_step.bind("<<ComboboxSelected>>", lambda _e: self._on_target_changed())

        ttk.Checkbutton(
            r_step,
            text="Custom (hours):",
            variable=self.use_custom_step_var,
            command=self._on_target_changed,
        ).pack(side=tk.LEFT)
        self.ent_custom = ttk.Entry(r_step, textvariable=self.custom_hours_var, width=8, state=tk.DISABLED)
        self.ent_custom.pack(side=tk.LEFT, padx=(4, 14))

        ttk.Checkbutton(
            r_step,
            text="Show all standard steps",
            variable=self.show_all_steps_var,
            command=self._populate_target_steps,
        ).pack(side=tk.LEFT)

        r_mode = ttk.Frame(lf_time)
        r_mode.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(r_mode, text="Method:").pack(side=tk.LEFT)
        self.cmb_method = ttk.Combobox(r_mode, textvariable=self.method_var, values=REFINE_METHODS, state="readonly", width=38)
        self.cmb_method.pack(side=tk.LEFT, padx=(6, 14))
        self.lbl_mode_badge = ttk.Label(r_mode, textvariable=self.mode_badge_var, foreground="#0F5132")
        self.lbl_mode_badge.pack(side=tk.LEFT)

        lf_out = ttk.LabelFrame(main, text="3. Output Settings", padding=10)
        lf_out.pack(fill=tk.X, pady=(0, 8))

        r_out1 = ttk.Frame(lf_out)
        r_out1.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(r_out1, text="Output folder:").pack(side=tk.LEFT)
        ttk.Entry(r_out1, textvariable=self.out_dir_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        ttk.Button(r_out1, text="Browse...", command=self._browse_out_dir).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Label(r_out1, text="Output suffix:").pack(side=tk.LEFT)
        ttk.Entry(r_out1, textvariable=self.suffix_var, width=16).pack(side=tk.LEFT, padx=(6, 0))

        r_out2 = ttk.Frame(lf_out)
        r_out2.pack(fill=tk.X)
        ttk.Label(r_out2, textvariable=self.out_preview_var, foreground="#333333").pack(side=tk.LEFT)

        run_row = ttk.Frame(main)
        run_row.pack(fill=tk.X, pady=(0, 6))
        self.btn_run = ttk.Button(run_row, text="Run Time Refinement", command=self._start_processing)
        self.btn_run.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_stop = ttk.Button(run_row, text="Stop", command=self._stop_processing, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 10))
        self.progress = ttk.Progressbar(run_row, orient=tk.HORIZONTAL, mode="determinate")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Label(run_row, textvariable=self.progress_pct_var, width=18, anchor=tk.E).pack(side=tk.RIGHT)

        self.log_text = tk.Text(main, height=11, wrap=tk.WORD, state=tk.DISABLED, font=("TkFixedFont", 10))
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _bind_traces(self):
        self.out_dir_var.trace_add("write", lambda *_: self._update_output_preview())
        self.suffix_var.trace_add("write", lambda *_: self._update_output_preview())
        self.custom_hours_var.trace_add("write", lambda *_: self._on_target_changed())

    def _log(self, msg):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="Select Input NetCDF File",
            filetypes=[("NetCDF Files", "*.nc *.nc4"), ("All Files", "*.*")],
        )
        if path:
            self.load_input_file(path)

    def _browse_out_dir(self):
        d = filedialog.askdirectory(title="Select Output Folder")
        if d:
            self.out_dir_var.set(d)

    def load_input_file(self, path):
        try:
            with nc.Dataset(path, "r") as ds:
                var_names = list(ds.variables.keys())
                t_var = detect_time_var(ds)
                self.cmb_time_var["values"] = var_names
                if t_var:
                    self.time_var_var.set(t_var)
                elif var_names:
                    self.time_var_var.set(var_names[0])

            self.input_path_var.set(path)
            if not self.out_dir_var.get().strip():
                self.out_dir_var.set(os.path.dirname(path))
            self._refresh_time_metadata()
            self._log(f"Loaded NetCDF file: {path}")
        except Exception as exc:
            messagebox.showerror("Load Error", f"Failed to load NetCDF file:\n{exc}")

    def _refresh_time_metadata(self):
        path = self.input_path_var.get().strip()
        t_var = self.time_var_var.get().strip()
        if not path or not t_var or not os.path.isfile(path):
            return
        try:
            with nc.Dataset(path, "r") as ds:
                info = parse_time_axis(ds, t_var)
                self.loaded_time_info = info
                n_t = info["src_sec"].size
                dt_str = format_duration(info["dt_sec"])
                reg_str = "regular" if info["is_regular"] else "irregular"
                if info["dates"] is not None:
                    t_start = info["dates"][0].strftime("%Y-%m-%d %H:%M")
                    t_end = info["dates"][-1].strftime("%Y-%m-%d %H:%M")
                    range_str = f"{t_start} -> {t_end}"
                else:
                    range_str = f"{info['raw_vals'][0]:.2f} -> {info['raw_vals'][-1]:.2f}"
                self.time_info_var.set(
                    f"Steps: {n_t} | Native Δt: {dt_str} ({reg_str}) | {range_str} | Cal: {info['calendar']}"
                )
                self._populate_var_checkboxes(ds, info["dim_name"], t_var)
            self._populate_target_steps()
        except Exception as exc:
            self.loaded_time_info = None
            self.time_info_var.set(f"Time parse error: {exc}")

    def _populate_var_checkboxes(self, ds, time_dim, time_var):
        for child in self.vars_frame.winfo_children():
            child.destroy()
        self.var_check_vars.clear()

        t_vars = [
            (k, v.shape)
            for k, v in ds.variables.items()
            if k != time_var and time_dim in v.dimensions
        ]
        if not t_vars:
            ttk.Label(self.vars_frame, text="No time-dependent variables found.", foreground="#B02A37").pack(anchor=tk.W)
            return

        col_count = 4
        for idx, (vname, shape) in enumerate(t_vars):
            var_bool = tk.BooleanVar(value=True)
            self.var_check_vars[vname] = var_bool
            lbl = f"{vname} {shape}"
            cb = ttk.Checkbutton(self.vars_frame, text=lbl, variable=var_bool)
            cb.grid(row=idx // col_count, column=idx % col_count, sticky=tk.W, padx=(0, 12), pady=1)

    def _toggle_all_vars(self, state):
        for b in self.var_check_vars.values():
            b.set(state)

    def _populate_target_steps(self):
        if not self.loaded_time_info:
            return
        entries = get_logical_target_steps(
            self.loaded_time_info["dt_sec"],
            is_regular=self.loaded_time_info["is_regular"],
            include_all=self.show_all_steps_var.get(),
        )
        self.logical_entries = entries
        displays = [e["display"] for e in entries]
        self.cmb_target_step["values"] = displays
        if displays:

            default_idx = 0
            for i, e in enumerate(entries):
                if e["mode"] == "refine":
                    default_idx = i
                    break
            self.target_step_var.set(displays[default_idx])
        self._on_target_changed()

    def _get_selected_target(self):
        if not self.loaded_time_info:
            return None
        src_dt = self.loaded_time_info["dt_sec"]
        if self.use_custom_step_var.get():
            try:
                hrs = float(self.custom_hours_var.get().strip())
                if hrs <= 0:
                    return None
                sec = hrs * 3600.0
                mode = "refine" if sec < src_dt else "coarsen"
                tag = f"_{hrs:g}h"
                return sec, mode, tag
            except ValueError:
                return None

        sel = self.target_step_var.get()
        for e in self.logical_entries:
            if e["display"] == sel:
                return e["seconds"], e["mode"], e["suffix"]
        return None

    def _on_target_changed(self):
        is_custom = self.use_custom_step_var.get()
        self.ent_custom.configure(state=tk.NORMAL if is_custom else tk.DISABLED)
        self.cmb_target_step.configure(state=tk.DISABLED if is_custom else "readonly")

        target = self._get_selected_target()
        if not target or not self.loaded_time_info:
            self.mode_badge_var.set("Mode: —")
            self._update_output_preview()
            return

        sec, mode, _ = target
        _, dst_vals, _ = build_target_time_grid(self.loaded_time_info, sec)
        n_src = self.loaded_time_info["src_sec"].size
        n_dst = dst_vals.size

        if mode == "refine":
            self.mode_badge_var.set(f"REFINEMENT (Upsampling): {n_src} -> {n_dst} steps")
            self.lbl_mode_badge.configure(foreground="#0D6EFD")
            if list(self.cmb_method["values"]) != REFINE_METHODS:
                self.cmb_method["values"] = REFINE_METHODS
                self.method_var.set(REFINE_METHODS[0])
        else:
            self.mode_badge_var.set(f"COARSENING (Downsampling): {n_src} -> {n_dst} steps")
            self.lbl_mode_badge.configure(foreground="#B45309")
            if list(self.cmb_method["values"]) != COARSEN_METHODS:
                self.cmb_method["values"] = COARSEN_METHODS
                self.method_var.set(COARSEN_METHODS[0])

        self._update_output_preview()

    def _update_output_preview(self):
        in_path = self.input_path_var.get().strip()
        if not in_path:
            self.out_preview_var.set("Output file: —")
            return
        out_dir = self.out_dir_var.get().strip() or os.path.dirname(in_path)
        suffix = self.suffix_var.get().strip() or "_reftime"
        base, ext = os.path.splitext(os.path.basename(in_path))
        out_path = os.path.join(out_dir, f"{base}{suffix}{ext}")
        self.out_preview_var.set(f"Output file: {out_path}")

    def _start_processing(self):
        if self.is_running:
            return

        in_path = self.input_path_var.get().strip()
        if not in_path or not os.path.isfile(in_path):
            messagebox.showwarning("Missing Input", "Please select a valid input NetCDF file.")
            return

        t_var = self.time_var_var.get().strip()
        if not t_var or not self.loaded_time_info:
            messagebox.showwarning("Invalid Time Axis", "Please select a valid time variable.")
            return

        target = self._get_selected_target()
        if not target:
            messagebox.showwarning("Invalid Target Step", "Please enter a valid positive target time step.")
            return

        selected_vars = [k for k, v in self.var_check_vars.items() if v.get()]
        if not selected_vars:
            messagebox.showwarning("No Variables Selected", "Please select at least one time-dependent variable.")
            return

        target_dt_sec, mode, _ = target
        method = self.method_var.get()
        out_dir = self.out_dir_var.get().strip() or os.path.dirname(in_path)
        suffix = self.suffix_var.get().strip() or "_reftime"
        base, ext = os.path.splitext(os.path.basename(in_path))
        out_path = os.path.join(out_dir, f"{base}{suffix}{ext}")

        if os.path.abspath(out_path) == os.path.abspath(in_path):
            messagebox.showwarning("Overwrite Guard", "Output path cannot match the input file. Please change the suffix or folder.")
            return

        total_chunks = count_work_units(in_path, self.loaded_time_info["dim_name"], selected_vars)
        self._total_chunks = total_chunks

        self.is_running = True
        self.cancel_event.clear()
        self.btn_run.configure(state=tk.DISABLED)
        self.btn_stop.configure(state=tk.NORMAL)
        self.progress.configure(maximum=total_chunks, value=0)
        self.progress_pct_var.set(f"0% (0/{total_chunks})")

        self._log(
            f"Starting temporal {mode}: {format_duration(self.loaded_time_info['dt_sec'])} -> "
            f"{format_duration(target_dt_sec)} | Method: {method}"
        )
        self._log(f"Output: {out_path}")

        def _worker():
            silence_hdf5_thread()
            t0 = time.perf_counter()
            done_chunks = 0

            def _on_chunk():
                nonlocal done_chunks
                done_chunks += 1
                self.msg_queue.put(("progress", done_chunks))

            try:
                refine_netcdf_time(
                    src_path=in_path,
                    out_path=out_path,
                    time_var_name=t_var,
                    target_dt_sec=target_dt_sec,
                    method=method,
                    mode=mode,
                    selected_vars=selected_vars,
                    progress_cb=lambda m: self.msg_queue.put(("log", f"  {m}")),
                    cancel_event=self.cancel_event,
                    chunk_cb=_on_chunk,
                )
                elapsed = time.perf_counter() - t0
                self.msg_queue.put(("done", f"Completed successfully in {elapsed:.2f} s -> {out_path}"))
            except InterruptedError:
                elapsed = time.perf_counter() - t0
                if os.path.isfile(out_path):
                    try:
                        os.remove(out_path)
                    except OSError:
                        pass
                self.msg_queue.put(("done", f"Stopped by user after {elapsed:.2f} s (partial output removed)."))
            except Exception as exc:
                if os.path.isfile(out_path):
                    try:
                        os.remove(out_path)
                    except OSError:
                        pass
                self.msg_queue.put(("done", f"ERROR: {exc}"))

        threading.Thread(target=_worker, daemon=True).start()

    def _stop_processing(self):
        if self.is_running and not self.cancel_event.is_set():
            self.cancel_event.set()
            self.btn_stop.configure(state=tk.DISABLED)
            self._log("Stop requested — halting after current chunk...")

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    self.progress["value"] = payload
                    tot = max(1, self._total_chunks)
                    pct = min(100.0, 100.0 * payload / tot)
                    self.progress_pct_var.set(f"{pct:.0f}% ({payload}/{tot})")
                    self.update_idletasks()
                elif kind == "done":
                    self._log(payload)
                    self.is_running = False
                    self.btn_run.configure(state=tk.NORMAL)
                    self.btn_stop.configure(state=tk.DISABLED)
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)

def main():
    app = SPartARefTimeApp()
    app.mainloop()

if __name__ == "__main__":
    main()
