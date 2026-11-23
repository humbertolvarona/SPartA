import ctypes
import ctypes.util
import glob
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cftime
import netCDF4 as nc
import numpy as np

APP_NAME = "SPartA-joinvars"
APP_VERSION = "v3.0"

TIME_CANDIDATES = ("time", "t", "ocean_time", "mt", "valid_time", "time_counter")

JOIN_MODES = [
    ("merge_vars", "Merge variables (same grid / coordinates)"),
    ("concat_dim", "Concatenate along dimension (e.g., time)"),
    ("auto", "Auto (merge variables & concatenate dimension)"),
]

CONFLICT_POLICIES = [
    ("keep_first", "Keep first (skip duplicates)"),
    ("overwrite", "Overwrite (last file wins)"),
    ("rename", "Rename duplicates (_1, _2, ...)"),
]

NC_FORMATS = [
    "NETCDF4",
    "NETCDF4_CLASSIC",
    "NETCDF3_64BIT_OFFSET",
    "NETCDF3_CLASSIC",
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

def is_cf_time_var(var):
    units = str(getattr(var, "units", "")).lower()
    return " since " in units

def inspect_netcdf(path):
    with nc.Dataset(path, "r") as ds:
        ds.set_auto_maskandscale(False)
        dims = {}
        for dname, dim in ds.dimensions.items():
            dims[dname] = (len(dim), dim.isunlimited())

        time_var = detect_time_var(ds)
        variables = []
        for vname, var in ds.variables.items():
            is_coord = (vname in ds.dimensions) or (
                var.ndim == 1 and len(var.dimensions) == 1 and var.dimensions[0] == vname
            )
            variables.append(
                {
                    "name": vname,
                    "dimensions": tuple(var.dimensions),
                    "shape": tuple(var.shape),
                    "dtype": str(var.dtype),
                    "units": str(getattr(var, "units", "")),
                    "long_name": str(getattr(var, "long_name", "")),
                    "is_coord": is_coord,
                }
            )

        time_range = ""
        if time_var and time_var in ds.variables:
            tv = ds.variables[time_var]
            if tv.size > 0:
                try:
                    if is_cf_time_var(tv):
                        cal = str(getattr(tv, "calendar", "standard"))
                        t0 = cftime.num2date(float(tv[0]), tv.units, calendar=cal)
                        t1 = cftime.num2date(float(tv[-1]), tv.units, calendar=cal)
                        time_range = f"{t0} .. {t1}"
                    else:
                        time_range = f"{tv[0]} .. {tv[-1]}"
                except Exception:
                    time_range = f"n={tv.size}"

        return {
            "path": path,
            "filename": os.path.basename(path),
            "size_mb": os.path.getsize(path) / (1024.0 * 1024.0),
            "data_model": ds.data_model,
            "dimensions": dims,
            "variables": variables,
            "time_var": time_var,
            "time_range": time_range,
        }

def _copy_var_attrs(src_var, dst_var):
    for attr in src_var.ncattrs():
        if attr == "_FillValue":
            continue
        dst_var.setncattr(attr, src_var.getncattr(attr))

def _create_matching_var(dst_ds, name, src_var, dims_override=None, nc_format="NETCDF4", zlib=True, complevel=4):
    dims = dims_override if dims_override is not None else src_var.dimensions
    fill_val = src_var.getncattr("_FillValue") if "_FillValue" in src_var.ncattrs() else None
    use_zlib = bool(zlib) and nc_format.startswith("NETCDF4")
    kwargs = {"dimensions": dims}
    if fill_val is not None:
        kwargs["fill_value"] = fill_val
    if use_zlib and len(dims) > 0:
        kwargs["zlib"] = True
        kwargs["complevel"] = int(complevel)
    dst_var = dst_ds.createVariable(name, src_var.dtype, **kwargs)
    _copy_var_attrs(src_var, dst_var)
    return dst_var

def _copy_var_chunked(src_var, dst_var, dst_offset_axis0=0, cancel_event=None, progress_cb=None, target_elems=4_000_000):
    if src_var.ndim == 0:
        dst_var[...] = src_var[...]
        if progress_cb:
            progress_cb(1)
        return

    n0 = src_var.shape[0]
    if n0 == 0:
        if progress_cb:
            progress_cb(1)
        return

    slice_elems = 1
    for s in src_var.shape[1:]:
        slice_elems *= max(1, s)
    step = max(1, min(n0, target_elems // max(1, slice_elems)))

    for start in range(0, n0, step):
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Process canceled by user.")
        end = min(n0, start + step)
        data = src_var[start:end, ...]
        dst_var[dst_offset_axis0 + start : dst_offset_axis0 + end, ...] = data
        if progress_cb:
            progress_cb(end - start)

def _get_sort_key_for_file(path, concat_dim):
    with nc.Dataset(path, "r") as ds:
        ds.set_auto_maskandscale(False)
        if concat_dim in ds.variables:
            cv = ds.variables[concat_dim]
            if cv.size > 0:
                if is_cf_time_var(cv):
                    cal = str(getattr(cv, "calendar", "standard"))
                    dt = cftime.num2date(float(cv[0]), cv.units, calendar=cal)
                    return (0, dt.toordinal(), getattr(dt, "hour", 0), getattr(dt, "minute", 0), getattr(dt, "second", 0))
                return (0, float(cv[0]))
    return (1, path)

def _ensure_dimension(dst_ds, dname, length, unlimited=False):
    if dname in dst_ds.dimensions:
        existing = dst_ds.dimensions[dname]
        if not existing.isunlimited() and not unlimited and len(existing) != length:
            raise ValueError(
                f"Incompatible dimension '{dname}': expected {len(existing)}, found {length}."
            )
        return
    dst_ds.createDimension(dname, None if unlimited else length)

def run_join_job(
    file_paths,
    output_path,
    mode,
    selected_vars,
    concat_dim,
    sort_by_coord,
    unlimited_concat,
    conflict_policy,
    nc_format,
    use_zlib,
    complevel,
    copy_global_attrs,
    cancel_event,
    msg_queue,
):
    silence_hdf5_thread()

    def log(text):
        msg_queue.put(("log", text))

    def set_progress(done, total):
        msg_queue.put(("progress", done, max(1, total)))

    tmp_output = output_path + ".part"
    if os.path.exists(tmp_output):
        os.remove(tmp_output)

    try:
        if len(file_paths) < 2:
            raise ValueError("At least 2 NetCDF files are required.")

        effective_mode = mode
        if mode == "auto":
            infos = [inspect_netcdf(p) for p in file_paths]
            data_var_sets = [
                {v["name"] for v in info["variables"] if not v["is_coord"] and v["name"] in selected_vars}
                for info in infos
            ]
            all_vars_union = set.union(*data_var_sets) if data_var_sets else set()
            common_data_vars = set.intersection(*data_var_sets) if data_var_sets else set()
            has_repeated_vars = any(
                sum(1 for vs in data_var_sets if v in vs) > 1 for v in all_vars_union
            )
            if concat_dim and all(concat_dim in info["dimensions"] for info in infos) and has_repeated_vars:
                if common_data_vars == all_vars_union and len(all_vars_union) > 0:
                    effective_mode = "concat_dim"
                else:
                    effective_mode = "hybrid"
            else:
                effective_mode = "merge_vars"
            log(f"Auto mode resolved to: {effective_mode}")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        if effective_mode == "merge_vars":
            _exec_merge_vars(
                file_paths, tmp_output, selected_vars, conflict_policy,
                nc_format, use_zlib, complevel, copy_global_attrs,
                cancel_event, log, set_progress,
            )
        elif effective_mode == "concat_dim":
            _exec_concat_dim(
                file_paths, tmp_output, selected_vars, concat_dim,
                sort_by_coord, unlimited_concat, nc_format, use_zlib,
                complevel, copy_global_attrs, cancel_event, log, set_progress,
            )
        else:
            _exec_hybrid(
                file_paths, tmp_output, selected_vars, concat_dim,
                sort_by_coord, unlimited_concat, conflict_policy,
                nc_format, use_zlib, complevel, copy_global_attrs,
                cancel_event, log, set_progress,
            )

        if cancel_event.is_set():
            raise InterruptedError("Process canceled by user.")

        if os.path.exists(output_path):
            os.remove(output_path)
        os.replace(tmp_output, output_path)
        size_mb = os.path.getsize(output_path) / (1024.0 * 1024.0)
        log(f"Joined file saved successfully: {output_path} ({size_mb:.2f} MB)")
        msg_queue.put(("done", output_path))

    except InterruptedError as exc:
        if os.path.exists(tmp_output):
            try:
                os.remove(tmp_output)
            except OSError:
                pass
        msg_queue.put(("cancelled", str(exc)))
    except Exception as exc:
        if os.path.exists(tmp_output):
            try:
                os.remove(tmp_output)
            except OSError:
                pass
        msg_queue.put(("error", str(exc)))

def _exec_merge_vars(
    file_paths, tmp_output, selected_vars, conflict_policy,
    nc_format, use_zlib, complevel, copy_global_attrs,
    cancel_event, log, set_progress,
):
    total_units = 0
    for p in file_paths:
        with nc.Dataset(p, "r") as ds:
            for vname, var in ds.variables.items():
                is_coord = vname in ds.dimensions
                if is_coord or vname in selected_vars:
                    total_units += max(1, var.shape[0] if var.ndim > 0 else 1)

    done_units = 0
    set_progress(0, total_units)

    def advance(n):
        nonlocal done_units
        done_units += n
        set_progress(done_units, total_units)

    written_vars = {}

    with nc.Dataset(tmp_output, "w", format=nc_format) as dst:
        dst.set_auto_maskandscale(False)

        for idx, path in enumerate(file_paths):
            if cancel_event.is_set():
                raise InterruptedError("Process canceled by user.")

            log(f"Reading [{idx + 1}/{len(file_paths)}]: {os.path.basename(path)}")
            with nc.Dataset(path, "r") as src:
                src.set_auto_maskandscale(False)

                if idx == 0 and copy_global_attrs:
                    for attr in src.ncattrs():
                        dst.setncattr(attr, src.getncattr(attr))
                    hist = str(getattr(dst, "history", ""))
                    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    entry = f"[{stamp}] Joined {len(file_paths)} files with {APP_NAME} {APP_VERSION}"
                    dst.setncattr("history", f"{entry}\n{hist}".strip())

                vars_to_copy = []
                needed_dims = set()
                for vname, var in src.variables.items():
                    is_coord = vname in src.dimensions
                    if vname in selected_vars or is_coord:
                        vars_to_copy.append(vname)
                        needed_dims.update(var.dimensions)

                for dname in needed_dims:
                    dim = src.dimensions[dname]
                    _ensure_dimension(dst, dname, len(dim), unlimited=dim.isunlimited())

                for vname in vars_to_copy:
                    if cancel_event.is_set():
                        raise InterruptedError("Process canceled by user.")

                    src_var = src.variables[vname]
                    is_coord = vname in src.dimensions
                    target_name = vname

                    if vname in dst.variables:
                        if is_coord:
                            advance(max(1, src_var.shape[0] if src_var.ndim > 0 else 1))
                            continue
                        if conflict_policy == "keep_first":
                            log(f"  Skipping duplicate variable '{vname}' (keep first).")
                            advance(max(1, src_var.shape[0] if src_var.ndim > 0 else 1))
                            continue
                        elif conflict_policy == "overwrite":
                            log(f"  Overwriting variable '{vname}' from {os.path.basename(path)}.")
                            dst_var = dst.variables[vname]
                            if dst_var.dimensions != src_var.dimensions or dst_var.shape != src_var.shape:
                                raise ValueError(
                                    f"Cannot overwrite '{vname}': incompatible shape {dst_var.shape} vs {src_var.shape}."
                                )
                            _copy_var_chunked(src_var, dst_var, 0, cancel_event, advance)
                            continue
                        else:
                            count = written_vars.get(vname, 1)
                            while f"{vname}_{count}" in dst.variables:
                                count += 1
                            target_name = f"{vname}_{count}"
                            written_vars[vname] = count + 1
                            log(f"  Renaming duplicate variable '{vname}' -> '{target_name}'.")

                    written_vars.setdefault(vname, 1)
                    dst_var = _create_matching_var(
                        dst, target_name, src_var,
                        nc_format=nc_format, zlib=use_zlib, complevel=complevel,
                    )
                    _copy_var_chunked(src_var, dst_var, 0, cancel_event, advance)

def _exec_concat_dim(
    file_paths, tmp_output, selected_vars, concat_dim,
    sort_by_coord, unlimited_concat, nc_format, use_zlib,
    complevel, copy_global_attrs, cancel_event, log, set_progress,
):
    if not concat_dim:
        raise ValueError("Please specify a concatenation dimension (e.g., 'time').")

    ordered_paths = list(file_paths)
    if sort_by_coord:
        ordered_paths.sort(key=lambda p: _get_sort_key_for_file(p, concat_dim))
        log("Files sorted by concatenation coordinate:")
        for p in ordered_paths:
            log(f"  • {os.path.basename(p)}")

    concat_lengths = []
    total_units = 0
    for idx, p in enumerate(ordered_paths):
        with nc.Dataset(p, "r") as ds:
            if concat_dim not in ds.dimensions:
                raise ValueError(f"File '{os.path.basename(p)}' does not contain dimension '{concat_dim}'.")
            clen = len(ds.dimensions[concat_dim])
            concat_lengths.append(clen)
            for vname, var in ds.variables.items():
                is_coord = vname in ds.dimensions
                if vname in selected_vars or is_coord:
                    if concat_dim in var.dimensions or idx == 0:
                        total_units += max(1, var.shape[0] if var.ndim > 0 else 1)

    total_concat_len = sum(concat_lengths)
    done_units = 0
    set_progress(0, total_units)

    def advance(n):
        nonlocal done_units
        done_units += n
        set_progress(done_units, total_units)

    ref_time_units = None
    ref_time_cal = "standard"

    with nc.Dataset(tmp_output, "w", format=nc_format) as dst:
        dst.set_auto_maskandscale(False)

        with nc.Dataset(ordered_paths[0], "r") as src0:
            src0.set_auto_maskandscale(False)
            if copy_global_attrs:
                for attr in src0.ncattrs():
                    dst.setncattr(attr, src0.getncattr(attr))
                hist = str(getattr(dst, "history", ""))
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                entry = f"[{stamp}] Concatenated {len(ordered_paths)} files along '{concat_dim}' with {APP_NAME} {APP_VERSION}"
                dst.setncattr("history", f"{entry}\n{hist}".strip())

            for dname, dim in src0.dimensions.items():
                if dname == concat_dim:
                    _ensure_dimension(dst, dname, total_concat_len, unlimited=unlimited_concat)
                else:
                    _ensure_dimension(dst, dname, len(dim), unlimited=dim.isunlimited())

            for vname, src_var in src0.variables.items():
                is_coord = vname in src0.dimensions
                if not (is_coord or vname in selected_vars):
                    continue
                if vname == concat_dim and is_cf_time_var(src_var):
                    ref_time_units = str(src_var.units)
                    ref_time_cal = str(getattr(src_var, "calendar", "standard"))

                dst_var = _create_matching_var(
                    dst, vname, src_var,
                    nc_format=nc_format, zlib=use_zlib, complevel=complevel,
                )
                if concat_dim not in src_var.dimensions:
                    _copy_var_chunked(src_var, dst_var, 0, cancel_event, advance)

        offset = 0
        for idx, path in enumerate(ordered_paths):
            if cancel_event.is_set():
                raise InterruptedError("Process canceled by user.")
            clen = concat_lengths[idx]
            log(f"Concatenating [{idx + 1}/{len(ordered_paths)}]: {os.path.basename(path)} ({concat_dim}={clen})")

            with nc.Dataset(path, "r") as src:
                src.set_auto_maskandscale(False)
                for vname, dst_var in dst.variables.items():
                    if concat_dim not in dst_var.dimensions:
                        continue
                    if vname not in src.variables:
                        raise ValueError(
                            f"Variable '{vname}' is missing in '{os.path.basename(path)}'."
                        )
                    src_var = src.variables[vname]
                    if src_var.dimensions != dst_var.dimensions:
                        raise ValueError(
                            f"Incompatible dimensions for '{vname}' in '{os.path.basename(path)}': "
                            f"{src_var.dimensions} vs {dst_var.dimensions}."
                        )

                    if vname == concat_dim and ref_time_units and is_cf_time_var(src_var):
                        src_units = str(src_var.units)
                        src_cal = str(getattr(src_var, "calendar", ref_time_cal))
                        if src_units != ref_time_units or src_cal != ref_time_cal:
                            raw_t = np.asarray(src_var[:], dtype=float)
                            dates = cftime.num2date(raw_t, src_units, calendar=src_cal)
                            reencoded = cftime.date2num(dates, ref_time_units, calendar=ref_time_cal)
                            dst_var[offset : offset + clen] = reencoded
                            advance(max(1, clen))
                            continue

                    if src_var.dimensions[0] == concat_dim:
                        _copy_var_chunked(src_var, dst_var, offset, cancel_event, advance)
                    else:
                        ax = src_var.dimensions.index(concat_dim)
                        slc = [slice(None)] * src_var.ndim
                        slc[ax] = slice(offset, offset + clen)
                        dst_var[tuple(slc)] = src_var[:]
                        advance(max(1, src_var.shape[0] if src_var.ndim > 0 else 1))

            offset += clen

def _exec_hybrid(
    file_paths, tmp_output, selected_vars, concat_dim,
    sort_by_coord, unlimited_concat, conflict_policy,
    nc_format, use_zlib, complevel, copy_global_attrs,
    cancel_event, log, set_progress,
):
    groups = {}
    for p in file_paths:
        with nc.Dataset(p, "r") as ds:
            sig = tuple(sorted(v for v in ds.variables if v not in ds.dimensions and v in selected_vars))
        groups.setdefault(sig, []).append(p)

    log(f"Hybrid mode: detected {len(groups)} variable group(s).")
    temp_merged = []
    try:
        for g_idx, (sig, g_paths) in enumerate(groups.items()):
            if len(g_paths) == 1:
                temp_merged.append(g_paths[0])
            else:
                g_tmp = f"{tmp_output}.grp{g_idx}.nc"
                temp_merged.append(g_tmp)
                _exec_concat_dim(
                    g_paths, g_tmp, set(sig), concat_dim,
                    sort_by_coord, unlimited_concat, nc_format, use_zlib,
                    complevel, copy_global_attrs and (g_idx == 0),
                    cancel_event, log, set_progress,
                )
        _exec_merge_vars(
            temp_merged, tmp_output, selected_vars, conflict_policy,
            nc_format, use_zlib, complevel, copy_global_attrs,
            cancel_event, log, set_progress,
        )
    finally:
        for p in temp_merged:
            if p.startswith(tmp_output + ".grp") and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

class SPartAJoinVarsApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION} — NetCDF File Joiner")
        self.geometry("1020x780")
        self.minsize(880, 660)

        self.file_infos = []
        self.var_check_vars = {}

        self.mode_var = tk.StringVar(value=JOIN_MODES[0][0])
        self.concat_dim_var = tk.StringVar(value="time")
        self.sort_coord_var = tk.BooleanVar(value=True)
        self.unlimited_var = tk.BooleanVar(value=False)
        self.conflict_var = tk.StringVar(value=CONFLICT_POLICIES[0][0])

        self.output_path_var = tk.StringVar()
        self.nc_format_var = tk.StringVar(value=NC_FORMATS[0])
        self.zlib_var = tk.BooleanVar(value=True)
        self.complevel_var = tk.IntVar(value=4)
        self.copy_attrs_var = tk.BooleanVar(value=True)

        self.progress_pct_var = tk.StringVar(value="0%")
        self.summary_var = tk.StringVar(value="No files loaded.")

        self.msg_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.is_running = False

        self._build_ui()
        self._on_mode_changed()
        self._poll_queue()

    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        main = ttk.Frame(self, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        lf_files = ttk.LabelFrame(main, text="1. Input NetCDF Files", padding=10)
        lf_files.pack(fill=tk.BOTH, expand=False, pady=(0, 8))

        btn_row = ttk.Frame(lf_files)
        btn_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(btn_row, text="Add Files...", command=self._add_files).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="Add Folder...", command=self._add_folder).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Button(btn_row, text="Move Up", command=lambda: self._move_selected(-1)).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="Move Down", command=lambda: self._move_selected(1)).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Button(btn_row, text="Remove Selected", command=self._remove_selected).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="Clear List", command=self._clear_files).pack(side=tk.LEFT)
        ttk.Label(btn_row, textvariable=self.summary_var, foreground="#1E3A5F").pack(side=tk.RIGHT)

        tree_frame = ttk.Frame(lf_files)
        tree_frame.pack(fill=tk.X)
        cols = ("file", "size", "dimensions", "variables", "time")
        self.tree_files = ttk.Treeview(tree_frame, columns=cols, show="headings", height=5, selectmode="extended")
        self.tree_files.heading("file", text="File")
        self.tree_files.heading("size", text="Size")
        self.tree_files.heading("dimensions", text="Dimensions")
        self.tree_files.heading("variables", text="Data Variables")
        self.tree_files.heading("time", text="Time Range")
        self.tree_files.column("file", width=210, anchor=tk.W)
        self.tree_files.column("size", width=75, anchor=tk.E)
        self.tree_files.column("dimensions", width=220, anchor=tk.W)
        self.tree_files.column("variables", width=220, anchor=tk.W)
        self.tree_files.column("time", width=220, anchor=tk.W)
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree_files.yview)
        self.tree_files.configure(yscrollcommand=vsb.set)
        self.tree_files.pack(side=tk.LEFT, fill=tk.X, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        lf_vars = ttk.LabelFrame(main, text="2. Data Variables to Include (coordinates are preserved automatically)", padding=10)
        lf_vars.pack(fill=tk.X, pady=(0, 8))

        vhdr = ttk.Frame(lf_vars)
        vhdr.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(vhdr, text="Variables detected across files:").pack(side=tk.LEFT)
        ttk.Button(vhdr, text="Select All", command=lambda: self._toggle_all_vars(True)).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(vhdr, text="Deselect All", command=lambda: self._toggle_all_vars(False)).pack(side=tk.RIGHT)

        self.vars_canvas = tk.Canvas(lf_vars, height=78, highlightthickness=0)
        self.vars_inner = ttk.Frame(self.vars_canvas)
        self.vars_inner_id = self.vars_canvas.create_window((0, 0), window=self.vars_inner, anchor="nw")
        vars_sb = ttk.Scrollbar(lf_vars, orient=tk.VERTICAL, command=self.vars_canvas.yview)
        self.vars_canvas.configure(yscrollcommand=vars_sb.set)
        self.vars_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)
        vars_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.vars_inner.bind("<Configure>", lambda _e: self.vars_canvas.configure(scrollregion=self.vars_canvas.bbox("all")))
        ttk.Label(self.vars_inner, text="Add NetCDF files to inspect variables.", foreground="#666666").pack(anchor=tk.W)

        lf_mode = ttk.LabelFrame(main, text="3. Join Mode & Options", padding=10)
        lf_mode.pack(fill=tk.X, pady=(0, 8))

        r_mode = ttk.Frame(lf_mode)
        r_mode.pack(fill=tk.X, pady=(0, 6))
        for val, label in JOIN_MODES:
            ttk.Radiobutton(
                r_mode, text=label, value=val, variable=self.mode_var, command=self._on_mode_changed
            ).pack(side=tk.LEFT, padx=(0, 14))

        r_opts = ttk.Frame(lf_mode)
        r_opts.pack(fill=tk.X)

        ttk.Label(r_opts, text="Concatenation dimension:").pack(side=tk.LEFT)
        self.cmb_concat_dim = ttk.Combobox(r_opts, textvariable=self.concat_dim_var, width=16)
        self.cmb_concat_dim.pack(side=tk.LEFT, padx=(6, 12))

        self.chk_sort = ttk.Checkbutton(r_opts, text="Sort by coordinate", variable=self.sort_coord_var)
        self.chk_sort.pack(side=tk.LEFT, padx=(0, 12))

        self.chk_unlim = ttk.Checkbutton(r_opts, text="UNLIMITED dimension", variable=self.unlimited_var)
        self.chk_unlim.pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(r_opts, text="On duplicate variable:").pack(side=tk.LEFT)
        self.cmb_conflict = ttk.Combobox(
            r_opts,
            state="readonly",
            width=28,
            values=[lbl for _, lbl in CONFLICT_POLICIES],
        )
        self.cmb_conflict.current(0)
        self.cmb_conflict.bind("<<ComboboxSelected>>", self._on_conflict_selected)
        self.cmb_conflict.pack(side=tk.LEFT, padx=(6, 0))

        lf_out = ttk.LabelFrame(main, text="4. Output NetCDF File", padding=10)
        lf_out.pack(fill=tk.X, pady=(0, 8))

        r_out1 = ttk.Frame(lf_out)
        r_out1.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(r_out1, text="Output file:").pack(side=tk.LEFT)
        ttk.Entry(r_out1, textvariable=self.output_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        ttk.Button(r_out1, text="Save As...", command=self._browse_output).pack(side=tk.RIGHT)

        r_out2 = ttk.Frame(lf_out)
        r_out2.pack(fill=tk.X)
        ttk.Label(r_out2, text="Format:").pack(side=tk.LEFT)
        ttk.Combobox(r_out2, textvariable=self.nc_format_var, values=NC_FORMATS, state="readonly", width=22).pack(
            side=tk.LEFT, padx=(6, 14)
        )
        ttk.Checkbutton(r_out2, text="zlib compression", variable=self.zlib_var).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(r_out2, text="Level:").pack(side=tk.LEFT)
        ttk.Spinbox(r_out2, from_=1, to=9, textvariable=self.complevel_var, width=4).pack(side=tk.LEFT, padx=(4, 16))
        ttk.Checkbutton(r_out2, text="Preserve global attributes", variable=self.copy_attrs_var).pack(side=tk.LEFT)

        run_row = ttk.Frame(main)
        run_row.pack(fill=tk.X, pady=(0, 6))
        self.btn_run = ttk.Button(run_row, text="Join NetCDF Files", command=self._start_join)
        self.btn_run.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_stop = ttk.Button(run_row, text="Stop", command=self._stop_join, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 10))
        self.progress = ttk.Progressbar(run_row, orient=tk.HORIZONTAL, mode="determinate")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Label(run_row, textvariable=self.progress_pct_var, width=10, anchor=tk.E).pack(side=tk.RIGHT)

        self.log_text = tk.Text(main, height=10, wrap=tk.WORD, state=tk.DISABLED, font=("TkFixedFont", 10))
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _log(self, msg):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _on_conflict_selected(self, _evt=None):
        idx = self.cmb_conflict.current()
        if 0 <= idx < len(CONFLICT_POLICIES):
            self.conflict_var.set(CONFLICT_POLICIES[idx][0])

    def _on_mode_changed(self):
        mode = self.mode_var.get()
        is_concat = mode in ("concat_dim", "auto")
        is_merge = mode in ("merge_vars", "auto")
        self.cmb_concat_dim.configure(state="normal" if is_concat else tk.DISABLED)
        self.chk_sort.configure(state=tk.NORMAL if is_concat else tk.DISABLED)
        self.chk_unlim.configure(state=tk.NORMAL if is_concat else tk.DISABLED)
        self.cmb_conflict.configure(state="readonly" if is_merge else tk.DISABLED)

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select NetCDF Files",
            filetypes=[("NetCDF Files", "*.nc *.nc4 *.cdf"), ("All Files", "*.*")],
        )
        if paths:
            self._load_paths(paths)

    def _add_folder(self):
        folder = filedialog.askdirectory(title="Select Folder Containing NetCDF Files")
        if not folder:
            return
        paths = sorted(
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith((".nc", ".nc4", ".cdf"))
        )
        if not paths:
            messagebox.showinfo(APP_NAME, "No .nc / .nc4 / .cdf files were found in that folder.")
            return
        self._load_paths(paths)

    def _load_paths(self, paths):
        existing = {info["path"] for info in self.file_infos}
        added = 0
        for p in paths:
            ap = os.path.abspath(p)
            if ap in existing:
                continue
            try:
                info = inspect_netcdf(ap)
                self.file_infos.append(info)
                existing.add(ap)
                added += 1
            except Exception as exc:
                self._log(f"Error inspecting '{os.path.basename(ap)}': {exc}")

        if added:
            self._refresh_files_ui()
            if not self.output_path_var.get().strip() and self.file_infos:
                first_dir = os.path.dirname(self.file_infos[0]["path"])
                self.output_path_var.set(os.path.join(first_dir, "sparta_joined.nc"))
            self._log(f"Added {added} NetCDF file(s).")

    def _refresh_files_ui(self):
        for item in self.tree_files.get_children():
            self.tree_files.delete(item)

        all_dims = []
        all_data_vars = []
        seen_vars = set()

        for info in self.file_infos:
            dims_str = ", ".join(f"{k}:{v[0]}" for k, v in info["dimensions"].items())
            data_vars = [v["name"] for v in info["variables"] if not v["is_coord"]]
            vars_str = ", ".join(data_vars) if data_vars else "(coordinates only)"
            self.tree_files.insert(
                "",
                tk.END,
                values=(
                    info["filename"],
                    f"{info['size_mb']:.2f} MB",
                    dims_str,
                    vars_str,
                    info["time_range"] or "—",
                ),
            )
            for d in info["dimensions"]:
                if d not in all_dims:
                    all_dims.append(d)
            for v in data_vars:
                if v not in seen_vars:
                    seen_vars.add(v)
                    all_data_vars.append(v)

        total_mb = sum(i["size_mb"] for i in self.file_infos)
        self.summary_var.set(
            f"{len(self.file_infos)} file(s) | {total_mb:.2f} MB | {len(all_data_vars)} variable(s)"
            if self.file_infos
            else "No files loaded."
        )

        self.cmb_concat_dim["values"] = all_dims
        detected_t = next((i["time_var"] for i in self.file_infos if i["time_var"]), "")
        if detected_t and detected_t in all_dims:
            self.concat_dim_var.set(detected_t)
        elif all_dims and self.concat_dim_var.get() not in all_dims:
            self.concat_dim_var.set(all_dims[0])

        prev_states = {k: v.get() for k, v in self.var_check_vars.items()}
        self.var_check_vars.clear()
        for child in self.vars_inner.winfo_children():
            child.destroy()

        if not all_data_vars:
            ttk.Label(self.vars_inner, text="No data variables detected.", foreground="#666666").pack(anchor=tk.W)
            return

        cols = 5
        for idx, vname in enumerate(all_data_vars):
            bvar = tk.BooleanVar(value=prev_states.get(vname, True))
            self.var_check_vars[vname] = bvar
            ttk.Checkbutton(self.vars_inner, text=vname, variable=bvar).grid(
                row=idx // cols, column=idx % cols, sticky=tk.W, padx=8, pady=2
            )

    def _toggle_all_vars(self, state):
        for bv in self.var_check_vars.values():
            bv.set(state)

    def _move_selected(self, delta):
        sel = self.tree_files.selection()
        if not sel:
            return
        indices = [self.tree_files.index(item) for item in sel]
        if delta < 0 and min(indices) == 0:
            return
        if delta > 0 and max(indices) == len(self.file_infos) - 1:
            return
        order = sorted(indices, reverse=(delta > 0))
        for idx in order:
            self.file_infos[idx], self.file_infos[idx + delta] = self.file_infos[idx + delta], self.file_infos[idx]
        self._refresh_files_ui()
        children = self.tree_files.get_children()
        for idx in indices:
            self.tree_files.selection_add(children[idx + delta])

    def _remove_selected(self):
        sel = self.tree_files.selection()
        if not sel:
            return
        indices = sorted((self.tree_files.index(item) for item in sel), reverse=True)
        for idx in indices:
            self.file_infos.pop(idx)
        self._refresh_files_ui()

    def _clear_files(self):
        self.file_infos.clear()
        self._refresh_files_ui()

    def _browse_output(self):
        initial = self.output_path_var.get().strip()
        init_dir = os.path.dirname(initial) if initial else os.getcwd()
        init_file = os.path.basename(initial) if initial else "sparta_joined.nc"
        path = filedialog.asksaveasfilename(
            title="Save Joined NetCDF As",
            initialdir=init_dir,
            initialfile=init_file,
            defaultextension=".nc",
            filetypes=[("NetCDF Files", "*.nc *.nc4"), ("All Files", "*.*")],
        )
        if path:
            self.output_path_var.set(path)

    def _start_join(self):
        if self.is_running:
            return
        if len(self.file_infos) < 2:
            messagebox.showwarning(APP_NAME, "Please add at least 2 NetCDF files to join.")
            return

        selected_vars = {k for k, bv in self.var_check_vars.items() if bv.get()}
        if not selected_vars:
            messagebox.showwarning(APP_NAME, "Please select at least one data variable.")
            return

        output_path = self.output_path_var.get().strip()
        if not output_path:
            messagebox.showwarning(APP_NAME, "Please specify an output NetCDF file path.")
            return

        if os.path.abspath(output_path) in {i["path"] for i in self.file_infos}:
            messagebox.showerror(APP_NAME, "The output file cannot overwrite one of the input files.")
            return

        if os.path.exists(output_path):
            if not messagebox.askyesno(APP_NAME, f"File '{output_path}' already exists.\nDo you want to overwrite it?"):
                return

        self.is_running = True
        self.cancel_event.clear()
        self.btn_run.configure(state=tk.DISABLED)
        self.btn_stop.configure(state=tk.NORMAL)
        self.progress.configure(value=0, maximum=100)
        self.progress_pct_var.set("0%")
        self._log("-" * 60)
        self._log(f"Starting join ({self.mode_var.get()}) of {len(self.file_infos)} files...")

        args = (
            [i["path"] for i in self.file_infos],
            output_path,
            self.mode_var.get(),
            selected_vars,
            self.concat_dim_var.get().strip(),
            self.sort_coord_var.get(),
            self.unlimited_var.get(),
            self.conflict_var.get(),
            self.nc_format_var.get(),
            self.zlib_var.get(),
            self.complevel_var.get(),
            self.copy_attrs_var.get(),
            self.cancel_event,
            self.msg_queue,
        )
        threading.Thread(target=run_join_job, args=args, daemon=True).start()

    def _stop_join(self):
        if self.is_running:
            self.cancel_event.set()
            self.btn_stop.configure(state=tk.DISABLED)
            self._log("Cancellation requested...")

    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._log(msg[1])
                elif kind == "progress":
                    _, done, total = msg
                    pct = min(100.0, (done / max(1, total)) * 100.0)
                    self.progress.configure(maximum=100, value=pct)
                    self.progress_pct_var.set(f"{pct:.0f}%")
                elif kind == "done":
                    self.progress.configure(value=100)
                    self.progress_pct_var.set("100%")
                    self._finish_run()
                    messagebox.showinfo(APP_NAME, f"Join completed:\n{msg[1]}")
                elif kind == "cancelled":
                    self._log(msg[1])
                    self._finish_run()
                elif kind == "error":
                    self._log(f"ERROR: {msg[1]}")
                    self._finish_run()
                    messagebox.showerror(APP_NAME, f"Error while joining files:\n{msg[1]}")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _finish_run(self):
        self.is_running = False
        self.btn_run.configure(state=tk.NORMAL)
        self.btn_stop.configure(state=tk.DISABLED)

if __name__ == "__main__":
    app = SPartAJoinVarsApp()
    app.mainloop()
