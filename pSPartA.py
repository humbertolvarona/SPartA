import csv
import json
import multiprocessing
import os
import sys
from time import perf_counter
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

import cartopy.crs as crs
import cartopy.feature as cfeature
import gsw
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
import netCDF4 as nc
import numpy as np
import psutil
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
from prettytable import PrettyTable
from scipy.interpolate import griddata
from scipy.spatial import cKDTree
from tabulate import tabulate

import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point, LineString
import geopandas as gpd
import warnings

def get_freememory():
    memory = psutil.virtual_memory()
    freememoryinbytes = memory.available
    if freememoryinbytes >= 1024 ** 3:
        totalfreememory = freememoryinbytes / (1024 ** 3)
        memoryunit = 'GB'
    elif freememoryinbytes >= 1024 ** 2:
        totalfreememory = freememoryinbytes / (1024 ** 2)
        memoryunit = 'MB'
    else:
        totalfreememory = freememoryinbytes / 1024
        memoryunit = 'KB'
    return totalfreememory, memoryunit

def get_cpu_temperature():
    try:
        temperature_info = psutil.sensors_temperatures()
        cpu_temperature = temperature_info['coretemp'][0].current
        return cpu_temperature
    except Exception as e:
        return None

def compute_deltas_in_m(deltalon, deltalat, mean_lat=0.0):
    delta_lon_m = 6371000 * deltalon * (np.pi / 180.0) * np.cos(np.radians(mean_lat))
    delta_lat_m = 6371000 * deltalat * (np.pi / 180.0)
    return delta_lon_m, delta_lat_m

def load_hydrodynamic_data(netcdf_file, parameterlist):
    dataset = nc.Dataset(netcdf_file)
    lon = np.ma.filled(dataset.variables[parameterlist[0]][:], np.nan).astype(np.float64, copy=False)
    lat = np.ma.filled(dataset.variables[parameterlist[1]][:], np.nan).astype(np.float64, copy=False)
    if len(lon.shape) == 1 and len(lat.shape) == 1:
        lon, lat = np.meshgrid(lon, lat)
    delta_lon = float(lon[0, 1] - lon[0, 0])
    delta_lat = float(lat[1, 0] - lat[0, 0])
    delta_lon, delta_lat = compute_deltas_in_m(delta_lon, delta_lat, mean_lat=float(np.mean(lat)))
    time = np.ma.filled(dataset.variables[parameterlist[2]][:], np.nan)
    time_units = dataset.variables[parameterlist[2]].units
    u = np.ma.filled(dataset.variables[parameterlist[3]][:], np.nan).astype(np.float64, copy=False)
    v = np.ma.filled(dataset.variables[parameterlist[4]][:], np.nan).astype(np.float64, copy=False)
    dataset.close()
    return lon, lat, time, u, v, time_units, delta_lon, delta_lat

def load_sw_data(netcdf_file, parameterlist):
    dataset = nc.Dataset(netcdf_file)
    if len(parameterlist) >= 5:
        t_var, s_var = parameterlist[3], parameterlist[4]
    elif len(parameterlist) >= 4:
        t_var, s_var = parameterlist[2], parameterlist[3]
    else:
        t_var, s_var = parameterlist[0], parameterlist[1]
    temp_raw = dataset.variables[t_var][:]
    salt_raw = dataset.variables[s_var][:]
    if temp_raw.ndim == 4:
        temp_raw = temp_raw[:, 0, :, :]
    if salt_raw.ndim == 4:
        salt_raw = salt_raw[:, 0, :, :]
    temp = np.ma.filled(temp_raw, np.nan).astype(np.float64, copy=False)
    salt = np.ma.filled(salt_raw, np.nan).astype(np.float64, copy=False)
    dataset.close()
    return temp, salt

def compute_region_limits(lon, lat):
    global lon_min, lon_max, lat_min, lat_max
    lon_min, lon_max = np.min(lon), np.max(lon)
    lat_min, lat_max = np.min(lat), np.max(lat)
    if 0 < verbose <= 2:
        print("\nGeographic limits of input files:")
        print(f"Longitude, from {lon_min} to {lon_max}")
        print(f"Latitude, from {lat_min} to {lat_max}\n")

def is_point_inside_region(target_lon, target_lat):
    return lon_min <= target_lon <= lon_max and lat_min <= target_lat <= lat_max

def load_wind_data(netcdf_file, parameterlist):
    dataset = nc.Dataset(netcdf_file)
    if len(parameterlist) >= 5:
        wlon = dataset.variables[parameterlist[0]][:]
        wlat = dataset.variables[parameterlist[1]][:]
        if len(wlon.shape) == 1 and len(wlat.shape) == 1:
            wlon, wlat = np.meshgrid(wlon, wlat)
        uwind = dataset.variables[parameterlist[3]][:]
        vwind = dataset.variables[parameterlist[4]][:]
    elif len(parameterlist) >= 4:
        wlon = dataset.variables[parameterlist[0]][:]
        wlat = dataset.variables[parameterlist[1]][:]
        if len(wlon.shape) == 1 and len(wlat.shape) == 1:
            wlon, wlat = np.meshgrid(wlon, wlat)
        uwind = dataset.variables[parameterlist[2]][:]
        vwind = dataset.variables[parameterlist[3]][:]
    else:
        wlon, wlat = None, None
        uwind = dataset.variables[parameterlist[0]][:]
        vwind = dataset.variables[parameterlist[1]][:]
    uwind = np.ma.filled(uwind, np.nan).astype(np.float64, copy=False)
    vwind = np.ma.filled(vwind, np.nan).astype(np.float64, copy=False)
    dataset.close()
    return uwind, vwind, wlon, wlat

def select_simulation_data(u, v, start_time, stop_time, time_step):
    if start_time > stop_time:
        stop_idx = stop_time - 1 if stop_time > 0 else None
        u_value = u[start_time:stop_idx:-time_step, :, :]
        v_value = v[start_time:stop_idx:-time_step, :, :]
    else:
        u_value = u[start_time:stop_time+1:time_step, :, :]
        v_value = v[start_time:stop_time+1:time_step, :, :]
    return u_value, v_value

def get_uv_at_coordinates(lon, lat, u, v, target_lon, target_lat, time_index, method='linear', points_lat_lon=None):
    if points_lat_lon is None:
        points_lat_lon = np.column_stack((lat.ravel(), lon.ravel()))
    u_value = griddata(points_lat_lon, u[time_index].ravel(), (target_lat, target_lon), method=method)
    v_value = griddata(points_lat_lon, v[time_index].ravel(), (target_lat, target_lon), method=method)
    return u_value, v_value

def get_var_at_coordinates(lon, lat, var, target_lon, target_lat, time_index, method='linear', points_lat_lon=None):
    if points_lat_lon is None:
        points_lat_lon = np.column_stack((lat.ravel(), lon.ravel()))
    var_value = griddata(points_lat_lon, var[time_index].ravel(), (target_lat, target_lon), method=method)
    return var_value

def interpolate_var_at_coordinates_kn(lon, lat, var, target_lon, target_lat, num_nodes=4, tree=None):
    if not (np.isfinite(target_lon) and np.isfinite(target_lat)):
        return np.nan
    if tree is None:
        points = np.column_stack((lon.flatten(), lat.flatten()))
        tree = cKDTree(points)
    target_point = np.array([[float(target_lon), float(target_lat)]])
    _, nearest_indices = tree.query(target_point, k=num_nodes)
    nearest_values = var.flatten()[nearest_indices]
    interpolated_value = np.mean(nearest_values)
    return float(interpolated_value) if np.isfinite(interpolated_value) else np.nan

def get_uv_at_coordinates_k_nodes(lon, lat, u, v, target_lon, target_lat, time_index, num_nodes=4, tree=None):
    u_value = interpolate_var_at_coordinates_kn(lon, lat, u[time_index], target_lon, target_lat, num_nodes, tree=tree)
    v_value = interpolate_var_at_coordinates_kn(lon, lat, v[time_index], target_lon, target_lat, num_nodes, tree=tree)
    return u_value, v_value

def get_k_nodes(aux_int_mthd):
    k_map = {"k4": 4, "k12": 12, "k16": 16}
    k_nodes = k_map.get(aux_int_mthd, 4)
    return k_nodes

def load_bathymetry_data(netcdf_file):
    dataset = nc.Dataset(netcdf_file)
    H = dataset.variables['H'][:]
    dataset.close()
    return H

def load_initial_positions(csv_file):
    with open(csv_file, 'r') as file:
        reader = csv.reader(file)
        particles = []
        for row in reader:
            name = row[0]
            lon = float(row[1])
            lat = float(row[2])
            particles.append([name, lon, lat])
    return particles

def print_particle_positions(particles):
    if not particles:
        print("There is no particle data to print.\n")
        return
    table = PrettyTable(["Particle", "Longitude", "Latitude"])
    table.align["Particle"] = "l"
    table.align["Longitude"] = "r"
    table.align["Latitude"] = "r"
    for particle in particles:
        name, lon, lat = particle
        table.add_row([name, lon, lat])
    print(table.get_string(border=True, hrules=False))

def load_polygons(from_file):
    polygons = []
    with open(from_file, 'r') as file:
        lines = file.readlines()
        i = 0
        while i < len(lines):
            num_points = int(lines[i].strip())
            vertices = []
            for j in range(i + 1, i + num_points + 1):
                lon, lat = map(float, lines[j].strip().split())
                vertices.append((lon, lat))
            polygons.append(vertices)
            i += num_points + 1
    return polygons

def meters_to_degrees(distance_meters):
    degrees = distance_meters / 111320.0
    return degrees

def compute_randomwalk(delta_t):
    global horizdiff
    rt_value = meters_to_degrees(np.sqrt(12 * horizdiff * delta_t) * C1 * np.cos(2 * np.pi * np.random.random()))
    return rt_value

def compute_uniform(delta_t):
    denom = (8784 - delta_t) if delta_t != 8784 else 1.0
    rt_value = meters_to_degrees(C1 * delta_t / denom * np.random.random())
    return rt_value

def compute_randomvalues(delta_t):
    denom = (8784 - delta_t) if delta_t != 8784 else 1.0
    rt_value = meters_to_degrees(C1 * delta_t / denom * np.random.rand())
    return rt_value

def compute_anorm(delta_t):
    denom = (8784 - delta_t) if delta_t != 8784 else 1.0
    rt_value = meters_to_degrees(C1 * delta_t / denom * np.random.normal(0.5, 0.25, 1)[0])
    return rt_value

def compute_mas(currenttime):
    rt_value = meters_to_degrees(C1 * np.cos(2 * np.pi / C2 * currenttime))
    return rt_value

def compute_dmas(currenttime):
    global horizdiff
    rt_value = meters_to_degrees(C1 * np.sqrt(2 * horizdiff) * np.cos(2 * np.pi / C2 * currenttime))
    return rt_value

def compute_wiener(delta_t, currenttime):
    global horizdiff
    rt_value = meters_to_degrees(C1 *
                                 (np.abs(currenttime - delta_t) * np.sqrt(delta_t) *
                                  np.random.normal(0, np.sqrt(2 * horizdiff), 1)[0]))
    return rt_value

def compute_poisson(current_time):
    rt_arr = np.random.poisson(lam=C2, size=current_time + 1)
    rt_value = meters_to_degrees(C1 * rt_arr[np.random.randint(0, current_time + 1)])
    return rt_value

def compute_random_term(delta_t, current_time):
    global random_term
    if not random_term:
        return 0.0
    method = rt_method.upper()
    if method == "RANDOMWALK":
        rt_value = compute_randomwalk(delta_t)
    elif method == "RANDOM":
        rt_value = compute_randomvalues(delta_t)
    elif method == "ANORM":
        rt_value = compute_anorm(delta_t)
    elif method == "MAS":
        rt_value = compute_mas(current_time)
    elif method == "DMAS":
        rt_value = compute_dmas(current_time)
    elif method == "UNIFORM":
        rt_value = compute_uniform(delta_t)
    elif method in ("WEINER", "WIENER"):
        rt_value = compute_wiener(delta_t, current_time)
    elif method == "POISSON":
        rt_value = compute_poisson(current_time)
    else:
        print(f"Method {rt_method} is unknown for the computation of the random term\n")
        random_term = False
        return 0.0
    return rt_value

def _compute_dt_seconds(time_arr, t_units, t_step):
    if time_arr is None or len(time_arr) < 2:
        return float(t_step)
    dt_raw = abs(float(time_arr[1] - time_arr[0]))
    u_str = str(t_units).lower() if t_units is not None else ""
    if "day" in u_str:
        unit_sec = 86400.0
    elif "hour" in u_str:
        unit_sec = 3600.0
    elif "minute" in u_str:
        unit_sec = 60.0
    else:
        unit_sec = 1.0
    dt_sec = dt_raw * unit_sec * float(t_step)
    return dt_sec if dt_sec > 0 else float(t_step)

def _seawater_density_eos80(temp_c, salt_psu):
    t = float(temp_c)
    s = float(salt_psu)
    rho_0 = (999.842594 + 6.793952e-2 * t - 9.095290e-3 * t**2
             + 1.001685e-4 * t**3 - 1.120083e-6 * t**4 + 6.536332e-9 * t**5)
    a = (8.24493e-1 - 4.0899e-3 * t + 7.6438e-5 * t**2
         - 8.2467e-7 * t**3 + 5.3875e-9 * t**4)
    b = -5.72466e-3 + 1.0227e-4 * t - 1.6546e-6 * t**2
    c = 4.8314e-4
    return rho_0 + a * s + b * (s ** 1.5) + c * (s ** 2)

def _compute_windwavecoef_automatic(u_wind, v_wind, lon_p, lat_p):
    w = float(np.hypot(u_wind, v_wind))
    if not np.isfinite(w) or w <= 0.0:
        return 0.0
    if w <= 1.0:
        return 0.5 * np.sqrt(w) * 1e-3
    if w <= 15.0:
        return (0.8 + 0.065 * w) * 1e-3
    lon_norm = ((float(lon_p) + 180.0) % 360.0) - 180.0
    lat_val = float(lat_p)
    in_caribbean = (-84.31 <= lon_norm <= -63.87) and (8.84 <= lat_val <= 26.95)
    in_gom = (-98.01 <= lon_norm <= -83.57) and (15.83 <= lat_val <= 30.64)
    if in_caribbean or in_gom:
        return 3.4e-3
    return 2.26e-3

def compute_curwind_diffusion(delta_t):
    r1 = np.random.random()
    r2 = np.random.random()
    return meters_to_degrees(np.sqrt(12 * horizdiff * delta_t) * r1 * np.cos(2 * np.pi * r2))

_WORKER_STATE = {}

def _init_worker(state):
    global _WORKER_STATE
    global lon_min, lon_max, lat_min, lat_max
    global horizdiff, C1, C2, random_term, rt_method
    _WORKER_STATE = state
    lon_min = state["lon_min"]
    lon_max = state["lon_max"]
    lat_min = state["lat_min"]
    lat_max = state["lat_max"]
    horizdiff = state["horizdiff"]
    C1 = state["C1"]
    C2 = state["C2"]
    random_term = state["random_term"]
    rt_method = state["rt_method"]
    _WORKER_STATE["points_lat_lon"] = np.column_stack((state["lat"].ravel(), state["lon"].ravel()))
    _WORKER_STATE["kdtree"] = cKDTree(np.column_stack((state["lon"].flatten(), state["lat"].flatten())))
    if state.get("wind_lon") is not None and state.get("wind_lat") is not None:
        _WORKER_STATE["wind_points_lat_lon"] = np.column_stack((state["wind_lat"].ravel(), state["wind_lon"].ravel()))
        _WORKER_STATE["wind_kdtree"] = cKDTree(np.column_stack((state["wind_lon"].flatten(), state["wind_lat"].flatten())))
    else:
        _WORKER_STATE["wind_points_lat_lon"] = _WORKER_STATE["points_lat_lon"]
        _WORKER_STATE["wind_kdtree"] = _WORKER_STATE["kdtree"]
    if state.get("stokes_lon") is not None and state.get("stokes_lat") is not None:
        _WORKER_STATE["stokes_points_lat_lon"] = np.column_stack((state["stokes_lat"].ravel(), state["stokes_lon"].ravel()))
        _WORKER_STATE["stokes_kdtree"] = cKDTree(np.column_stack((state["stokes_lon"].flatten(), state["stokes_lat"].flatten())))
    else:
        _WORKER_STATE["stokes_points_lat_lon"] = _WORKER_STATE["points_lat_lon"]
        _WORKER_STATE["stokes_kdtree"] = _WORKER_STATE["kdtree"]

def _interp_uv_worker(lon, lat, u, v, lon_p, lat_p, t_idx, interp_method, points_lat_lon, knodes, kdtree):
    if not (np.isfinite(lon_p) and np.isfinite(lat_p)):
        return np.nan, np.nan
    u_val, v_val = get_uv_at_coordinates(
        lon, lat, u, v, lon_p, lat_p, t_idx, method=interp_method, points_lat_lon=points_lat_lon
    )
    if np.isnan(u_val) or np.isnan(v_val):
        u_val, v_val = get_uv_at_coordinates_k_nodes(
            lon, lat, u, v, lon_p, lat_p, t_idx, num_nodes=knodes, tree=kdtree
        )
    return u_val, v_val

def _simulate_single_particle(task):
    p_start = perf_counter()
    i_part, particle = task
    s = _WORKER_STATE
    lon = s["lon"]
    lat = s["lat"]
    u = s["u"]
    v = s["v"]
    uwind_arr = s.get("uwind")
    vwind_arr = s.get("vwind")
    w_lon = lon if s.get("wind_lon") is None else s["wind_lon"]
    w_lat = lat if s.get("wind_lat") is None else s["wind_lat"]
    ustokes_arr = s.get("ustokes")
    vstokes_arr = s.get("vstokes")
    s_lon = lon if s.get("stokes_lon") is None else s["stokes_lon"]
    s_lat = lat if s.get("stokes_lat") is None else s["stokes_lat"]
    model_mode = s.get("model_mode", "FOCURR")
    needs_wind = model_mode in ("CURWIND", "GNOME", "OPENDRIFT", "MEDSLIK2", "OSCAR", "uPLASTIC", "LEEWAY", "SARGASSUM", "ICEFLOES", "DEBRIS")
    needs_stokes = model_mode in ("OPENDRIFT", "MEDSLIK2", "uPLASTIC", "LARVAE", "SARGASSUM", "DEBRIS") and ustokes_arr is not None and vstokes_arr is not None
    estimate_stokes_from_wind = (
        model_mode in ("OPENDRIFT", "MEDSLIK2", "uPLASTIC", "LARVAE", "SARGASSUM", "DEBRIS")
        and not needs_stokes
        and uwind_arr is not None and vwind_arr is not None
    )
    c_cor = s.get("currcoef", 1.0)
    c_ww = s.get("windwavecoef", 0.0)
    use_ww_auto = s.get("windwavecoef_automatic", False)
    c_stokes = s.get("stokes_wind_coef", 0.015)
    theta_rad = np.radians(s.get("leeway_angle", 0.0))
    rho_p0 = s.get("plastic_density", 920.0)
    biofoul_rate = s.get("biofouling_rate", 0.0)
    u_act = s.get("larvae_u_active", 0.0)
    v_act = s.get("larvae_v_active", 0.0)
    t_pld = s.get("larvae_pld", 1e9)
    m_rate = s.get("larvae_mortality_rate", 0.0)
    b_sarg = s.get("sargassum_biomass_init", 1.0)
    mu_sarg = s.get("sargassum_growth_rate", 0.0)
    m_sarg = s.get("sargassum_mortality_rate", 0.0)
    v_ice = s.get("ice_volume_init", 1e6)
    u_grad_ice = s.get("ice_u_grad", 0.0)
    v_grad_ice = s.get("ice_v_grad", 0.0)
    c_coriolis_ice = s.get("ice_coriolis_coef", 1.0)
    a_basal = s.get("ice_ablation_basal", 0.0)
    a_lateral = s.get("ice_ablation_lateral", 0.0)
    a_thermal = s.get("ice_ablation_thermal", 0.0)
    c_debris = s.get("debris_windage", c_ww)
    d_rate = s.get("decay_rate", 0.0)
    d_thresh = s.get("decay_min_threshold", 0.01)
    okubo_l0 = s.get("okubo_ref_length", 1000.0)
    z_sub = s.get("subsurface_depth_init", 10.0)
    w_settle = s.get("subsurface_settling_rate", 0.0)
    z_sub_max = s.get("subsurface_max_depth", 100.0)
    res_bbox = s.get("residence_bbox")
    c_tracer = 1.0
    omega_earth = 7.2921e-5
    temp_arr = s["temp"]
    salt_arr = s["salt"]
    stop_t = s["stop_time"]
    t_step = s["time_step"]
    dt_sec = s["dt_seconds"]
    knodes = s["knodes"]
    interp_method = s["interpolation_method"]
    use_sw = s["seawater_properties"]
    use_transport = s["compute_transport"]
    use_random = s["random_term"]
    dlon = s["deltalon"]
    dlat = s["deltalat"]
    verb = s["verbose"]
    points_lat_lon = s["points_lat_lon"]
    kdtree = s["kdtree"]
    wind_points_lat_lon = s["wind_points_lat_lon"]
    wind_kdtree = s["wind_kdtree"]
    stokes_points_lat_lon = s["stokes_points_lat_lon"]
    stokes_kdtree = s["stokes_kdtree"]

    traj = np.empty((stop_t + 1, 7))
    traj[:] = np.nan

    if verb == 2:
        print(f"\nParticle: {i_part}\n")

    part_name, lon_current_part, lat_current_part = particle
    lon0_part, lat0_part = lon_current_part, lat_current_part
    for current_time in range(stop_t):
        if current_time == 0:
            traj[current_time] = [lon_current_part, lat_current_part, np.nan, np.nan, np.nan, np.nan, np.nan]
        if verb == 2:
            print(f"lon={lon_current_part}, lat={lat_current_part}")
        if not is_point_inside_region(lon_current_part, lat_current_part):
            print(f"\nWarning: Particle '{part_name}' (#{i_part + 1}) outside region at step {current_time} (lon={lon_current_part:.4f}, lat={lat_current_part:.4f}); skipping remaining steps.")
            break

        u_cor, v_cor = get_uv_at_coordinates(
            lon, lat, u, v, lon_current_part, lat_current_part,
            current_time, method=interp_method, points_lat_lon=points_lat_lon
        )
        if np.isnan(u_cor) or np.isnan(v_cor):
            u_cor, v_cor = get_uv_at_coordinates_k_nodes(
                lon, lat, u, v, lon_current_part, lat_current_part,
                current_time, num_nodes=knodes, tree=kdtree
            )
            if np.isnan(u_cor) or np.isnan(v_cor):
                print(f"\nWarning: Particle '{part_name}' (#{i_part + 1}) encountered NaN current velocity at step {current_time} (lon={lon_current_part:.4f}, lat={lat_current_part:.4f}); skipping remaining steps.")
                break

        u_10, v_10 = 0.0, 0.0
        if needs_wind or estimate_stokes_from_wind:
            u_10, v_10 = get_uv_at_coordinates(
                w_lon, w_lat, uwind_arr, vwind_arr, lon_current_part, lat_current_part,
                current_time, method=interp_method, points_lat_lon=wind_points_lat_lon
            )
            if np.isnan(u_10) or np.isnan(v_10):
                u_10, v_10 = get_uv_at_coordinates_k_nodes(
                    w_lon, w_lat, uwind_arr, vwind_arr, lon_current_part, lat_current_part,
                    current_time, num_nodes=knodes, tree=wind_kdtree
                )
                if np.isnan(u_10) or np.isnan(v_10):
                    print(f"\nWarning: Particle '{part_name}' (#{i_part + 1}) encountered NaN wind velocity at step {current_time} (lon={lon_current_part:.4f}, lat={lat_current_part:.4f}); skipping remaining steps.")
                    break

        u_st, v_st = 0.0, 0.0
        if needs_stokes:
            u_st, v_st = get_uv_at_coordinates(
                s_lon, s_lat, ustokes_arr, vstokes_arr, lon_current_part, lat_current_part,
                current_time, method=interp_method, points_lat_lon=stokes_points_lat_lon
            )
            if np.isnan(u_st) or np.isnan(v_st):
                u_st, v_st = get_uv_at_coordinates_k_nodes(
                    s_lon, s_lat, ustokes_arr, vstokes_arr, lon_current_part, lat_current_part,
                    current_time, num_nodes=knodes, tree=stokes_kdtree
                )
                if np.isnan(u_st) or np.isnan(v_st):
                    u_st, v_st = 0.0, 0.0
        elif estimate_stokes_from_wind:
            u_st = c_stokes * u_10
            v_st = c_stokes * v_10

        c_ww_step = (
            _compute_windwavecoef_automatic(u_10, v_10, lon_current_part, lat_current_part)
            if use_ww_auto else c_ww
        )

        if model_mode == "FOCURR":
            u_effective, v_effective = u_cor, v_cor
        elif model_mode == "FOCURR_RK2":
            t_next = min(current_time + 1, stop_t - 1)
            cos_l1 = max(np.cos(np.radians(lat_current_part)), 1e-6)
            lon_m = lon_current_part + meters_to_degrees(u_cor * dt_sec) / cos_l1
            lat_m = lat_current_part + meters_to_degrees(v_cor * dt_sec)
            u2, v2 = _interp_uv_worker(lon, lat, u, v, lon_m, lat_m, t_next, interp_method, points_lat_lon, knodes, kdtree)
            if np.isnan(u2) or np.isnan(v2):
                u2, v2 = u_cor, v_cor
            u_effective = 0.5 * (u_cor + u2)
            v_effective = 0.5 * (v_cor + v2)
        elif model_mode == "FOCURR_RK4":
            t_next = min(current_time + 1, stop_t - 1)
            cos_l1 = max(np.cos(np.radians(lat_current_part)), 1e-6)
            lon2 = lon_current_part + 0.5 * meters_to_degrees(u_cor * dt_sec) / cos_l1
            lat2 = lat_current_part + 0.5 * meters_to_degrees(v_cor * dt_sec)
            u2, v2 = _interp_uv_worker(lon, lat, u, v, lon2, lat2, current_time, interp_method, points_lat_lon, knodes, kdtree)
            if np.isnan(u2) or np.isnan(v2):
                u2, v2 = u_cor, v_cor
            lon3 = lon_current_part + 0.5 * meters_to_degrees(u2 * dt_sec) / cos_l1
            lat3 = lat_current_part + 0.5 * meters_to_degrees(v2 * dt_sec)
            u3, v3 = _interp_uv_worker(lon, lat, u, v, lon3, lat3, current_time, interp_method, points_lat_lon, knodes, kdtree)
            if np.isnan(u3) or np.isnan(v3):
                u3, v3 = u2, v2
            lon4 = lon_current_part + meters_to_degrees(u3 * dt_sec) / cos_l1
            lat4 = lat_current_part + meters_to_degrees(v3 * dt_sec)
            u4, v4 = _interp_uv_worker(lon, lat, u, v, lon4, lat4, t_next, interp_method, points_lat_lon, knodes, kdtree)
            if np.isnan(u4) or np.isnan(v4):
                u4, v4 = u3, v3
            u_effective = (u_cor + 2.0 * u2 + 2.0 * u3 + u4) / 6.0
            v_effective = (v_cor + 2.0 * v2 + 2.0 * v3 + v4) / 6.0
        elif model_mode in ("DECAY_TRACER", "RESIDENCE_TIME", "OKUBO", "SUBSURFACE"):
            u_effective, v_effective = u_cor, v_cor
        elif model_mode == "CURWIND":
            u_effective = c_cor * u_cor + c_ww_step * u_10
            v_effective = c_cor * v_cor + c_ww_step * v_10
        elif model_mode in ("GNOME", "LEEWAY"):
            u_effective = u_cor + c_ww_step * u_10 * np.cos(theta_rad) - c_ww_step * v_10 * np.sin(theta_rad)
            v_effective = v_cor + c_ww_step * u_10 * np.sin(theta_rad) + c_ww_step * v_10 * np.cos(theta_rad)
        elif model_mode in ("OPENDRIFT", "MEDSLIK2", "uPLASTIC", "SARGASSUM"):
            u_effective = u_cor + u_st + c_ww_step * u_10
            v_effective = v_cor + v_st + c_ww_step * v_10
        elif model_mode == "DEBRIS":
            u_effective = u_cor + c_debris * u_10 + u_st
            v_effective = v_cor + c_debris * v_10 + v_st
        elif model_mode == "ICEFLOES":
            f_cor = 2.0 * omega_earth * np.sin(np.radians(lat_current_part))
            u_coriolis = c_coriolis_ice * f_cor * v_cor
            v_coriolis = -c_coriolis_ice * f_cor * u_cor
            u_effective = u_cor + c_ww_step * u_10 + u_grad_ice + u_coriolis
            v_effective = v_cor + c_ww_step * v_10 + v_grad_ice + v_coriolis
        elif model_mode == "LARVAE":
            u_effective = u_cor + u_act + u_st
            v_effective = v_cor + v_act + v_st
        elif model_mode == "OSCAR":
            u_effective = u_cor + c_ww_step * u_10
            v_effective = v_cor + c_ww_step * v_10
        else:
            u_effective, v_effective = u_cor, v_cor

        if use_sw:
            new_temp = get_var_at_coordinates(
                lon, lat, temp_arr, lon_current_part, lat_current_part,
                current_time, method=interp_method, points_lat_lon=points_lat_lon
            )
            new_salt = get_var_at_coordinates(
                lon, lat, salt_arr, lon_current_part, lat_current_part,
                current_time, method=interp_method, points_lat_lon=points_lat_lon
            )
            if np.isnan(new_temp) or np.isnan(new_salt):
                new_temp = interpolate_var_at_coordinates_kn(
                    lon, lat, temp_arr[current_time], lon_current_part,
                    lat_current_part, num_nodes=knodes, tree=kdtree
                )
                new_salt = interpolate_var_at_coordinates_kn(
                    lon, lat, salt_arr[current_time], lon_current_part,
                    lat_current_part, num_nodes=knodes, tree=kdtree
                )

        if use_random:
            if model_mode == "CURWIND" and rt_method.upper() == "RANDOMWALK":
                randomvalue_lon = compute_curwind_diffusion(dt_sec)
                randomvalue_lat = compute_curwind_diffusion(dt_sec)
            elif model_mode == "GNOME":
                scale = np.sqrt(6.0 * horizdiff * dt_sec)
                randomvalue_lon = meters_to_degrees(scale * np.random.uniform(-1.0, 1.0))
                randomvalue_lat = meters_to_degrees(scale * np.random.uniform(-1.0, 1.0))
            elif model_mode in ("OPENDRIFT", "OSCAR", "uPLASTIC", "LARVAE", "LEEWAY", "SARGASSUM", "ICEFLOES", "DEBRIS", "FOCURR_RK2", "FOCURR_RK4", "DECAY_TRACER", "RESIDENCE_TIME", "SUBSURFACE"):
                scale = np.sqrt(2.0 * horizdiff * dt_sec)
                randomvalue_lon = meters_to_degrees(scale * np.random.normal(0.0, 1.0))
                randomvalue_lat = meters_to_degrees(scale * np.random.normal(0.0, 1.0))
            elif model_mode == "OKUBO":
                dist_m = max(okubo_l0, 111320.0 * np.hypot((lon_current_part - lon0_part) * np.cos(np.radians(lat0_part)), lat_current_part - lat0_part))
                kh_okubo = min(horizdiff * ((dist_m / okubo_l0) ** (4.0 / 3.0)), 5000.0)
                scale = np.sqrt(2.0 * kh_okubo * dt_sec)
                randomvalue_lon = meters_to_degrees(scale * np.random.normal(0.0, 1.0))
                randomvalue_lat = meters_to_degrees(scale * np.random.normal(0.0, 1.0))
            elif model_mode == "MEDSLIK2":
                scale = np.sqrt(2.0 * horizdiff * dt_sec)
                r01 = np.random.random()
                randomvalue_lon = meters_to_degrees(scale * np.cos(2.0 * np.pi * r01))
                randomvalue_lat = meters_to_degrees(scale * np.sin(2.0 * np.pi * r01))
            else:
                randomvalue_lon = compute_random_term(dt_sec, current_time)
                randomvalue_lat = compute_random_term(dt_sec, current_time)
        else:
            randomvalue_lon = 0.0
            randomvalue_lat = 0.0

        cos_lat = max(np.cos(np.radians(lat_current_part)), 1e-6)
        new_lon = lon_current_part + meters_to_degrees(u_effective * dt_sec) / cos_lat + randomvalue_lon
        new_lat = lat_current_part + meters_to_degrees(v_effective * dt_sec) + randomvalue_lat

        current_speed = float(np.hypot(u_cor, v_cor))
        wind_speed = float(np.hypot(u_10, v_10)) if (needs_wind or estimate_stokes_from_wind) else np.nan
        transport_val = np.sqrt(u_effective * u_effective + v_effective * v_effective) * dlon * dlat if use_transport else np.nan
        temp_val = new_temp if use_sw else np.nan
        salt_val = new_salt if use_sw else np.nan
        traj[current_time + 1] = [new_lon, new_lat, transport_val, temp_val, salt_val, current_speed, wind_speed]

        lon_current_part = new_lon
        lat_current_part = new_lat

        elapsed_t = (current_time + 1) * dt_sec
        if model_mode == "uPLASTIC":
            rho_p_t = rho_p0 + biofoul_rate * elapsed_t
            rho_w = _seawater_density_eos80(new_temp, new_salt) if use_sw else 1025.0
            if rho_p_t > rho_w:
                break
        elif model_mode == "LARVAE":
            m_asa = 1.0 - np.exp(-m_rate * elapsed_t) if m_rate > 0.0 else 0.0
            if elapsed_t > t_pld or m_asa > np.random.random():
                break
        elif model_mode == "SARGASSUM":
            b_sarg = b_sarg + b_sarg * (mu_sarg - m_sarg) * dt_sec
            if b_sarg <= 0.0:
                break
        elif model_mode == "ICEFLOES":
            v_ice = v_ice - (a_basal + a_lateral + a_thermal) * dt_sec
            if v_ice <= 0.0:
                break
        elif model_mode == "DECAY_TRACER":
            c_tracer = c_tracer * np.exp(-d_rate * dt_sec)
            if c_tracer < d_thresh:
                break
        elif model_mode == "RESIDENCE_TIME":
            if res_bbox is not None:
                if not (res_bbox[0] <= new_lon <= res_bbox[1] and res_bbox[2] <= new_lat <= res_bbox[3]):
                    break
        elif model_mode == "SUBSURFACE":
            z_sub = z_sub + w_settle * dt_sec
            if z_sub > z_sub_max or z_sub < 0.0:
                break

    return i_part, traj, perf_counter() - p_start

def _run_parallel_particles(lon, lat, u, v, particles, model_mode="FOCURR",
                            uwind=None, vwind=None, wind_lon=None, wind_lat=None,
                            ustokes=None, vstokes=None, stokes_lon=None, stokes_lat=None):
    global particle_exec_times
    num_particles = len(particles)
    trajectories = np.empty((num_particles, stop_time + 1, 7))
    trajectories[:] = np.nan
    particle_exec_times = [0.0] * num_particles

    active_tasks = [
        (i_part, particles[i_part])
        for i_part in range(num_particles)
        if active_particles == "all" or i_part in active_particles
    ]
    if not active_tasks:
        return trajectories

    knodes = get_k_nodes(auxiliary_interpolation_method)
    g = globals()
    worker_state = {
        "model_mode": model_mode,
        "lon": lon,
        "lat": lat,
        "u": u,
        "v": v,
        "uwind": uwind,
        "vwind": vwind,
        "wind_lon": wind_lon,
        "wind_lat": wind_lat,
        "ustokes": ustokes,
        "vstokes": vstokes,
        "stokes_lon": stokes_lon,
        "stokes_lat": stokes_lat,
        "currcoef": float(currcoef) if g.get("currcoef") is not None else 1.0,
        "windwavecoef": float(windwavecoef) if g.get("windwavecoef") is not None else 0.0,
        "windwavecoef_automatic": bool(g.get("windwavecoef_automatic", False)),
        "leeway_angle": float(leeway_angle) if g.get("leeway_angle") is not None else 0.0,
        "plastic_density": float(plastic_density) if g.get("plastic_density") is not None else 920.0,
        "biofouling_rate": float(biofouling_rate) if g.get("biofouling_rate") is not None else 0.0,
        "larvae_u_active": float(larvae_u_active) if g.get("larvae_u_active") is not None else 0.0,
        "larvae_v_active": float(larvae_v_active) if g.get("larvae_v_active") is not None else 0.0,
        "larvae_pld": float(larvae_pld) if g.get("larvae_pld") is not None else 1e9,
        "larvae_mortality_rate": float(larvae_mortality_rate) if g.get("larvae_mortality_rate") is not None else 0.0,
        "sargassum_biomass_init": float(sargassum_biomass_init) if g.get("sargassum_biomass_init") is not None else 1.0,
        "sargassum_growth_rate": float(sargassum_growth_rate) if g.get("sargassum_growth_rate") is not None else 0.0,
        "sargassum_mortality_rate": float(sargassum_mortality_rate) if g.get("sargassum_mortality_rate") is not None else 0.0,
        "ice_volume_init": float(ice_volume_init) if g.get("ice_volume_init") is not None else 1e6,
        "ice_u_grad": float(ice_u_grad) if g.get("ice_u_grad") is not None else 0.0,
        "ice_v_grad": float(ice_v_grad) if g.get("ice_v_grad") is not None else 0.0,
        "ice_coriolis_coef": float(ice_coriolis_coef) if g.get("ice_coriolis_coef") is not None else 1.0,
        "ice_ablation_basal": float(ice_ablation_basal) if g.get("ice_ablation_basal") is not None else 0.0,
        "ice_ablation_lateral": float(ice_ablation_lateral) if g.get("ice_ablation_lateral") is not None else 0.0,
        "ice_ablation_thermal": float(ice_ablation_thermal) if g.get("ice_ablation_thermal") is not None else 0.0,
        "debris_windage": float(debris_windage) if g.get("debris_windage") is not None else (float(windwavecoef) if g.get("windwavecoef") is not None else 0.0),
        "stokes_wind_coef": float(stokes_wind_coef) if g.get("stokes_wind_coef") is not None else 0.015,
        "decay_rate": float(decay_rate) if g.get("decay_rate") is not None else 0.0,
        "decay_min_threshold": float(decay_min_threshold) if g.get("decay_min_threshold") is not None else 0.01,
        "residence_bbox": g.get("residence_bbox") if g.get("residence_bbox") and len(g.get("residence_bbox")) == 4 else None,
        "okubo_ref_length": float(okubo_ref_length) if g.get("okubo_ref_length") is not None else 1000.0,
        "subsurface_depth_init": float(subsurface_depth_init) if g.get("subsurface_depth_init") is not None else 10.0,
        "subsurface_settling_rate": float(subsurface_settling_rate) if g.get("subsurface_settling_rate") is not None else 0.0,
        "subsurface_max_depth": float(subsurface_max_depth) if g.get("subsurface_max_depth") is not None else 100.0,
        "temp": g.get("temp"),
        "salt": g.get("salt"),
        "lon_min": lon_min,
        "lon_max": lon_max,
        "lat_min": lat_min,
        "lat_max": lat_max,
        "stop_time": stop_time,
        "time_step": time_step,
        "dt_seconds": float(g.get("dt_seconds", time_step)),
        "knodes": knodes,
        "interpolation_method": interpolation_method,
        "seawater_properties": seawater_properties,
        "compute_transport": compute_transport,
        "random_term": random_term,
        "rt_method": rt_method,
        "horizdiff": horizdiff,
        "C1": C1,
        "C2": C2,
        "deltalon": g.get("deltalon", 0.0),
        "deltalat": g.get("deltalat", 0.0),
        "verbose": verbose,
    }

    total_cores = os.process_cpu_count() if hasattr(os, "process_cpu_count") else os.cpu_count()
    num_workers = max(1, min(total_cores or 1, len(active_tasks)))

    if num_workers == 1:
        _init_worker(worker_state)
        for task in active_tasks:
            i_part, traj, p_elapsed = _simulate_single_particle(task)
            trajectories[i_part] = traj
            particle_exec_times[i_part] = p_elapsed
        return trajectories

    gil_disabled = hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled()
    if gil_disabled:
        _init_worker(worker_state)
        executor_cls = ThreadPoolExecutor
        executor_kwargs = {"max_workers": num_workers}
        mode_label = "threads (free-threaded Python 3.14)"
    else:
        executor_cls = ProcessPoolExecutor
        executor_kwargs = {
            "max_workers": num_workers,
            "initializer": _init_worker,
            "initargs": (worker_state,),
        }
        mode_label = "processes (multi-core)"

    if verbose > 0:
        print(f"Parallelizing {len(active_tasks)} particles ({model_mode}) across {num_workers} CPU cores using {mode_label}...")

    completed = 0
    total_tasks = len(active_tasks)
    with executor_cls(**executor_kwargs) as executor:
        futures = [executor.submit(_simulate_single_particle, task) for task in active_tasks]
        for future in as_completed(futures):
            i_part, traj, p_elapsed = future.result()
            trajectories[i_part] = traj
            particle_exec_times[i_part] = p_elapsed
            completed += 1
            if verbose == 2:
                print(f"Progress: {completed}/{total_tasks} particles completed", flush=True)
            elif verbose > 0:
                print(f"\rProgress: {completed}/{total_tasks} particles completed", end="", flush=True)
    if verbose == 1:
        print()
    return trajectories

def compute_free_ocurr(lon, lat, u, v, particles):
    return _run_parallel_particles(lon, lat, u, v, particles, model_mode="FOCURR")

def compute_curwind(lon, lat, u, v, uwind, vwind, particles, wind_lon=None, wind_lat=None):
    return _run_parallel_particles(
        lon, lat, u, v, particles, model_mode="CURWIND",
        uwind=uwind, vwind=vwind, wind_lon=wind_lon, wind_lat=wind_lat
    )

def compute_gnome(lon, lat, u, v, uwind, vwind, particles, wind_lon=None, wind_lat=None):
    return _run_parallel_particles(
        lon, lat, u, v, particles, model_mode="GNOME",
        uwind=uwind, vwind=vwind, wind_lon=wind_lon, wind_lat=wind_lat
    )

def compute_opendrift(lon, lat, u, v, uwind, vwind, particles, wind_lon=None, wind_lat=None,
                      ustokes=None, vstokes=None, stokes_lon=None, stokes_lat=None):
    return _run_parallel_particles(
        lon, lat, u, v, particles, model_mode="OPENDRIFT",
        uwind=uwind, vwind=vwind, wind_lon=wind_lon, wind_lat=wind_lat,
        ustokes=ustokes, vstokes=vstokes, stokes_lon=stokes_lon, stokes_lat=stokes_lat
    )

def compute_medslik2(lon, lat, u, v, uwind, vwind, particles, wind_lon=None, wind_lat=None,
                     ustokes=None, vstokes=None, stokes_lon=None, stokes_lat=None):
    return _run_parallel_particles(
        lon, lat, u, v, particles, model_mode="MEDSLIK2",
        uwind=uwind, vwind=vwind, wind_lon=wind_lon, wind_lat=wind_lat,
        ustokes=ustokes, vstokes=vstokes, stokes_lon=stokes_lon, stokes_lat=stokes_lat
    )

def compute_oscar(lon, lat, u, v, uwind, vwind, particles, wind_lon=None, wind_lat=None):
    return _run_parallel_particles(
        lon, lat, u, v, particles, model_mode="OSCAR",
        uwind=uwind, vwind=vwind, wind_lon=wind_lon, wind_lat=wind_lat
    )

def compute_uplastic(lon, lat, u, v, uwind, vwind, particles, wind_lon=None, wind_lat=None,
                     ustokes=None, vstokes=None, stokes_lon=None, stokes_lat=None):
    return _run_parallel_particles(
        lon, lat, u, v, particles, model_mode="uPLASTIC",
        uwind=uwind, vwind=vwind, wind_lon=wind_lon, wind_lat=wind_lat,
        ustokes=ustokes, vstokes=vstokes, stokes_lon=stokes_lon, stokes_lat=stokes_lat
    )

def compute_larvae(lon, lat, u, v, particles, ustokes=None, vstokes=None, stokes_lon=None, stokes_lat=None):
    return _run_parallel_particles(
        lon, lat, u, v, particles, model_mode="LARVAE",
        ustokes=ustokes, vstokes=vstokes, stokes_lon=stokes_lon, stokes_lat=stokes_lat
    )

def compute_leeway(lon, lat, u, v, uwind, vwind, particles, wind_lon=None, wind_lat=None):
    return _run_parallel_particles(
        lon, lat, u, v, particles, model_mode="LEEWAY",
        uwind=uwind, vwind=vwind, wind_lon=wind_lon, wind_lat=wind_lat
    )

def compute_sargassum(lon, lat, u, v, uwind, vwind, particles, wind_lon=None, wind_lat=None,
                      ustokes=None, vstokes=None, stokes_lon=None, stokes_lat=None):
    return _run_parallel_particles(
        lon, lat, u, v, particles, model_mode="SARGASSUM",
        uwind=uwind, vwind=vwind, wind_lon=wind_lon, wind_lat=wind_lat,
        ustokes=ustokes, vstokes=vstokes, stokes_lon=stokes_lon, stokes_lat=stokes_lat
    )

def compute_icefloes(lon, lat, u, v, uwind, vwind, particles, wind_lon=None, wind_lat=None):
    return _run_parallel_particles(
        lon, lat, u, v, particles, model_mode="ICEFLOES",
        uwind=uwind, vwind=vwind, wind_lon=wind_lon, wind_lat=wind_lat
    )

def compute_debris(lon, lat, u, v, uwind, vwind, particles, wind_lon=None, wind_lat=None,
                   ustokes=None, vstokes=None, stokes_lon=None, stokes_lat=None):
    return _run_parallel_particles(
        lon, lat, u, v, particles, model_mode="DEBRIS",
        uwind=uwind, vwind=vwind, wind_lon=wind_lon, wind_lat=wind_lat,
        ustokes=ustokes, vstokes=vstokes, stokes_lon=stokes_lon, stokes_lat=stokes_lat
    )

def compute_focurr_rk2(lon, lat, u, v, particles):
    return _run_parallel_particles(lon, lat, u, v, particles, model_mode="FOCURR_RK2")

def compute_focurr_rk4(lon, lat, u, v, particles):
    return _run_parallel_particles(lon, lat, u, v, particles, model_mode="FOCURR_RK4")

def compute_decay_tracer(lon, lat, u, v, particles):
    return _run_parallel_particles(lon, lat, u, v, particles, model_mode="DECAY_TRACER")

def compute_residence_time(lon, lat, u, v, particles):
    return _run_parallel_particles(lon, lat, u, v, particles, model_mode="RESIDENCE_TIME")

def compute_okubo(lon, lat, u, v, particles):
    return _run_parallel_particles(lon, lat, u, v, particles, model_mode="OKUBO")

def compute_subsurface(lon, lat, u, v, particles):
    return _run_parallel_particles(lon, lat, u, v, particles, model_mode="SUBSURFACE")

def read_colortable():
    with open(track_colortable, "r") as file:
        lines = [ln.strip() for ln in file if ln.strip()]
    colors = []
    for line in lines:
        vals = [float(x) for x in line.split(',')]
        if all(0.0 <= v <= 1.0 for v in vals) and any('.' in x for x in line.split(',')):
            colors.append(tuple(int(round(v * 255)) for v in vals[:3]))
        else:
            colors.append(tuple(int(round(v)) for v in vals[:3]))
    return colors

def get_color_by_index(colors, index):
    if colors and index >= 0:
        color_hex = "#{:02X}{:02X}{:02X}".format(*colors[index % len(colors)])
        return color_hex
    return None

def plot_pathway(lon_min, lon_max, lat_min, lat_max, trajectories, particle_numbers="all", show_labels=False):
    global label_color, label_fontsize, legend_position, legend_fontsize, legend_numcol
    fig, ax = plt.subplots(subplot_kw={'projection': crs.PlateCarree()})
    ax.set_extent([lon_min, lon_max, lat_min, lat_max])
    ax.add_feature(cfeature.LAND, edgecolor='black', facecolor='#DCDCDC', linewidth=0.15)
    ax.add_feature(cfeature.COASTLINE, edgecolor='black', linewidth=0.75)
    gl = ax.gridlines(crs=crs.PlateCarree(), draw_labels=True, linewidth=1, color='gray', alpha=0.5, linestyle='--')
    gl.xformatter = LongitudeFormatter()
    gl.yformatter = LatitudeFormatter()
    if particle_numbers == "all":
        particle_numbers = list(range(trajectories.shape[0]))
    else:
        particle_numbers = list(particle_numbers)
    parts_list = globals().get("particles", [])
    if not parts_list and globals().get("input_directory") and globals().get("particles_file"):
        p_csv = input_directory + particles_file
        if os.path.isfile(p_csv):
            parts_list = load_initial_positions(p_csv)
    plotted_count = 0
    for particle_number in particle_numbers:
        if particle_number < 0 or particle_number > trajectories.shape[0] - 1:
            print(f'Error: Particle number must be between 0 and {trajectories.shape[0] - 1}. Skipping particle {particle_number}.')
            continue
        lon_values = trajectories[particle_number, :, 0]
        lat_values = trajectories[particle_number, :, 1]
        time_values = range(trajectories.shape[1])
        color = get_color_by_index(tackcolors, particle_number)
        p_label = parts_list[particle_number][0] if particle_number < len(parts_list) else f'P{particle_number + 1}'
        if track_lines:
            ax.plot(lon_values, lat_values, linestyle=track_linestyle, linewidth=tack_linewidth, color=color,
                    label=p_label, transform=crs.PlateCarree())
        else:
            ax.plot(lon_values, lat_values, marker='o', markersize=2, linestyle=track_linestyle, linewidth=tack_linewidth, color=color,
                    label=p_label, markerfacecolor=color, transform=crs.PlateCarree())
        valid_mask = ~(np.isnan(lon_values) | np.isnan(lat_values))
        if np.any(valid_mask):
            valid_lons = lon_values[valid_mask]
            valid_lats = lat_values[valid_mask]
            ax.plot(valid_lons[0], valid_lats[0], marker='^', markersize=triangle_size, color=color,
                    markerfacecolor=color, markeredgecolor=color, linestyle='None', zorder=5, transform=crs.PlateCarree())
            ax.plot(valid_lons[-1], valid_lats[-1], marker='v', markersize=triangle_size, color=color,
                    markerfacecolor=color, markeredgecolor=color, linestyle='None', zorder=5, transform=crs.PlateCarree())
        plotted_count += 1
        if show_labels:
            for i, txt in enumerate(time_values):
                ax.text(lon_values[i], lat_values[i], str(txt), color=label_color, fontsize=label_fontsize, ha='right', va='bottom',
                        transform=crs.PlateCarree())
    if plotted_count <= 28 and not hidden_legend:
        ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.09), fontsize=legend_fontsize, ncol=7, frameon=True)
    return fig, ax

def convert_to_decimal_from_string(coord_string):
    direction_multiplier = 1
    if coord_string.endswith('S') or coord_string.endswith('W'):
        direction_multiplier = -1
    parts = coord_string.lstrip('+-').rstrip('NSWE').split('˚')
    degrees = float(parts[0])
    parts = parts[1].split('"')
    minutes = float(parts[0])
    seconds_and_centiseconds = parts[1].split('.')
    seconds = float(seconds_and_centiseconds[0])
    centiseconds = float(seconds_and_centiseconds[1]) if len(seconds_and_centiseconds) > 1 else 0
    decimal_degrees = degrees + minutes / 60.0 + seconds / 3600.0 + centiseconds / 360000.0
    decimal_degrees *= direction_multiplier
    return decimal_degrees

def read_object_data(file_path):
    objects = []
    with open(file_path, 'r') as file:
        for line in file:
            data = line.strip().split(',')
            object_type = data[0].lower()
            for i in range(1, len(data)):
                if '˚' in data[i]:
                    data[i] = convert_to_decimal_from_string(data[i])
            if object_type == 'circle':
                obj = {'type': 'circle', 'lon': float(data[1]), 'lat': float(data[2]), 'radius': float(data[3]), 'color': data[4]}
            elif object_type == 'fcircle':
                obj = {'type': 'fcircle', 'lon': float(data[1]), 'lat': float(data[2]), 'radius': float(data[3]), 'color': data[4]}
            elif object_type == 'tcircle':
                obj = {'type': 'tcircle', 'lon': float(data[1]), 'lat': float(data[2]), 'radius': float(data[3]), 'color': data[4]}
            elif object_type == 'rectangle':
                obj = {'type': 'rectangle', 'lon1': float(data[1]), 'lat1': float(data[2]),
                       'lon2': float(data[3]), 'lat2': float(data[4]), 'color': data[5]}
            elif object_type == 'frectangle':
                obj = {'type': 'frectangle', 'lon1': float(data[1]), 'lat1': float(data[2]),
                       'lon2': float(data[3]), 'lat2': float(data[4]), 'color': data[5]}
            elif object_type == 'trectangle':
                obj = {'type': 'trectangle', 'lon1': float(data[1]), 'lat1': float(data[2]),
                       'lon2': float(data[3]), 'lat2': float(data[4]), 'color': data[5]}
            elif object_type == 'mark':
                obj = {'type': 'mark', 'lon': float(data[1]), 'lat': float(data[2]), 'shape': data[3], 'size': float(data[4]), 'color': data[5]}
            elif object_type == 'text':
                alignment = data[6] if len(data) > 6 else 'lt'
                obj = {'type': 'text', 'lon': float(data[1]), 'lat': float(data[2]),
                       'label': data[3], 'size': float(data[4]), 'color': data[5], 'alignment': alignment}
            else:
                print(f"Warning: Unknown object type '{object_type}'. Skipping line.")
                continue
            objects.append(obj)
    return objects

def plot_objects_on_map(ax, objects):
    for obj in objects:
        if obj['type'] == 'circle':
            circle = mpatches.Circle((obj['lon'], obj['lat']), obj['radius'], edgecolor=obj['color'],
                                     facecolor='none', transform=crs.PlateCarree())
            ax.add_patch(circle)
        elif obj['type'] == 'fcircle':
            circle = mpatches.Circle((obj['lon'], obj['lat']), obj['radius'], edgecolor=obj['color'],
                                     facecolor=obj['color'], alpha=1.0, transform=crs.PlateCarree())
            ax.add_patch(circle)
        elif obj['type'] == 'tcircle':
            circle = mpatches.Circle((obj['lon'], obj['lat']), obj['radius'], edgecolor='none',
                                     facecolor=obj['color'], alpha=0.3, transform=crs.PlateCarree())
            ax.add_patch(circle)
        elif obj['type'] == 'rectangle':
            rectangle = mpatches.Rectangle((obj['lon1'], obj['lat1']), obj['lon2'] - obj['lon1'],
                                           obj['lat2'] - obj['lat1'], edgecolor=obj['color'], facecolor='none',
                                           transform=crs.PlateCarree())
            ax.add_patch(rectangle)
        elif obj['type'] == 'frectangle':
            rectangle = mpatches.Rectangle((obj['lon1'], obj['lat1']), obj['lon2'] - obj['lon1'],
                                           obj['lat2'] - obj['lat1'], edgecolor=obj['color'], facecolor=obj['color'],
                                           alpha=1.0, transform=crs.PlateCarree())
            ax.add_patch(rectangle)
        elif obj['type'] == 'trectangle':
            rectangle = mpatches.Rectangle((obj['lon1'], obj['lat1']), obj['lon2'] - obj['lon1'],
                                           obj['lat2'] - obj['lat1'], edgecolor='none', facecolor=obj['color'],
                                           alpha=0.3, transform=crs.PlateCarree())
            ax.add_patch(rectangle)
        elif obj['type'] == 'mark':
            marker = Line2D([obj['lon']], [obj['lat']], marker=obj['shape'], markersize=obj['size'],
                            color=obj['color'], transform=crs.PlateCarree())
            ax.add_line(marker)
        elif obj['type'] == 'text':
            text_alignment_horizontal = {'l': 'left', 'c': 'center', 'r': 'right'}
            text_alignment_vertical = {'t': 'top', 'c': 'center', 'b': 'bottom'}
            ha = text_alignment_horizontal.get(obj['alignment'][0], 'left')
            va = text_alignment_vertical.get(obj['alignment'][1], 'top')
            ax.text(obj['lon'], obj['lat'], obj['label'],  color=obj['color'], fontsize=obj['size'],
                    ha=ha, va=va, transform=crs.PlateCarree())
        else:
            print(f"Warning: Unknown object type '{obj['type']}'. Skipping object.")

def save_plot(fig, filename, dpi=500):
    fig.savefig(filename, dpi=dpi, bbox_inches='tight')
    print(f'Figure saved as {filename}')

def save_plot_geotiff(fig, filename, lon_min, lat_max):
    temp_png = "temp.png"
    fig.savefig(temp_png, dpi=dpi, bbox_inches='tight')
    transform = from_origin(lon_min, lat_max, 1 / dpi, 1 / dpi)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=rasterio.errors.NotGeoreferencedWarning)
            with rasterio.open(temp_png) as src:
                with rasterio.open(filename, 'w', driver='GTiff', width=src.width, height=src.height,
                                   count=3, dtype='uint8', crs='+proj=latlong', transform=transform) as dst:
                    dst.write(src.read([1, 2, 3]))
        print(f'GeoTIFF saved as {filename}')
    finally:
        if os.path.exists(temp_png):
            os.remove(temp_png)

def _valid_particle_coords(lons, lats):
    valid_mask = ~(np.isnan(lons) | np.isnan(lats))
    return list(zip(lons[valid_mask], lats[valid_mask]))

def save_plot_shapefile(fig, filename, trajectories):
    if track_lines:
        geometry = [
            LineString(coords)
            for lon, lat in zip(trajectories[:, :, 0], trajectories[:, :, 1])
            if len(coords := _valid_particle_coords(lon, lat)) >= 2
        ]
    else:
        coords = _valid_particle_coords(trajectories[:, :, 0].flatten(), trajectories[:, :, 1].flatten())
        geometry = [Point(lon, lat) for lon, lat in coords]
    gdf = gpd.GeoDataFrame(geometry=geometry, crs='+proj=latlong')
    gdf.to_file(filename)
    print(f'Shapefile saved as {filename}')

def save_plot_shapefile_multilayers(fig, base_filename, trajectories):
    for particle_number in range(trajectories.shape[0]):
        coords = _valid_particle_coords(trajectories[particle_number, :, 0], trajectories[particle_number, :, 1])
        if track_lines:
            if len(coords) < 2:
                continue
            geometry = [LineString(coords)]
        else:
            geometry = [Point(lon, lat) for lon, lat in coords]
        gdf = gpd.GeoDataFrame(geometry=geometry, crs='+proj=latlong')
        filename = f"{remove_file_extension(base_filename)}_particle_{particle_number}.shp"
        gdf.to_file(filename)
        print(f'Shapefile for Particle {particle_number} saved as {filename}')

def save_plot_based_on_extension(fig, trajectories):
    extension = particle_map_file.split('.')[-1].lower()
    if extension in ['png', 'tiff', 'jpeg', 'pdf']:
        save_plot(fig, output_directory + particle_map_file, dpi=dpi)
    elif extension == 'geotiff':
        save_plot_geotiff(fig, output_directory + particle_map_file, study_region[0], study_region[3])
    elif extension == 'shp':
        if activate_multilayer_shapefile:
            save_plot_shapefile_multilayers(fig, output_directory + particle_map_file, trajectories)
        else:
            save_plot_shapefile(fig, output_directory + particle_map_file, trajectories)
    else:
        print(f"Error: Unrecognized extension to save frame: {extension}")

def _compute_seawater_properties_gsw(lon_arr, lat_arr, temp_arr, salt_arr, transport_arr):
    sa = gsw.SA_from_SP(salt_arr, 0.0, lon_arr, lat_arr)
    ct = gsw.CT_from_t(sa, temp_arr, 0.0)
    surface_density = gsw.rho(sa, ct, 0.0)
    heat_capacity = gsw.cp_t_exact(sa, temp_arr, 0.0)
    heat_transport = surface_density * heat_capacity * temp_arr * transport_arr
    salt_transport = surface_density * (sa * 1e-3) * transport_arr
    return heat_capacity, surface_density, heat_transport, salt_transport

def _compute_cumulative_distance_m(lon_arr, lat_arr):
    num_particles, num_steps = lon_arr.shape
    cum_dist = np.full((num_particles, num_steps), np.nan, dtype=np.float64)
    valid_start = np.isfinite(lon_arr[:, 0]) & np.isfinite(lat_arr[:, 0])
    cum_dist[valid_start, 0] = 0.0
    if num_steps > 1:
        lon_rad = np.radians(lon_arr)
        lat_rad = np.radians(lat_arr)
        dlon = lon_rad[:, 1:] - lon_rad[:, :-1]
        dlat = lat_rad[:, 1:] - lat_rad[:, :-1]
        a = np.sin(dlat * 0.5) ** 2 + np.cos(lat_rad[:, :-1]) * np.cos(lat_rad[:, 1:]) * np.sin(dlon * 0.5) ** 2
        step_dist = 2.0 * 6371000.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
        for t in range(1, num_steps):
            valid_step = np.isfinite(step_dist[:, t - 1]) & np.isfinite(cum_dist[:, t - 1])
            cum_dist[valid_step, t] = cum_dist[valid_step, t - 1] + step_dist[valid_step, t - 1]
    return cum_dist

def save_to_netcdf(file_path, trajectories):
    num_particles, num_steps, _ = trajectories.shape
    with nc.Dataset(file_path, 'w', format='NETCDF4') as ncfile:
        ncfile.createDimension('num_particles', num_particles)
        ncfile.createDimension('num_steps', num_steps)
        particle_var = ncfile.createVariable('particle', 'i4', ('num_particles',))
        time_var = ncfile.createVariable('time', 'i4', ('num_steps',))
        time_days_var = ncfile.createVariable('time_days', 'f8', ('num_steps',))
        time_days_var.long_name = 'Elapsed simulation time in days and fractions of days'
        time_days_var.units = 'days'
        lon_var = ncfile.createVariable('lon', 'f8', ('num_particles', 'num_steps'))
        lat_var = ncfile.createVariable('lat', 'f8', ('num_particles', 'num_steps'))
        cum_dist_var = ncfile.createVariable('cumulative_distance', 'f8', ('num_particles', 'num_steps'))
        cum_dist_var.long_name = 'Cumulative distance traveled from release'
        cum_dist_var.units = 'm'
        curr_spd_var = ncfile.createVariable('current_speed', 'f8', ('num_particles', 'num_steps'))
        curr_spd_var.long_name = 'Ocean current speed'
        curr_spd_var.units = 'm s-1'
        wind_spd_var = ncfile.createVariable('wind_speed', 'f8', ('num_particles', 'num_steps'))
        wind_spd_var.long_name = 'Wind speed'
        wind_spd_var.units = 'm s-1'
        dt_sec = float(globals().get("dt_seconds", globals().get("time_step", 1.0)))
        particle_var[:] = range(num_particles)
        time_var[:] = range(num_steps)
        time_days_var[:] = np.arange(num_steps, dtype=np.float64) * (dt_sec / 86400.0)
        lon_var[:, :] = trajectories[:, :, 0]
        lat_var[:, :] = trajectories[:, :, 1]
        cum_dist_var[:, :] = _compute_cumulative_distance_m(trajectories[:, :, 0], trajectories[:, :, 1])
        curr_spd_var[:, :] = trajectories[:, :, 5] if trajectories.shape[2] > 5 else np.nan
        wind_spd_var[:, :] = trajectories[:, :, 6] if trajectories.shape[2] > 6 else np.nan
        if compute_transport:
            transport_var = ncfile.createVariable('transport', 'f8', ('num_particles', 'num_steps'))
            transport_var[:, :] = trajectories[:, :, 2]
        if seawater_properties and bool(seawater_properties_file):
            temp_arr = trajectories[:, :, 3]
            salt_arr = trajectories[:, :, 4]
            temp_var = ncfile.createVariable('temp', 'f8', ('num_particles', 'num_steps'))
            temp_var[:, :] = temp_arr
            salt_var = ncfile.createVariable('salt', 'f8', ('num_particles', 'num_steps'))
            salt_var[:, :] = salt_arr
            heat_capacity, surface_density, heat_transport, salt_transport = _compute_seawater_properties_gsw(
                trajectories[:, :, 0], trajectories[:, :, 1], temp_arr, salt_arr, trajectories[:, :, 2]
            )
            cp_var = ncfile.createVariable('heat_capacity', 'f8', ('num_particles', 'num_steps'))
            cp_var.long_name = 'Surface seawater specific heat capacity (TEOS-10)'
            cp_var.units = 'J kg-1 K-1'
            cp_var[:, :] = heat_capacity
            rho_var = ncfile.createVariable('surface_density', 'f8', ('num_particles', 'num_steps'))
            rho_var.long_name = 'Surface seawater density at p=0 dbar (TEOS-10)'
            rho_var.units = 'kg m-3'
            rho_var[:, :] = surface_density
            ht_var = ncfile.createVariable('heat_transport', 'f8', ('num_particles', 'num_steps'))
            ht_var.long_name = 'Surface seawater heat transport'
            ht_var.units = 'W'
            ht_var[:, :] = heat_transport
            st_var = ncfile.createVariable('salt_transport', 'f8', ('num_particles', 'num_steps'))
            st_var.long_name = 'Surface seawater salt transport'
            st_var.units = 'kg s-1'
            st_var[:, :] = salt_transport
    print(f'NetCDF file saved in: {file_path}')

def is_point_inside_polygon(lon, lat, polygon):
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        if ((polygon[i][1] > lat) != (polygon[j][1] > lat)) and \
           (lon < (polygon[j][0] - polygon[i][0]) * (lat - polygon[i][1]) / (polygon[j][1] - polygon[i][1]) + polygon[i][0]):
            inside = not inside
        j = i
    return inside

def read_configuration(config_file):
    try:
        with open(config_file, 'r') as file:
            configuration = json.load(file)
        return configuration
    except FileNotFoundError:
        print(f"Configuration file '{config_file}' not found.")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding configuration file '{config_file}': {e}")
        return None

def get_config_param(json_data, config_key, default=None, warn=True):
    try:
        claves = config_key.split('->')
        valor = json_data
        for k in claves:
            valor = valor[k]
        return valor
    except (KeyError, TypeError):
        if warn:
            print(f'Key "{config_key}" does not exist in the model configuration file.')
        return default

def print_pathways(trajectories):
    num_particles, num_steps, _ = trajectories.shape
    for i_part in range(num_particles):
        data = []
        for i_step in range(num_steps):
            lon, lat, transport, temp, salt = trajectories[i_part, i_step, :5]
            if compute_transport and seawater_properties:
                headers = ["Step", "Lon", "Lat", "Transport", "Temp", "Salt"]
                data.append([f"{i_step}", f"{lon:.4f}", f"{lat:.4f}", f"{transport:.2f}", f"{temp:.1f}", f"{salt:.1f}"])
            elif compute_transport:
                headers = ["Step", "Lon", "Lat", "Transport"]
                data.append([f"{i_step}", f"{lon:.4f}", f"{lat:.4f}", f"{transport:.2f}"])
            elif seawater_properties:
                headers = ["Step", "Lon", "Lat", "Temp", "Salt"]
                data.append([f"{i_step}", f"{lon:.4f}", f"{lat:.4f}", f"{temp:.1f}", f"{salt:.1f}"])
            else:
                headers = ["Step", "Lon", "Lat"]
                data.append([f"{i_step}", f"{lon:.4f}", f"{lat:.4f}"])
        table_title = f"Particle {i_part + 1}"
        print(table_title)
        print(tabulate(data, headers=headers, tablefmt="grid", numalign="right"))
        print("\n")

def load_config_file(configuration):
    global model_name, model_description, model_type, verbose, interpolation_method, auxiliary_interpolation_method
    global input_directory, hydrodynamic_file, htd_paramlist, swp_paramlist, wind_file, wind_paramlist, \
        stokes_file, stokes_paramlist, particles_file, active_particles, coast_file, objects_files, seawater_properties_file
    global invert_vector_fields, compute_transport, seawater_properties, horizdiff, currcoef, windwavecoef, \
        windwavecoef_automatic, leeway_angle, plastic_density, biofouling_rate, larvae_u_active, larvae_v_active, \
        larvae_pld, larvae_mortality_rate, sargassum_biomass_init, sargassum_growth_rate, \
        sargassum_mortality_rate, ice_volume_init, ice_u_grad, ice_v_grad, ice_coriolis_coef, \
        ice_ablation_basal, ice_ablation_lateral, ice_ablation_thermal, debris_windage, stokes_wind_coef, \
        decay_rate, decay_min_threshold, residence_bbox, okubo_ref_length, \
        subsurface_depth_init, subsurface_settling_rate, subsurface_max_depth, random_term, rt_method
    global start_time, stop_time, time_step
    global C1, C2
    global time_interval_filter, time_range
    global output_directory, track_file, report_file, activate_multilayer_shapefile, particle_map_file
    global study_region, dpi, particles_to_show, plot_objects, track_lines, show_particle_label, label_color, \
        label_fontsize, tack_linewidth, track_linestyle, track_colortable, triangle_size, legend_position, \
        legend_fontsize, legend_numcol, hidden_legend

    model_name = get_config_param(configuration, 'General->model_name')
    model_description = get_config_param(configuration, 'General->description')
    model_type = get_config_param(configuration, 'General->model_type')
    verbose = get_config_param(configuration, 'General->verbose')

    input_directory = get_config_param(configuration, 'Inputs->input_directory')
    hydrodynamic_file = get_config_param(configuration, 'Inputs->hydrodynamic_file')
    htd_paramlist = get_config_param(configuration, 'Inputs->htd_paramlist')
    seawater_properties_file = get_config_param(configuration, 'Inputs->seawater_properties_file')
    swp_paramlist = get_config_param(configuration, 'Inputs->swp_paramlist')
    wind_file = get_config_param(configuration, 'Inputs->wind_file')
    wind_paramlist = get_config_param(configuration, 'Inputs->wind_paramlist')
    stokes_file = get_config_param(configuration, 'Inputs->stokes_file', default="", warn=False)
    stokes_paramlist = get_config_param(configuration, 'Inputs->stokes_paramlist', default=[], warn=False)
    particles_file = get_config_param(configuration, 'Inputs->particles_file')
    active_particles = get_config_param(configuration, 'Inputs->active_particles')
    coast_file = get_config_param(configuration, 'Inputs->coast_file')
    objects_files = get_config_param(configuration, 'Inputs->objects_files')

    interpolation_method = get_config_param(configuration, 'Numerical_methods->interpolation_method')
    auxiliary_interpolation_method = get_config_param(configuration,
                                                      'Numerical_methods->auxiliary_interpolation_method')

    invert_vector_fields = bool(get_config_param(configuration, 'Physics->invert_vector_fields'))
    compute_transport = bool(get_config_param(configuration, 'Physics->compute_transport'))
    seawater_properties = bool(get_config_param(configuration, 'Physics->seawater_properties'))
    horizdiff = get_config_param(configuration, 'Physics->horizdiff')
    currcoef = get_config_param(configuration, 'Physics->currcoef')
    windwavecoef = get_config_param(configuration, 'Physics->windwavecoef')
    windwavecoef_automatic = bool(get_config_param(configuration, 'Physics->windwavecoef_automatic', default=0, warn=False))
    leeway_angle = get_config_param(configuration, 'Physics->leeway_angle', default=0.0, warn=False)
    plastic_density = get_config_param(configuration, 'Physics->plastic_density', default=920.0, warn=False)
    biofouling_rate = get_config_param(configuration, 'Physics->biofouling_rate', default=0.0, warn=False)
    larvae_u_active = get_config_param(configuration, 'Physics->larvae_u_active', default=0.0, warn=False)
    larvae_v_active = get_config_param(configuration, 'Physics->larvae_v_active', default=0.0, warn=False)
    larvae_pld = get_config_param(configuration, 'Physics->larvae_pld', default=1e9, warn=False)
    larvae_mortality_rate = get_config_param(configuration, 'Physics->larvae_mortality_rate', default=0.0, warn=False)
    sargassum_biomass_init = get_config_param(configuration, 'Physics->sargassum_biomass_init', default=1.0, warn=False)
    sargassum_growth_rate = get_config_param(configuration, 'Physics->sargassum_growth_rate', default=0.0, warn=False)
    sargassum_mortality_rate = get_config_param(configuration, 'Physics->sargassum_mortality_rate', default=0.0, warn=False)
    ice_volume_init = get_config_param(configuration, 'Physics->ice_volume_init', default=1e6, warn=False)
    ice_u_grad = get_config_param(configuration, 'Physics->ice_u_grad', default=0.0, warn=False)
    ice_v_grad = get_config_param(configuration, 'Physics->ice_v_grad', default=0.0, warn=False)
    ice_coriolis_coef = get_config_param(configuration, 'Physics->ice_coriolis_coef', default=1.0, warn=False)
    ice_ablation_basal = get_config_param(configuration, 'Physics->ice_ablation_basal', default=0.0, warn=False)
    ice_ablation_lateral = get_config_param(configuration, 'Physics->ice_ablation_lateral', default=0.0, warn=False)
    ice_ablation_thermal = get_config_param(configuration, 'Physics->ice_ablation_thermal', default=0.0, warn=False)
    debris_windage = get_config_param(configuration, 'Physics->debris_windage', default=None, warn=False)
    stokes_wind_coef = get_config_param(configuration, 'Physics->stokes_wind_coef', default=0.015, warn=False)
    decay_rate = get_config_param(configuration, 'Physics->decay_rate', default=0.0, warn=False)
    decay_min_threshold = get_config_param(configuration, 'Physics->decay_min_threshold', default=0.01, warn=False)
    residence_bbox = get_config_param(configuration, 'Physics->residence_bbox', default=None, warn=False)
    okubo_ref_length = get_config_param(configuration, 'Physics->okubo_ref_length', default=1000.0, warn=False)
    subsurface_depth_init = get_config_param(configuration, 'Physics->subsurface_depth_init', default=10.0, warn=False)
    subsurface_settling_rate = get_config_param(configuration, 'Physics->subsurface_settling_rate', default=0.0, warn=False)
    subsurface_max_depth = get_config_param(configuration, 'Physics->subsurface_max_depth', default=100.0, warn=False)
    random_term = bool(get_config_param(configuration, 'Physics->random_term'))
    rt_method = get_config_param(configuration, 'Physics->rt_method')

    start_time_val = get_config_param(configuration, 'Parameters->start_time')
    stop_time_val = get_config_param(configuration, 'Parameters->stop_time')
    time_step_val = get_config_param(configuration, 'Parameters->time_step')
    if start_time_val is None or stop_time_val is None or time_step_val is None:
        print("Missing required simulation time parameters in configuration file.")
        sys.exit(1)
    start_time = int(start_time_val)
    stop_time = int(stop_time_val)
    time_step = int(time_step_val)

    C1 = get_config_param(configuration, 'Coefficients->C1')
    C2 = get_config_param(configuration, 'Coefficients->C2')

    output_directory = get_config_param(configuration, 'Outputs->output_directory')
    track_file = get_config_param(configuration, 'Outputs->track_file')
    report_file = get_config_param(configuration, 'Outputs->report_file')
    activate_multilayer_shapefile = bool(get_config_param(configuration, 'Outputs->activate_multilayer_shapefile'))
    particle_map_file = get_config_param(configuration, 'Outputs->particle_map_file')

    time_interval_filter = bool(get_config_param(configuration, 'Analysis->time_interval_filter'))
    time_range = get_config_param(configuration, 'Analysis->time_range')

    study_region = get_config_param(configuration, 'Plots->study_region')
    dpi = get_config_param(configuration, 'Plots->dpi')
    particles_to_show = get_config_param(configuration, 'Plots->particles_to_show')
    plot_objects = bool(get_config_param(configuration, 'Plots->plot_objects'))
    track_lines = bool(get_config_param(configuration, 'Plots->track_lines'))
    show_particle_label = bool(get_config_param(configuration, 'Plots->show_particle_label'))
    label_color = get_config_param(configuration, 'Plots->label_color')
    label_fontsize = get_config_param(configuration, 'Plots->label_fontsize')
    tack_linewidth = get_config_param(configuration, 'Plots->tack_linewidth')
    track_linestyle = get_config_param(configuration, 'Plots->track_linestyle')
    track_colortable = get_config_param(configuration, 'Plots->track_colortable')
    triangle_size = float(get_config_param(configuration, 'Plots->triangle_size', default=3.0, warn=False))
    legend_position = get_config_param(configuration, 'Plots->legend_position')
    legend_fontsize = get_config_param(configuration, 'Plots->legend_fontsize')
    legend_numcol = get_config_param(configuration, 'Plots->legend_numcol')
    hidden_legend = bool(get_config_param(configuration, 'Plots->hidden_legend'))

def print_config_logs():
    if 0 < verbose <= 2:
        print("General:\n---")
        print(f'Model name: {model_name}')
        print(f'Model description: {model_description}')
        print(f'Model type: {model_type}\n')

        print("Inputs:\n---")
        print(f'Input directory: {input_directory}')
        print(f'Hydrodynamic file: {hydrodynamic_file}')
        print(f'Hydrodynamic parameters: {htd_paramlist}')
        print(f'Seawater parameters: {swp_paramlist}')
        print(f'Wind file: {wind_file}')
        print(f'Wind parameters: {wind_paramlist}')
        print(f'Particle file: {particles_file}')
        print(f'Active particles: {active_particles}')
        print(f'Coast file: {coast_file}\n')

        print("Numerical methods:\n---")
        print(f'Interpolation method: {interpolation_method}')
        print(f'Interpolation method: {auxiliary_interpolation_method}\n')

        print("Physics:\n---")
        print(f'Invert vector fields: {invert_vector_fields}')
        print(f'Compute transport: {compute_transport}')
        print(f'Seawater properties: {seawater_properties}')
        print(f'Horizontal diffusion coefficient: {horizdiff}')
        print(f'Current coefficient: {currcoef}')
        print(f'Wind wave coefficient: {windwavecoef}')
        print(f'Wind wave coefficient automatic: {windwavecoef_automatic}')
        print(f'Random term: {random_term}')
        print(f'Random term method: {rt_method}\n')

        print("Parameters:\n---")
        print(f'Start time: {start_time}')
        print(f'Stop time: {stop_time}')
        print(f'Time step: {time_step}\n')

        print("Coefficients:\n---")
        print(f'C1: {C1}')
        print(f'C2: {C2}\n')

        print("Outputs:\n---")
        print(f'Output directory: {output_directory}')
        print(f'Track file: {track_file}')
        print(f'Report file: {report_file}')
        print(f'Particle map file: {particle_map_file}\n')

def file_exists(filename):
    file_found = os.path.isfile(filename)
    if file_found:
        print(f"File {filename} exists.")
    else:
        print(f"File {filename} does not exist.")
    return file_found

def _dispatch_model():
    if model_type == "FOCURR":
        return compute_free_ocurr(lon, lat, u, v, particles)
    elif model_type == "CURWIND":
        return compute_curwind(lon, lat, u, v, uwind, vwind, particles, wind_lon=wind_lon, wind_lat=wind_lat)
    elif model_type == "GNOME":
        return compute_gnome(lon, lat, u, v, uwind, vwind, particles, wind_lon=wind_lon, wind_lat=wind_lat)
    elif model_type == "OPENDRIFT":
        return compute_opendrift(
            lon, lat, u, v, uwind, vwind, particles, wind_lon=wind_lon, wind_lat=wind_lat,
            ustokes=ustokes, vstokes=vstokes, stokes_lon=stokes_lon, stokes_lat=stokes_lat
        )
    elif model_type == "MEDSLIK2":
        return compute_medslik2(
            lon, lat, u, v, uwind, vwind, particles, wind_lon=wind_lon, wind_lat=wind_lat,
            ustokes=ustokes, vstokes=vstokes, stokes_lon=stokes_lon, stokes_lat=stokes_lat
        )
    elif model_type == "OSCAR":
        return compute_oscar(lon, lat, u, v, uwind, vwind, particles, wind_lon=wind_lon, wind_lat=wind_lat)
    elif model_type == "uPLASTIC":
        return compute_uplastic(
            lon, lat, u, v, uwind, vwind, particles, wind_lon=wind_lon, wind_lat=wind_lat,
            ustokes=ustokes, vstokes=vstokes, stokes_lon=stokes_lon, stokes_lat=stokes_lat
        )
    elif model_type == "LARVAE":
        return compute_larvae(
            lon, lat, u, v, particles,
            ustokes=ustokes, vstokes=vstokes, stokes_lon=stokes_lon, stokes_lat=stokes_lat
        )
    elif model_type == "LEEWAY":
        return compute_leeway(lon, lat, u, v, uwind, vwind, particles, wind_lon=wind_lon, wind_lat=wind_lat)
    elif model_type == "SARGASSUM":
        return compute_sargassum(
            lon, lat, u, v, uwind, vwind, particles, wind_lon=wind_lon, wind_lat=wind_lat,
            ustokes=ustokes, vstokes=vstokes, stokes_lon=stokes_lon, stokes_lat=stokes_lat
        )
    elif model_type == "ICEFLOES":
        return compute_icefloes(lon, lat, u, v, uwind, vwind, particles, wind_lon=wind_lon, wind_lat=wind_lat)
    elif model_type == "DEBRIS":
        return compute_debris(
            lon, lat, u, v, uwind, vwind, particles, wind_lon=wind_lon, wind_lat=wind_lat,
            ustokes=ustokes, vstokes=vstokes, stokes_lon=stokes_lon, stokes_lat=stokes_lat
        )
    elif model_type == "FOCURR_RK2":
        return compute_focurr_rk2(lon, lat, u, v, particles)
    elif model_type == "FOCURR_RK4":
        return compute_focurr_rk4(lon, lat, u, v, particles)
    elif model_type == "DECAY_TRACER":
        return compute_decay_tracer(lon, lat, u, v, particles)
    elif model_type == "RESIDENCE_TIME":
        return compute_residence_time(lon, lat, u, v, particles)
    elif model_type == "OKUBO":
        return compute_okubo(lon, lat, u, v, particles)
    elif model_type == "SUBSURFACE":
        return compute_subsurface(lon, lat, u, v, particles)
    return None

def _format_hms(seconds):
    total_sec = int(round(max(0.0, seconds)))
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def _format_days_hours(seconds):
    total_hours = int(round(max(0.0, seconds) / 3600.0))
    days = total_hours // 24
    hours = total_hours % 24
    return f"{days:02d}:{hours:02d}"

def _print_timing_summary(trajectories, run_start_perf):
    elapsed_wall = perf_counter() - run_start_perf
    dt_sec = float(globals().get("dt_seconds", time_step))
    exec_times = globals().get("particle_exec_times", [0.0] * trajectories.shape[0])
    parts_list = globals().get("particles", [])
    travel_secs = []
    rows = []
    headers = ["Particle", "Run Time (hh:mm:ss)", "Travel Time (h)", "Travel Time (days:hours)"]
    table = PrettyTable(headers)
    table.align["Particle"] = "l"
    table.align["Run Time (hh:mm:ss)"] = "r"
    table.align["Travel Time (h)"] = "r"
    table.align["Travel Time (days:hours)"] = "r"
    for i_part in range(trajectories.shape[0]):
        valid_count = int(np.sum(~np.isnan(trajectories[i_part, :, 0])))
        p_name = parts_list[i_part][0] if i_part < len(parts_list) else f"P{i_part + 1}"
        p_wall = exec_times[i_part] if i_part < len(exec_times) else 0.0
        t_sec = max(0, valid_count - 1) * dt_sec if valid_count > 0 else 0.0
        if valid_count > 0:
            travel_secs.append(t_sec)
        t_hours = t_sec / 3600.0
        row = [p_name, _format_hms(p_wall), f"{t_hours:.2f}", _format_days_hours(t_sec)]
        rows.append(row)
        table.add_row(row)

    summary_csv = output_directory + remove_file_extension(track_file) + "_summary.csv"
    with open(summary_csv, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)
        writer.writerows(rows)

    mean_travel = float(np.mean(travel_secs)) if travel_secs else 0.0
    print("\nParticle Execution and Travel Time Summary:")
    print(table.get_string(border=True, hrules=False))
    print(f"Summary CSV saved in: {summary_csv}")
    print(f"\nComputer execution time: {_format_hms(elapsed_wall)} ({elapsed_wall:.4f} s)")
    print(f"Mean particle travel time: {mean_travel / 3600.0:.2f} h ({_format_days_hours(mean_travel)} days:hours)\n")

def run_models():
    global pathways, tackcolors
    print(f"\nRunning model {model_type}...\n\n")
    pathways = _dispatch_model()
    if pathways is None:
        print(f"Model {model_type} is not implemented.\nList of implemented models: FOCURR, CURWIND, GNOME, OPENDRIFT, MEDSLIK2, OSCAR, uPLASTIC, LARVAE, LEEWAY, SARGASSUM, ICEFLOES, DEBRIS.\n")
        return False
    print(f"\nModel {model_type} run completed\n")
    totalfreememory, memoryunit = get_freememory()
    print(f"Free memory: {totalfreememory:.2f} {memoryunit}\n")
    save_to_netcdf(output_directory + track_file, pathways)
    save_report(pathways)
    tackcolors = read_colortable()
    fig, ax = plot_pathway(study_region[0], study_region[1], study_region[2], study_region[3], pathways,
                           particle_numbers=particles_to_show, show_labels=show_particle_label)
    if plot_objects:
        if file_exists(input_directory + objects_files):
            objects_list = read_object_data(input_directory + objects_files)
            plot_objects_on_map(ax, objects_list)
    save_plot_based_on_extension(fig, pathways)
    if verbose == 2:
        print_pathways(pathways)
    return True

def run_test():
    global pathways, tackcolors
    pathways = _dispatch_model()
    if pathways is None:
        print(f"Model {model_type} is not implemented.\nList of implemented models: FOCURR, CURWIND, GNOME, OPENDRIFT, MEDSLIK2, OSCAR, uPLASTIC, LARVAE, LEEWAY, SARGASSUM, ICEFLOES, DEBRIS.\n")
        return
    print(f"Model {model_type} run completed\n")
    cpu_temperature = get_cpu_temperature()
    if cpu_temperature is not None:
        print(f"The processor temperature is: {cpu_temperature} °C\n")
    save_to_netcdf(output_directory + track_file, pathways)
    save_report(pathways)
    tackcolors = read_colortable()
    fig, ax = plot_pathway(study_region[0], study_region[1], study_region[2], study_region[3], pathways,
                           particle_numbers=particles_to_show, show_labels=show_particle_label)
    if plot_objects:
        if file_exists(input_directory + objects_files):
            objects_list = read_object_data(input_directory + objects_files)
            plot_objects_on_map(ax, objects_list)
    save_plot_based_on_extension(fig, pathways)
    if verbose == 2:
        print_pathways(pathways)

def load_trajectories_from_netcdf(file_path):
    with nc.Dataset(file_path, 'r') as netcdf_file:
        num_particles = netcdf_file.dimensions['num_particles'].size
        num_steps = netcdf_file.dimensions['num_steps'].size
        particles = netcdf_file.variables['particle'][:]
        times = netcdf_file.variables['time'][:]
        lons = netcdf_file.variables['lon'][:, :]
        lats = netcdf_file.variables['lat'][:, :]
        trajectories = np.empty((num_particles, num_steps, 2))
        trajectories[:] = np.nan
        for i_part in range(num_particles):
            trajectories[i_part, :, 0] = lons[i_part, :]
            trajectories[i_part, :, 1] = lats[i_part, :]
    return trajectories

def remove_file_extension(filename):
    if "." in filename:
        name_parts = filename.rsplit(".", 1)
        return name_parts[0]
    else:
        return filename

def set_time_interval_filter(trajectories, initt, finalt):
    return trajectories[:, initt:finalt, :]

def view_results():
    global tackcolors
    if file_exists(output_directory + track_file):
        pathways = load_trajectories_from_netcdf(output_directory + track_file)
        if time_interval_filter:
            pathways = set_time_interval_filter(pathways, time_range[0], time_range[1])
        tackcolors = read_colortable()
        fig, ax = plot_pathway(study_region[0], study_region[1], study_region[2], study_region[3], pathways,
                           particle_numbers=particles_to_show, show_labels=show_particle_label)
        if plot_objects:
            if file_exists(input_directory + objects_files):
                objects_list = read_object_data(input_directory + objects_files)
                plot_objects_on_map(ax, objects_list)
        save_plot_based_on_extension(fig, pathways)
        plt.show()
    else:
        print(f"Particle file {track_file} not found")

def prepare_run():
    global lon, lat, time, u, v, time_units, deltalon, deltalat, particles
    global temp, salt, uwind, vwind, wind_lon, wind_lat, ustokes, vstokes, stokes_lon, stokes_lat
    global start_time, stop_time, time_step, dt_seconds
    uwind, vwind, wind_lon, wind_lat = None, None, None, None
    ustokes, vstokes, stokes_lon, stokes_lat = None, None, None, None
    needs_wind = model_type in ("CURWIND", "GNOME", "OPENDRIFT", "MEDSLIK2", "OSCAR", "uPLASTIC", "LEEWAY", "SARGASSUM", "ICEFLOES", "DEBRIS")
    needs_stokes = model_type in ("OPENDRIFT", "MEDSLIK2", "uPLASTIC", "LARVAE", "SARGASSUM", "DEBRIS") and bool(stokes_file)
    if file_exists(input_directory + hydrodynamic_file):
        totalfreememory, memoryunit = get_freememory()
        print(f"Initial free memory: {totalfreememory:.2f} {memoryunit}\n")

        lon, lat, time, u, v, time_units, deltalon, deltalat = (
            load_hydrodynamic_data(input_directory + hydrodynamic_file, htd_paramlist))
        if seawater_properties:
            if file_exists(input_directory + seawater_properties_file):
                temp, salt = load_sw_data(input_directory + seawater_properties_file, swp_paramlist)
            else:
                print("Error: seawater properties file not found.")
                sys.exit(1)
        if needs_wind:
            if wind_file and file_exists(input_directory + wind_file):
                uwind, vwind, wind_lon, wind_lat = load_wind_data(input_directory + wind_file, wind_paramlist)
            else:
                print(f"Error: wind file not found for {model_type} model.")
                sys.exit(1)
        if needs_stokes:
            if file_exists(input_directory + stokes_file):
                ustokes, vstokes, stokes_lon, stokes_lat = load_wind_data(input_directory + stokes_file, stokes_paramlist)
            else:
                print(f"Error: Stokes drift file not found for {model_type} model.")
                sys.exit(1)

        totalfreememory, memoryunit = get_freememory()
        print(f"Initial free memory: {totalfreememory:.2f} {memoryunit}\n")

        if invert_vector_fields:
            u, v = select_simulation_data(u, v, stop_time, start_time, time_step)
            u = u * -1
            v = v * -1
            if seawater_properties:
                temp, salt = select_simulation_data(temp, salt, stop_time, start_time, time_step)
            if needs_wind:
                uwind, vwind = select_simulation_data(uwind, vwind, stop_time, start_time, time_step)
                uwind = uwind * -1
                vwind = vwind * -1
            if needs_stokes:
                ustokes, vstokes = select_simulation_data(ustokes, vstokes, stop_time, start_time, time_step)
                ustokes = ustokes * -1
                vstokes = vstokes * -1
        else:
            u, v = select_simulation_data(u, v, start_time, stop_time, time_step)
            if seawater_properties:
                temp, salt = select_simulation_data(temp, salt, start_time, stop_time, time_step)
            if needs_wind:
                uwind, vwind = select_simulation_data(uwind, vwind, start_time, stop_time, time_step)
            if needs_stokes:
                ustokes, vstokes = select_simulation_data(ustokes, vstokes, start_time, stop_time, time_step)

        totalfreememory, memoryunit = get_freememory()
        print(f"Initial free memory: {totalfreememory:.2f} {memoryunit}\n")

        dt_seconds = _compute_dt_seconds(time, time_units, time_step)
        start_time = 0
        stop_time = v.shape[0] - 1
        compute_region_limits(lon, lat)
    else:
        print("Error in model configuration.")
        sys.exit(1)

    if file_exists(input_directory + particles_file):
        particles = load_initial_positions(input_directory + particles_file)
        if 0 < verbose <= 2:
            print_particle_positions(particles)
    else:
        sys.exit(1)

def save_report(trajectories):
    return 0

def get_config(config_filename):
    configuration = read_configuration(config_filename)
    if configuration is not None:
        load_config_file(configuration)
        print_config_logs()
    else:
        print("Invalid configuration file\n")
        sys.exit(1)

if __name__ == "__main__":
    multiprocessing.freeze_support()

    if len(sys.argv) < 3:
        print("SPartA model v3.0 (parallel)\n")
        print("Usage:")
        print("python SPartA.py run <filename.conf>")
        print("or")
        print("Usage: python SPartA.py test <test number [1 or 2]>")
        print("or")
        print("python SPartA.py view <filename.conf>")
        sys.exit(1)

    command_run = sys.argv[1]
    config_filename = sys.argv[2]

    cpu_temperature = get_cpu_temperature()
    if cpu_temperature is not None:
        print(f"Initial processor temperature is: {cpu_temperature} °C\n")
    totalfreememory, memoryunit = get_freememory()
    print(f"Initial free memory: {totalfreememory:.2f} {memoryunit}\n")

    if command_run == "test":
        get_config(f"test{config_filename}.conf")
    else:
        get_config(config_filename)

    if command_run == "run":
        run_start_perf = perf_counter()
        prepare_run()
        if not run_models():
            sys.exit(1)
        _print_timing_summary(pathways, run_start_perf)
    elif command_run == "test":
        run_start_perf = perf_counter()
        prepare_run()
        run_test()
        _print_timing_summary(pathways, run_start_perf)
    elif command_run == "view":
        view_results()
    else:
        print("Invalid option. Use 'run' or 'view' or 'test' options.\n")
        sys.exit(1)

