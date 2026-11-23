import argparse
import datetime
import json
import os
import re
import sys

import netCDF4 as nc
import numpy as np

_DURATION_RE = re.compile(r"^(?:(?P<days>\d+)dys)?(?:(?P<hours>\d+)hrs)?$")

def parse_duration(duration_str):
    m = _DURATION_RE.match(duration_str.strip())
    if not m or (m.group("days") is None and m.group("hours") is None):
        raise ValueError(
            f"Invalid time_duration '{duration_str}'. Expected formats like "
            "'1hrs', '12hrs', '1dys', '7dys', '1dys12hrs', '2dys3hrs'."
        )
    days = int(m.group("days")) if m.group("days") is not None else 0
    hours = int(m.group("hours")) if m.group("hours") is not None else 0
    if hours > 23:
        raise ValueError(
            f"Invalid hours '{hours}hrs' in '{duration_str}': maximum is 23hrs "
            "(use days for >= 24 hours, e.g., '1dys')."
        )
    if days == 0 and hours == 0:
        raise ValueError("time_duration must be greater than zero.")
    return datetime.timedelta(days=days, hours=hours)

def _load_hydro_datetimes(conf):
    inputs = conf.get("Inputs", {})
    input_dir = inputs.get("input_directory", "")
    hydro_file = inputs.get("hydrodynamic_file", "")
    htd_params = inputs.get("htd_paramlist", [])
    if not hydro_file or len(htd_params) < 3:
        raise ValueError("Invalid Inputs->hydrodynamic_file or Inputs->htd_paramlist in .conf.")

    nc_path = os.path.join(input_dir, hydro_file) if input_dir else hydro_file
    if not os.path.isfile(nc_path):
        raise FileNotFoundError(f"Hydrodynamic NetCDF file not found: {nc_path}")

    t_var_name = htd_params[2]
    with nc.Dataset(nc_path, "r") as ds:
        if t_var_name not in ds.variables:
            raise KeyError(f"Time variable '{t_var_name}' not found in {nc_path}.")
        t_var = ds.variables[t_var_name]
        units = getattr(t_var, "units", None)
        if not units:
            raise ValueError(f"Time variable '{t_var_name}' in {nc_path} has no 'units' attribute.")
        calendar = getattr(t_var, "calendar", "standard")
        raw_time = np.ma.filled(t_var[:], np.nan)
        cftimes = nc.num2date(raw_time, units=units, calendar=calendar)

    dates = []
    for dt in cftimes:
        dates.append(datetime.datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second))
    return dates

def _nearest_time_index(time_dates, target_dt):
    diffs = np.array([abs((t - target_dt).total_seconds()) for t in time_dates], dtype=np.float64)
    return int(np.argmin(diffs))

def main():
    parser = argparse.ArgumentParser(
        description="Compute and optionally update start_time and stop_time in a SPartA .conf file."
    )
    parser.add_argument("time_duration", help="Duration (e.g., 3hrs, 12hrs, 1dys, 7dys, 1dys12hrs)")
    parser.add_argument("conf_file", help="Path to SPartA JSON .conf file")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--verbose",
        action="store_true",
        help="Print start_time and stop_time (real datetime and time index) without modifying the .conf file.",
    )
    mode.add_argument(
        "--quiet",
        action="store_true",
        help="Modify start_time and stop_time in the .conf file without printing to the screen.",
    )
    args = parser.parse_args()

    try:
        delta = parse_duration(args.time_duration)
        with open(args.conf_file, "r", encoding="utf-8") as f:
            conf = json.load(f)
        time_dates = _load_hydro_datetimes(conf)
    except Exception as exc:
        if not args.quiet:
            print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    now_dt = datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
    end_dt = now_dt + delta

    start_idx = _nearest_time_index(time_dates, now_dt)
    stop_idx = _nearest_time_index(time_dates, end_dt)

    if not args.verbose:
        conf.setdefault("Parameters", {})
        conf["Parameters"]["start_time"] = start_idx
        conf["Parameters"]["stop_time"] = stop_idx
        with open(args.conf_file, "w", encoding="utf-8") as f:
            json.dump(conf, f, indent=4, ensure_ascii=False)
            f.write("\n")

    if args.verbose or not args.quiet:
        print(f"start_time -> real: {now_dt.strftime('%Y-%m-%d %H:%M:%S')} | time_index: {start_idx} (grid: {time_dates[start_idx].strftime('%Y-%m-%d %H:%M:%S')})")
        print(f"stop_time  -> real: {end_dt.strftime('%Y-%m-%d %H:%M:%S')} | time_index: {stop_idx} (grid: {time_dates[stop_idx].strftime('%Y-%m-%d %H:%M:%S')})")

if __name__ == "__main__":
    main()
