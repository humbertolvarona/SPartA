import ctypes
import ctypes.util
import glob
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import netCDF4 as nc
import numpy as np
from scipy.interpolate import PchipInterpolator, RBFInterpolator, RegularGridInterpolator, griddata
from scipy.spatial import cKDTree

REGRID_METHODS = [
    "Bilinear (linear)",
    "Nearest Neighbor (nearest)",
    "Bicubic (cubic)",
    "PCHIP Monotone (pchip, no overshoot)",
    "Quintic Spline (quintic)",
    "Conservative Area-Mean (cos-lat weighted)",
    "Cressman Objective Analysis (metocean)",
    "Gaussian / Barnes Analysis (metocean)",
    "RBF Thin-Plate Spline (rbf-tps)",
    "IDW (k=4 Inverse Distance)",
    "IDW (k=8 Inverse Distance)",
]

LON_CANDIDATES = ("lon", "longitude", "nav_lon", "x", "lon_u", "lon_v", "xt_ocean", "xu_ocean")
LAT_CANDIDATES = ("lat", "latitude", "nav_lat", "y", "lat_u", "lat_v", "yt_ocean", "yu_ocean")

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

def detect_lon_lat_vars(ds):
    vars_lower = {k.lower(): k for k in ds.variables.keys()}
    lon_var = next((vars_lower[c] for c in LON_CANDIDATES if c in vars_lower), "")
    lat_var = next((vars_lower[c] for c in LAT_CANDIDATES if c in vars_lower), "")
    if not lon_var:
        for k, v in ds.variables.items():
            std = str(getattr(v, "standard_name", "")).lower()
            units = str(getattr(v, "units", "")).lower()
            if "longitude" in std or "degrees_east" in units:
                lon_var = k
                break
    if not lat_var:
        for k, v in ds.variables.items():
            std = str(getattr(v, "standard_name", "")).lower()
            units = str(getattr(v, "units", "")).lower()
            if "latitude" in std or "degrees_north" in units:
                lat_var = k
                break
    return lon_var, lat_var

def normalize_lon(lon_arr, target_range="auto", ref_lon=None):
    arr = np.array(lon_arr, dtype=float)
    if target_range == "[-180, 180]" or (target_range == "auto" and ref_lon is not None and np.nanmin(ref_lon) < 0):
        arr = ((arr + 180.0) % 360.0) - 180.0
    elif target_range == "[0, 360]" or (target_range == "auto" and ref_lon is not None and np.nanmax(ref_lon) > 180.0):
        arr = arr % 360.0
    return arr

def build_2d_lon_lat(lon_raw, lat_raw):
    lon_arr = np.array(lon_raw, dtype=float)
    lat_arr = np.array(lat_raw, dtype=float)
    if lon_arr.ndim == 1 and lat_arr.ndim == 1:
        lon2d, lat2d = np.meshgrid(lon_arr, lat_arr)
        return lon2d, lat2d, True, lon_arr, lat_arr
    elif lon_arr.ndim == 2 and lat_arr.ndim == 2:
        return lon_arr, lat_arr, False, None, None
    raise ValueError(f"Unsupported coordinate dimensions: lon={lon_arr.shape}, lat={lat_arr.shape}")

def regrid_2d_slice(
    src_data,
    src_lon,
    src_lat,
    dst_lon2d,
    dst_lat2d,
    method="Bilinear (linear)",
    fill_coastal_nearest=False,
):
    arr = np.array(src_data, dtype=float)
    arr[np.abs(arr) > 1e15] = np.nan

    dst_pts = np.column_stack([dst_lon2d.ravel(), dst_lat2d.ravel()])
    out_shape = dst_lon2d.shape

    is_rect = (src_lon.ndim == 1 and src_lat.ndim == 1)
    has_nan = bool(np.any(np.isnan(arr)))

    if is_rect and (
        method in ("Bilinear (linear)", "Nearest Neighbor (nearest)")
        or (method in ("Bicubic (cubic)", "Quintic Spline (quintic)", "PCHIP Monotone (pchip, no overshoot)") and not has_nan)
    ):
        lon_1d = np.array(src_lon, dtype=float)
        lat_1d = np.array(src_lat, dtype=float)

        if lon_1d[0] > lon_1d[-1]:
            lon_1d = lon_1d[::-1]
            arr = arr[:, ::-1]
        if lat_1d[0] > lat_1d[-1]:
            lat_1d = lat_1d[::-1]
            arr = arr[::-1, :]

        lon_order = np.argsort(lon_1d)
        lat_order = np.argsort(lat_1d)
        lon_1d = lon_1d[lon_order]
        lat_1d = lat_1d[lat_order]
        arr = arr[np.ix_(lat_order, lon_order)]

        if method == "PCHIP Monotone (pchip, no overshoot)":

            tmp = np.full((len(lat_1d), dst_lon2d.shape[1]), np.nan, dtype=float)
            dst_lon_1d = dst_lon2d[0, :] if np.allclose(dst_lon2d, dst_lon2d[0:1, :]) else None
            if dst_lon_1d is not None and not has_nan:
                p_lon = PchipInterpolator(lon_1d, arr, axis=1, extrapolate=False)
                tmp = p_lon(dst_lon_1d)
                res = np.full(out_shape, np.nan, dtype=float)
                for j in range(out_shape[1]):
                    p_lat = PchipInterpolator(lat_1d, tmp[:, j], extrapolate=False)
                    res[:, j] = p_lat(dst_lat2d[:, j])
            else:

                interp = RegularGridInterpolator((lat_1d, lon_1d), arr, method="linear", bounds_error=False, fill_value=np.nan)
                res = interp(np.column_stack([dst_lat2d.ravel(), dst_lon2d.ravel()])).reshape(out_shape)
        else:
            rgi_method = {
                "Bilinear (linear)": "linear",
                "Nearest Neighbor (nearest)": "nearest",
                "Bicubic (cubic)": "cubic",
                "Quintic Spline (quintic)": "quintic",
            }[method]

            interp = RegularGridInterpolator(
                (lat_1d, lon_1d),
                arr,
                method=rgi_method,
                bounds_error=False,
                fill_value=np.nan,
            )
            res = interp(np.column_stack([dst_lat2d.ravel(), dst_lon2d.ravel()])).reshape(out_shape)

    elif method == "Conservative Area-Mean (cos-lat weighted)":
        src_lon2d, src_lat2d, _, _, _ = build_2d_lon_lat(src_lon, src_lat)
        valid = ~np.isnan(arr)
        if not np.any(valid):
            return np.full(out_shape, np.nan, dtype=float)

        dst_tree = cKDTree(dst_pts)
        src_pts_v = np.column_stack([src_lon2d[valid], src_lat2d[valid]])
        src_vals_v = arr[valid]
        src_weights_v = np.maximum(1e-6, np.cos(np.deg2rad(src_lat2d[valid])))

        _, target_cell = dst_tree.query(src_pts_v)
        n_dst = len(dst_pts)
        num = np.bincount(target_cell, weights=src_vals_v * src_weights_v, minlength=n_dst)
        den = np.bincount(target_cell, weights=src_weights_v, minlength=n_dst)
        with np.errstate(divide="ignore", invalid="ignore"):
            res = np.where(den > 0, num / den, np.nan).reshape(out_shape)

        if np.any(np.isnan(res)):
            gd = griddata(src_pts_v, src_vals_v, dst_pts, method="linear", fill_value=np.nan).reshape(out_shape)
            miss = np.isnan(res)
            res[miss] = gd[miss]

    elif method in ("Cressman Objective Analysis (metocean)", "Gaussian / Barnes Analysis (metocean)"):
        src_lon2d, src_lat2d, _, _, _ = build_2d_lon_lat(src_lon, src_lat)
        valid = ~np.isnan(arr)
        if not np.any(valid):
            return np.full(out_shape, np.nan, dtype=float)
        src_pts_v = np.column_stack([src_lon2d[valid], src_lat2d[valid]])
        src_vals_v = arr[valid]
        tree = cKDTree(src_pts_v)
        k_eff = min(12, len(src_vals_v))
        dists, idxs = tree.query(dst_pts, k=k_eff)
        if k_eff == 1:
            dists = dists[:, None]
            idxs = idxs[:, None]

        r_inf = np.maximum(1e-6, np.max(dists, axis=1, keepdims=True) * 1.15)
        if method.startswith("Cressman"):
            w = np.maximum(0.0, (r_inf ** 2 - dists ** 2) / (r_inf ** 2 + dists ** 2))
        else:

            gamma = 0.5 * (r_inf ** 2)
            w = np.exp(-(dists ** 2) / np.maximum(1e-12, gamma))
        with np.errstate(divide="ignore", invalid="ignore"):
            res = (np.sum(w * src_vals_v[idxs], axis=1) / np.sum(w, axis=1)).reshape(out_shape)

    elif method == "RBF Thin-Plate Spline (rbf-tps)":
        src_lon2d, src_lat2d, _, _, _ = build_2d_lon_lat(src_lon, src_lat)
        valid = ~np.isnan(arr)
        if not np.any(valid):
            return np.full(out_shape, np.nan, dtype=float)
        src_pts_v = np.column_stack([src_lon2d[valid], src_lat2d[valid]])
        src_vals_v = arr[valid]

        if len(src_vals_v) > 3000:
            step = max(1, len(src_vals_v) // 3000)
            src_pts_v = src_pts_v[::step]
            src_vals_v = src_vals_v[::step]
        rbf = RBFInterpolator(src_pts_v, src_vals_v, kernel="thin_plate_spline", smoothing=1e-4)
        res = rbf(dst_pts).reshape(out_shape)

    elif method.startswith("IDW"):
        k = 4 if "k=4" in method else 8
        src_lon2d, src_lat2d, _, _, _ = build_2d_lon_lat(src_lon, src_lat)
        valid = ~np.isnan(arr)
        if not np.any(valid):
            return np.full(out_shape, np.nan, dtype=float)
        src_pts = np.column_stack([src_lon2d[valid], src_lat2d[valid]])
        src_vals = arr[valid]
        tree = cKDTree(src_pts)
        k_eff = min(k, len(src_vals))
        dists, idxs = tree.query(dst_pts, k=k_eff)
        if k_eff == 1:
            dists = dists[:, None]
            idxs = idxs[:, None]
        with np.errstate(divide="ignore", invalid="ignore"):
            weights = np.where(dists < 1e-12, 1e12, 1.0 / (dists ** 2))
            num = np.sum(weights * src_vals[idxs], axis=1)
            den = np.sum(weights, axis=1)
            res = (num / den).reshape(out_shape)

    else:

        src_lon2d, src_lat2d, _, _, _ = build_2d_lon_lat(src_lon, src_lat)
        valid = ~np.isnan(arr)
        if not np.any(valid):
            return np.full(out_shape, np.nan, dtype=float)
        gd_method = {
            "Bilinear (linear)": "linear",
            "Nearest Neighbor (nearest)": "nearest",
            "Bicubic (cubic)": "cubic",
        }.get(method, "linear")
        res = griddata(
            np.column_stack([src_lon2d[valid], src_lat2d[valid]]),
            arr[valid],
            dst_pts,
            method=gd_method,
            fill_value=np.nan,
        ).reshape(out_shape)

    if fill_coastal_nearest and np.any(np.isnan(res)):
        src_lon2d, src_lat2d, _, _, _ = build_2d_lon_lat(src_lon, src_lat)
        valid = ~np.isnan(arr)
        if np.any(valid):
            tree = cKDTree(np.column_stack([src_lon2d[valid], src_lat2d[valid]]))
            nan_mask = np.isnan(res)
            _, nn_idx = tree.query(np.column_stack([dst_lon2d[nan_mask], dst_lat2d[nan_mask]]))
            res[nan_mask] = arr[valid][nn_idx]

    return res

def count_total_slices(file_paths):
    total = 0
    for p in file_paths:
        try:
            with nc.Dataset(p, "r") as ds:
                lon_n, lat_n = detect_lon_lat_vars(ds)
                if not lon_n or not lat_n:
                    total += 1
                    continue
                sp_dims = set(ds.variables[lon_n].dimensions) | set(ds.variables[lat_n].dimensions)
                for vname, var in ds.variables.items():
                    if vname in (lon_n, lat_n):
                        continue
                    vdims = var.dimensions
                    if len(vdims) >= 2 and any(d in sp_dims for d in vdims):
                        if len(vdims) == 2:
                            total += 1
                        elif len(vdims) == 3:
                            total += max(1, var.shape[0])
                        elif len(vdims) == 4:
                            total += max(1, var.shape[0] * var.shape[1])
        except Exception:
            total += 1
    return max(1, total)

def regrid_netcdf_file(
    ref_path,
    ref_lon_name,
    ref_lat_name,
    src_path,
    out_path,
    method="Bilinear (linear)",
    lon_norm_mode="auto",
    fill_coastal_nearest=False,
    progress_cb=None,
    cancel_event=None,
    slice_cb=None,
):
    with nc.Dataset(ref_path, "r") as ds_ref:
        ref_lon_var = ds_ref.variables[ref_lon_name]
        ref_lat_var = ds_ref.variables[ref_lat_name]
        ref_lon_raw = np.array(ref_lon_var[:], dtype=float)
        ref_lat_raw = np.array(ref_lat_var[:], dtype=float)
        dst_lon2d, dst_lat2d, dst_is_rect, dst_lon1d, dst_lat1d = build_2d_lon_lat(ref_lon_raw, ref_lat_raw)
        ref_lon_attrs = {a: ref_lon_var.getncattr(a) for a in ref_lon_var.ncattrs() if a != "_FillValue"}
        ref_lat_attrs = {a: ref_lat_var.getncattr(a) for a in ref_lat_var.ncattrs() if a != "_FillValue"}
        ref_lon_dims = ref_lon_var.dimensions
        ref_lat_dims = ref_lat_var.dimensions

    with nc.Dataset(src_path, "r") as ds_src:
        src_lon_name, src_lat_name = detect_lon_lat_vars(ds_src)
        if not src_lon_name or not src_lat_name:
            raise ValueError(f"Could not detect lon/lat variables in {os.path.basename(src_path)}")

        src_lon_raw = normalize_lon(ds_src.variables[src_lon_name][:], target_range=lon_norm_mode, ref_lon=dst_lon2d)
        src_lat_raw = np.array(ds_src.variables[src_lat_name][:], dtype=float)

        src_lon_dims_set = set(ds_src.variables[src_lon_name].dimensions)
        src_lat_dims_set = set(ds_src.variables[src_lat_name].dimensions)
        spatial_dim_names = src_lon_dims_set | src_lat_dims_set

        if len(spatial_dim_names) != 2:
            raise ValueError(f"Expected 2 spatial dimensions in {os.path.basename(src_path)}, got {spatial_dim_names}")

        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with nc.Dataset(out_path, "w", format="NETCDF4") as ds_out:

            for attr in ds_src.ncattrs():
                ds_out.setncattr(attr, ds_src.getncattr(attr))
            ds_out.setncattr("regridded_by", f"SPartA-regrid ({method})")
            ds_out.setncattr("reference_grid_file", os.path.basename(ref_path))

            if dst_is_rect:
                lat_dim_name = ref_lat_dims[0]
                lon_dim_name = ref_lon_dims[0]
                ds_out.createDimension(lat_dim_name, len(dst_lat1d))
                ds_out.createDimension(lon_dim_name, len(dst_lon1d))
                v_lat = ds_out.createVariable(lat_dim_name, "f8", (lat_dim_name,))
                v_lat[:] = dst_lat1d
                for k, v in ref_lat_attrs.items():
                    v_lat.setncattr(k, v)
                v_lon = ds_out.createVariable(lon_dim_name, "f8", (lon_dim_name,))
                v_lon[:] = dst_lon1d
                for k, v in ref_lon_attrs.items():
                    v_lon.setncattr(k, v)
            else:
                lat_dim_name, lon_dim_name = ref_lat_dims[0], ref_lat_dims[1]
                ds_out.createDimension(lat_dim_name, dst_lat2d.shape[0])
                ds_out.createDimension(lon_dim_name, dst_lon2d.shape[1])
                v_lat = ds_out.createVariable(ref_lat_name, "f8", (lat_dim_name, lon_dim_name))
                v_lat[:, :] = dst_lat2d
                for k, v in ref_lat_attrs.items():
                    v_lat.setncattr(k, v)
                v_lon = ds_out.createVariable(ref_lon_name, "f8", (lat_dim_name, lon_dim_name))
                v_lon[:, :] = dst_lon2d
                for k, v in ref_lon_attrs.items():
                    v_lon.setncattr(k, v)

            for dname, dim in ds_src.dimensions.items():
                if dname not in spatial_dim_names:
                    ds_out.createDimension(dname, None if dim.isunlimited() else len(dim))

            var_items = list(ds_src.variables.items())
            for vname, var in var_items:
                if vname in (src_lon_name, src_lat_name):
                    continue

                vdims = var.dimensions
                has_spatial = any(d in spatial_dim_names for d in vdims)

                if not has_spatial:
                    fillv = var.getncattr("_FillValue") if "_FillValue" in var.ncattrs() else None
                    v_out = ds_out.createVariable(vname, var.dtype, vdims, fill_value=fillv)
                    for a in var.ncattrs():
                        if a != "_FillValue":
                            v_out.setncattr(a, var.getncattr(a))
                    v_out[:] = var[:]
                    continue

                if len(vdims) < 2:
                    continue
                new_dims = list(vdims[:-2]) + [lat_dim_name, lon_dim_name]
                v_out = ds_out.createVariable(vname, "f4", tuple(new_dims), zlib=True, complevel=2, fill_value=np.float32(np.nan))
                for a in var.ncattrs():
                    if a != "_FillValue":
                        v_out.setncattr(a, var.getncattr(a))

                if len(vdims) == 2:
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError("Stopped by user.")
                    raw_2d = var[:, :]
                    if np.ma.isMaskedArray(raw_2d):
                        raw_2d = raw_2d.filled(np.nan)
                    out_2d = regrid_2d_slice(raw_2d, src_lon_raw, src_lat_raw, dst_lon2d, dst_lat2d, method, fill_coastal_nearest)
                    v_out[:, :] = out_2d.astype(np.float32)
                    if slice_cb:
                        slice_cb()
                elif len(vdims) == 3:
                    nt = var.shape[0]
                    for t in range(nt):
                        if cancel_event is not None and cancel_event.is_set():
                            raise InterruptedError("Stopped by user.")
                        raw_2d = var[t, :, :]
                        if np.ma.isMaskedArray(raw_2d):
                            raw_2d = raw_2d.filled(np.nan)
                        out_2d = regrid_2d_slice(raw_2d, src_lon_raw, src_lat_raw, dst_lon2d, dst_lat2d, method, fill_coastal_nearest)
                        v_out[t, :, :] = out_2d.astype(np.float32)
                        if slice_cb:
                            slice_cb()
                        if progress_cb and (t % 10 == 0 or t == nt - 1):
                            progress_cb(f"{os.path.basename(src_path)} [{vname}] step {t + 1}/{nt}")
                elif len(vdims) == 4:
                    nt, nz = var.shape[0], var.shape[1]
                    for t in range(nt):
                        for z in range(nz):
                            if cancel_event is not None and cancel_event.is_set():
                                raise InterruptedError("Stopped by user.")
                            raw_2d = var[t, z, :, :]
                            if np.ma.isMaskedArray(raw_2d):
                                raw_2d = raw_2d.filled(np.nan)
                            out_2d = regrid_2d_slice(raw_2d, src_lon_raw, src_lat_raw, dst_lon2d, dst_lat2d, method, fill_coastal_nearest)
                            v_out[t, z, :, :] = out_2d.astype(np.float32)
                            if slice_cb:
                                slice_cb()
                        if progress_cb and (t % 10 == 0 or t == nt - 1):
                            progress_cb(f"{os.path.basename(src_path)} [{vname}] step {t + 1}/{nt}")

class SPartARegridApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SPartA-regrid v3.0 — Spatial NetCDF Regridder")
        self.geometry("1040x760")
        self.minsize(900, 640)

        self.ref_path_var = tk.StringVar()
        self.ref_lon_var = tk.StringVar()
        self.ref_lat_var = tk.StringVar()
        self.ref_info_var = tk.StringVar(value="No reference NetCDF loaded.")

        self.method_var = tk.StringVar(value=REGRID_METHODS[0])
        self.lon_norm_var = tk.StringVar(value="auto")
        self.fill_coast_var = tk.BooleanVar(value=False)
        self.out_dir_var = tk.StringVar()
        self.suffix_var = tk.StringVar(value="_regrid")

        self.target_files = []
        self.msg_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.is_running = False

        self._build_ui()
        self._poll_queue()

    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        main = ttk.Frame(self, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        lf_ref = ttk.LabelFrame(main, text="1. Reference NetCDF (Base Lon/Lat Grid)", padding=10)
        lf_ref.pack(fill=tk.X, pady=(0, 8))

        row_r1 = ttk.Frame(lf_ref)
        row_r1.pack(fill=tk.X, pady=(0, 6))
        ttk.Entry(row_r1, textvariable=self.ref_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(row_r1, text="Select Reference .nc...", command=self._browse_ref).pack(side=tk.RIGHT)

        row_r2 = ttk.Frame(lf_ref)
        row_r2.pack(fill=tk.X)
        ttk.Label(row_r2, text="Lon var:").pack(side=tk.LEFT)
        self.cmb_ref_lon = ttk.Combobox(row_r2, textvariable=self.ref_lon_var, state="readonly", width=16)
        self.cmb_ref_lon.pack(side=tk.LEFT, padx=(4, 14))
        ttk.Label(row_r2, text="Lat var:").pack(side=tk.LEFT)
        self.cmb_ref_lat = ttk.Combobox(row_r2, textvariable=self.ref_lat_var, state="readonly", width=16)
        self.cmb_ref_lat.pack(side=tk.LEFT, padx=(4, 14))
        ttk.Label(row_r2, textvariable=self.ref_info_var, foreground="#1E3A5F").pack(side=tk.LEFT)

        lf_tgt = ttk.LabelFrame(main, text="2. Target NetCDF Files to Regrid", padding=10)
        lf_tgt.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        tgt_top = ttk.Frame(lf_tgt)
        tgt_top.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(tgt_top, text="+ Add NetCDF Files...", command=self._add_targets).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(tgt_top, text="Remove Selected", command=self._remove_selected).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(tgt_top, text="Clear List", command=self._clear_targets).pack(side=tk.LEFT)

        tree_frame = ttk.Frame(lf_tgt)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=("file", "grid", "vars"), show="headings", height=6)
        self.tree.heading("file", text="File Path")
        self.tree.heading("grid", text="Source Grid")
        self.tree.heading("vars", text="Variables")
        self.tree.column("file", width=460)
        self.tree.column("grid", width=180)
        self.tree.column("vars", width=280)
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        lf_opt = ttk.LabelFrame(main, text="3. Regridding Method & Output Settings", padding=10)
        lf_opt.pack(fill=tk.X, pady=(0, 8))

        r_m = ttk.Frame(lf_opt)
        r_m.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(r_m, text="Method:").pack(side=tk.LEFT)
        ttk.Combobox(r_m, textvariable=self.method_var, values=REGRID_METHODS, state="readonly", width=28).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(r_m, text="Lon range:").pack(side=tk.LEFT)
        ttk.Combobox(r_m, textvariable=self.lon_norm_var, values=["auto", "[-180, 180]", "[0, 360]"], state="readonly", width=13).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Checkbutton(r_m, text="Fill coastal NaNs (Nearest)", variable=self.fill_coast_var).pack(side=tk.LEFT)

        r_o = ttk.Frame(lf_opt)
        r_o.pack(fill=tk.X)
        ttk.Label(r_o, text="Output folder:").pack(side=tk.LEFT)
        ttk.Entry(r_o, textvariable=self.out_dir_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        ttk.Button(r_o, text="Browse...", command=self._browse_out_dir).pack(side=tk.LEFT, padx=(0, 14))
        ttk.Label(r_o, text="Suffix:").pack(side=tk.LEFT)
        ttk.Entry(r_o, textvariable=self.suffix_var, width=12).pack(side=tk.LEFT, padx=(6, 0))

        run_row = ttk.Frame(main)
        run_row.pack(fill=tk.X, pady=(0, 6))
        self.btn_run = ttk.Button(run_row, text="Run Regridding", command=self._start_regrid)
        self.btn_run.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_stop = ttk.Button(run_row, text="Stop", command=self._stop_regrid, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 10))
        self.progress = ttk.Progressbar(run_row, orient=tk.HORIZONTAL, mode="determinate")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.progress_pct_var = tk.StringVar(value="0%")
        ttk.Label(run_row, textvariable=self.progress_pct_var, width=16, anchor=tk.E).pack(side=tk.RIGHT)

        self.log_text = tk.Text(main, height=8, wrap=tk.WORD, state=tk.DISABLED, font=("TkFixedFont", 10))
        self.log_text.pack(fill=tk.BOTH, expand=False)

    def _log(self, msg):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _browse_ref(self):
        path = filedialog.askopenfilename(
            title="Select Reference NetCDF File",
            filetypes=[("NetCDF Files", "*.nc *.nc4"), ("All Files", "*.*")],
        )
        if path:
            self.load_reference(path)

    def load_reference(self, path):
        try:
            with nc.Dataset(path, "r") as ds:
                var_names = list(ds.variables.keys())
                lon_v, lat_v = detect_lon_lat_vars(ds)
                self.cmb_ref_lon["values"] = var_names
                self.cmb_ref_lat["values"] = var_names
                if lon_v:
                    self.ref_lon_var.set(lon_v)
                if lat_v:
                    self.ref_lat_var.set(lat_v)
                if lon_v and lat_v:
                    lon_arr = ds.variables[lon_v][:]
                    lat_arr = ds.variables[lat_v][:]
                    self.ref_info_var.set(
                        f"Grid: lon={lon_arr.shape} [{float(np.nanmin(lon_arr)):.2f}, {float(np.nanmax(lon_arr)):.2f}], "
                        f"lat={lat_arr.shape} [{float(np.nanmin(lat_arr)):.2f}, {float(np.nanmax(lat_arr)):.2f}]"
                    )
            self.ref_path_var.set(path)
            if not self.out_dir_var.get():
                self.out_dir_var.set(os.path.join(os.path.dirname(path), "regridded"))
            self._log(f"Loaded reference: {path}")
        except Exception as exc:
            messagebox.showerror("Reference Error", str(exc))

    def _add_targets(self):
        paths = filedialog.askopenfilenames(
            title="Select Target NetCDF Files",
            filetypes=[("NetCDF Files", "*.nc *.nc4"), ("All Files", "*.*")],
        )
        for p in paths:
            self.add_target_file(p)

    def add_target_file(self, path):
        if path in self.target_files:
            return
        try:
            with nc.Dataset(path, "r") as ds:
                lon_v, lat_v = detect_lon_lat_vars(ds)
                grid_str = f"{ds.variables[lat_v].shape} x {ds.variables[lon_v].shape}" if (lon_v and lat_v) else "Unknown"
                vnames = ", ".join(list(ds.variables.keys())[:6])
            self.target_files.append(path)
            self.tree.insert("", tk.END, values=(path, grid_str, vnames))
        except Exception as exc:
            messagebox.showerror("Target Error", f"{path}:\n{exc}")

    def _remove_selected(self):
        for sel in self.tree.selection():
            vals = self.tree.item(sel, "values")
            if vals and vals[0] in self.target_files:
                self.target_files.remove(vals[0])
            self.tree.delete(sel)

    def _clear_targets(self):
        self.target_files.clear()
        for it in self.tree.get_children():
            self.tree.delete(it)

    def _browse_out_dir(self):
        d = filedialog.askdirectory(title="Select Output Folder")
        if d:
            self.out_dir_var.set(d)

    def _start_regrid(self):
        if self.is_running:
            return
        ref_path = self.ref_path_var.get().strip()
        if not ref_path or not os.path.isfile(ref_path):
            messagebox.showwarning("Missing Reference", "Please select a valid reference NetCDF file.")
            return
        if not self.target_files:
            messagebox.showwarning("No Targets", "Please add at least one target NetCDF file.")
            return
        lon_v, lat_v = self.ref_lon_var.get(), self.ref_lat_var.get()
        if not lon_v or not lat_v:
            messagebox.showwarning("Missing Coordinates", "Please select Lon and Lat variables for the reference file.")
            return

        out_dir = self.out_dir_var.get().strip() or os.path.join(os.path.dirname(ref_path), "regridded")
        suffix = self.suffix_var.get().strip() or "_regrid"
        method = self.method_var.get()
        lon_norm = self.lon_norm_var.get()
        fill_coast = self.fill_coast_var.get()

        targets = list(self.target_files)
        total_slices = count_total_slices(targets)
        self._total_slices = total_slices

        self.is_running = True
        self.cancel_event.clear()
        self.btn_run.configure(state=tk.DISABLED)
        self.btn_stop.configure(state=tk.NORMAL)
        self.progress.configure(maximum=total_slices, value=0)
        self.progress_pct_var.set(f"0% (0/{total_slices})")

        def _worker():
            silence_hdf5_thread()
            t0 = time.perf_counter()
            stopped = False
            done_slices = 0

            def _on_slice():
                nonlocal done_slices
                done_slices += 1
                self.msg_queue.put(("progress", done_slices))

            for idx, src_p in enumerate(targets, start=1):
                if self.cancel_event.is_set():
                    stopped = True
                    break
                base, ext = os.path.splitext(os.path.basename(src_p))
                out_p = os.path.join(out_dir, f"{base}{suffix}{ext}")
                try:
                    self.msg_queue.put(("log", f"[{idx}/{len(targets)}] Regridding {os.path.basename(src_p)} -> {out_p} ({method})..."))
                    regrid_netcdf_file(
                        ref_path, lon_v, lat_v, src_p, out_p,
                        method=method, lon_norm_mode=lon_norm, fill_coastal_nearest=fill_coast,
                        progress_cb=lambda m: self.msg_queue.put(("log", f"  {m}")),
                        cancel_event=self.cancel_event,
                        slice_cb=_on_slice,
                    )
                except InterruptedError:
                    stopped = True
                    if os.path.isfile(out_p):
                        try:
                            os.remove(out_p)
                        except OSError:
                            pass
                    self.msg_queue.put(("log", f"Stopped while processing {os.path.basename(src_p)} (partial output removed)."))
                    break
                except Exception as exc:
                    self.msg_queue.put(("log", f"ERROR in {src_p}: {exc}"))
            elapsed = time.perf_counter() - t0
            summary = f"Regridding stopped by user after {elapsed:.2f} s." if stopped else f"Completed {len(targets)} file(s) in {elapsed:.2f} s."
            self.msg_queue.put(("done", summary))

        threading.Thread(target=_worker, daemon=True).start()

    def _stop_regrid(self):
        if self.is_running and not self.cancel_event.is_set():
            self.cancel_event.set()
            self.btn_stop.configure(state=tk.DISABLED)
            self._log("Stop requested — halting after current slice...")

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    self.progress["value"] = payload
                    tot = max(1, getattr(self, "_total_slices", 1))
                    pct = min(100.0, 100.0 * payload / tot)
                    self.progress_pct_var.set(f"{pct:.0f}% ({payload}/{tot})")
                elif kind == "done":
                    self._log(payload)
                    self.is_running = False
                    self.btn_run.configure(state=tk.NORMAL)
                    self.btn_stop.configure(state=tk.DISABLED)
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)

def main():
    app = SPartARegridApp()
    app.mainloop()

if __name__ == "__main__":
    main()
