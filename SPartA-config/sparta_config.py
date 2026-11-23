import csv
from datetime import datetime, timedelta
import glob
import json
import math
import os
import queue
import random
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)
MAPS_DIR = os.path.join(PROJECT_ROOT, "SPartA-GUI", "maps")
if not os.path.isdir(MAPS_DIR):
    MAPS_DIR = os.path.join(APP_DIR, "maps")
    os.makedirs(MAPS_DIR, exist_ok=True)

MODEL_TYPES = [
    "FOCURR",
    "FOCURR_RK2",
    "FOCURR_RK4",
    "DECAY_TRACER",
    "SUBSURFACE",
    "RESIDENCE_TIME",
    "OKUBO",
    "CURWIND",
    "GNOME",
    "OPENDRIFT",
    "MEDSLIK2",
    "OSCAR",
    "uPLASTIC",
    "LARVAE",
    "LEEWAY",
    "SARGASSUM",
    "ICEFLOES",
    "DEBRIS",
]

INTERP_METHODS = ["linear", "nearest", "cubic"]
AUX_INTERP_METHODS = ["k4", "k12", "k16"]
RT_METHODS = [
    "RANDOMWALK",
    "UNIFORM",
    "RANDOM",
    "ANORM",
    "MAS",
    "DMAS",
    "WIENER",
    "POISSON",
    "NONE",
]
LINESTYLES = ["-", "--", "-.", ":"]
LEGEND_POSITIONS = [
    "best",
    "upper right",
    "upper left",
    "lower left",
    "lower right",
    "right",
    "center left",
    "center right",
    "lower center",
    "upper center",
    "center",
    "outside upper left",
    "outside upper center",
    "outside upper right",
    "outside lower left",
    "outside lower center",
    "outside lower right",
    "outside left upper",
    "outside left lower",
    "outside right upper",
    "outside right lower",
]

OBJ_TYPES = [
    "mark",
    "text",
    "circle",
    "fcircle",
    "tcircle",
    "rectangle",
    "frectangle",
    "trectangle",
]

OBJ_FIELD_SPECS = {
    "mark": (
        ["Lon", "Lat", "Marker Shape (o,^,s,*)", "Size (pt)", "Color", "(unused)"],
        "Format: mark, lon, lat, shape, size, color",
    ),
    "text": (
        ["Lon", "Lat", "Label Text", "Font Size (pt)", "Color", "Align (lt/ct/rt)"],
        "Format: text, lon, lat, label, fontsize, color, alignment",
    ),
    "circle": (
        ["Center Lon", "Center Lat", "Radius (deg)", "Edge Color", "(unused)", "(unused)"],
        "Format: circle, lon, lat, radius_deg, color",
    ),
    "fcircle": (
        ["Center Lon", "Center Lat", "Radius (deg)", "Fill/Edge Color", "(unused)", "(unused)"],
        "Format: fcircle, lon, lat, radius_deg, color",
    ),
    "tcircle": (
        ["Center Lon", "Center Lat", "Radius (deg)", "Edge Color", "(unused)", "(unused)"],
        "Format: tcircle, lon, lat, radius_deg, color",
    ),
    "rectangle": (
        ["Lon1 (West)", "Lat1 (South)", "Lon2 (East)", "Lat2 (North)", "Edge Color", "(unused)"],
        "Format: rectangle, lon1, lat1, lon2, lat2, color",
    ),
    "frectangle": (
        ["Lon1 (West)", "Lat1 (South)", "Lon2 (East)", "Lat2 (North)", "Fill/Edge Color", "(unused)"],
        "Format: frectangle, lon1, lat1, lon2, lat2, color",
    ),
    "trectangle": (
        ["Lon1 (West)", "Lat1 (South)", "Lon2 (East)", "Lat2 (North)", "Edge Color", "(unused)"],
        "Format: trectangle, lon1, lat1, lon2, lat2, color",
    ),
}

DEFAULT_CONFIG = {
    "General": {
        "model_name": "NEW_SIM",
        "description": "",
        "model_type": "LARVAE",
        "verbose": 2,
    },
    "Inputs": {
        "input_directory": "samples/inputs/",
        "hydrodynamic_file": "12hrClimHYCOM_CURR_1year.nc",
        "htd_paramlist": ["lon", "lat", "time", "water_u", "water_v"],
        "seawater_properties_file": "",
        "swp_paramlist": ["water_temp", "salinity"],
        "wind_file": "",
        "wind_paramlist": ["lon", "lat", "u10", "v10"],
        "stokes_file": "",
        "stokes_paramlist": ["lon", "lat", "ustokes", "vstokes"],
        "particles_file": "test3.csv",
        "active_particles": "all",
        "coast_file": "",
        "objects_files": "islands.obj",
    },
    "Numerical_methods": {
        "interpolation_method": "linear",
        "auxiliary_interpolation_method": "k4",
    },
    "Physics": {
        "invert_vector_fields": 0,
        "compute_transport": 1,
        "seawater_properties": 0,
        "horizdiff": 100,
        "currcoef": 1.0,
        "windwavecoef": 0.0,
        "windwavecoef_automatic": 0,
        "leeway_angle": 0.0,
        "plastic_density": 920.0,
        "biofouling_rate": 0.0,
        "larvae_u_active": -0.02,
        "larvae_v_active": 0.01,
        "larvae_pld": 3000000,
        "larvae_mortality_rate": 0.0,
        "sargassum_biomass_init": 1.0,
        "sargassum_growth_rate": 0.0,
        "sargassum_mortality_rate": 0.0,
        "ice_volume_init": 1000000.0,
        "ice_u_grad": 0.0,
        "ice_v_grad": 0.0,
        "ice_coriolis_coef": 1.0,
        "ice_ablation_basal": 0.0,
        "ice_ablation_lateral": 0.0,
        "ice_ablation_thermal": 0.0,
        "debris_windage": 0.02,
        "stokes_wind_coef": 0.015,
        "decay_rate": 0.0,
        "decay_min_threshold": 0.01,
        "residence_bbox": [-40, -10, -22, 0],
        "okubo_ref_length": 1000.0,
        "subsurface_depth_init": 10.0,
        "subsurface_settling_rate": 0.0,
        "subsurface_max_depth": 100.0,
        "random_term": 1,
        "rt_method": "RANDOMWALK",
    },
    "Parameters": {
        "start_time": 0,
        "stop_time": 60,
        "time_step": 1,
    },
    "Coefficients": {
        "C1": 1.0,
        "C2": 0,
    },
    "Outputs": {
        "output_directory": "samples/outputs/test3/",
        "track_file": "test3.nc",
        "report_file": "test3.info",
        "activate_multilayer_shapefile": 0,
        "particle_map_file": "test3.png",
    },
    "Analysis": {
        "time_interval_filter": 0,
        "time_range": [0, 61],
    },
    "Plots": {
        "study_region": [-40, -10, -22, 0],
        "dpi": 300,
        "particles_to_show": "all",
        "plot_objects": 1,
        "track_lines": 1,
        "show_particle_label": 0,
        "label_color": "blue",
        "label_fontsize": 8,
        "tack_linewidth": 1.2,
        "track_linestyle": "-",
        "track_colortable": "vivid_contrast.tab",
        "triangle_size": 3.0,
        "legend_position": "best",
        "legend_fontsize": 9,
        "legend_numcol": 2,
        "hidden_legend": 0,
    },
}

def _import_cartopy_mpl():
    import cartopy
    cartopy.config["data_dir"] = MAPS_DIR
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    from cartopy.mpl.ticker import LatitudeFormatter, LongitudeFormatter
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.patches as mpatches
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    from matplotlib.widgets import RectangleSelector
    return ccrs, cfeature, LatitudeFormatter, LongitudeFormatter, mpatches, FigureCanvasTkAgg, Figure, RectangleSelector

def resolve_input_file(input_dir, filename):
    if not filename:
        return ""
    if os.path.isabs(filename):
        return filename
    if input_dir:
        joined = os.path.join(input_dir, filename)
        for base in (PROJECT_ROOT, APP_DIR, os.getcwd()):
            cand = os.path.normpath(os.path.join(base, joined))
            if os.path.exists(cand):
                return cand
        return os.path.normpath(os.path.join(PROJECT_ROOT, joined))
    return os.path.normpath(os.path.join(PROJECT_ROOT, filename))

class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.vbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=10)

        self.inner.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self._win_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self._win_id, width=e.width),
        )

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.vbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.inner.bind("<Enter>", self._bind_wheel)
        self.inner.bind("<Leave>", self._unbind_wheel)

    def _on_wheel(self, event):
        delta = -1 * (event.delta // 120) if abs(event.delta) >= 120 else (-1 if event.delta > 0 else 1)
        self.canvas.yview_scroll(delta, "units")

    def _bind_wheel(self, _e=None):
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _unbind_wheel(self, _e=None):
        self.canvas.unbind_all("<MouseWheel>")

def _configure_map_axes(ax, ccrs, cfeature, LatitudeFormatter, LongitudeFormatter, extent=None):
    if extent is not None and len(extent) == 4:
        ax.set_extent(extent, crs=ccrs.PlateCarree())
    else:
        ax.set_global()
    ax.add_feature(cfeature.OCEAN.with_scale("10m"), facecolor="#EEF6FC", zorder=0)
    ax.add_feature(cfeature.LAND.with_scale("10m"), facecolor="#DCDCDC", edgecolor="black", linewidth=0.3, zorder=1)
    ax.add_feature(cfeature.COASTLINE.with_scale("10m"), edgecolor="black", linewidth=0.6, zorder=2)
    ax.add_feature(cfeature.BORDERS.with_scale("10m"), edgecolor="#64748B", linewidth=0.4, zorder=2)
    gl = ax.gridlines(crs=ccrs.PlateCarree(), draw_labels=True, linewidth=0.5, color="gray", alpha=0.5, linestyle="--")
    gl.top_labels = False
    gl.right_labels = False
    gl.xformatter = LongitudeFormatter()
    gl.yformatter = LatitudeFormatter()

class MapRegionSelectorDialog(tk.Toplevel):
    def __init__(
        self,
        parent,
        initial_region,
        on_apply,
        title="Select Study Region on Map (Drag Rectangle)",
        label_prefix="Study Region",
        initial_extent=None,
        apply_text="Apply Region",
    ):
        super().__init__(parent)
        self.title(title)
        self.geometry("920x640")
        self.minsize(720, 520)
        self.on_apply = on_apply
        self.label_prefix = label_prefix
        self.selected_region = list(initial_region) if len(initial_region) == 4 else [-40.0, -10.0, -22.0, 0.0]

        ccrs, cfeature, LatitudeFormatter, LongitudeFormatter, mpatches, FigureCanvasTkAgg, Figure, RectangleSelector = _import_cartopy_mpl()
        self.ccrs = ccrs

        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)
        self.lbl_coords = ttk.Label(top, text=self._fmt_region(self.selected_region))
        self.lbl_coords.pack(side=tk.LEFT)

        ttk.Button(top, text=apply_text, command=self._apply).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(top, text="World View", command=self._world_view).pack(side=tk.RIGHT, padx=4)
        ttk.Button(top, text="Zoom to Selection", command=self._zoom_selection).pack(side=tk.RIGHT, padx=4)

        self.fig = Figure(figsize=(8.6, 5.4), dpi=100)
        self.ax = self.fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
        _configure_map_axes(self.ax, ccrs, cfeature, LatitudeFormatter, LongitudeFormatter, extent=initial_extent)

        lon0, lon1, lat0, lat1 = self.selected_region
        self.rect_patch = mpatches.Rectangle(
            (lon0, lat0), lon1 - lon0, lat1 - lat0,
            edgecolor="#DC2626", facecolor="#EF4444", alpha=0.22, linewidth=1.8,
            transform=ccrs.PlateCarree(), zorder=5
        )
        self.ax.add_patch(self.rect_patch)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self.selector = RectangleSelector(
            self.ax,
            self._on_select,
            useblit=True,
            button=[1],
            minspanx=0.1,
            minspany=0.1,
            spancoords="data",
            interactive=True,
        )
        self.canvas.draw()

    def _fmt_region(self, reg):
        return f"{self.label_prefix}: lon_min={reg[0]:.2f}, lon_max={reg[1]:.2f}, lat_min={reg[2]:.2f}, lat_max={reg[3]:.2f}"

    def _on_select(self, eclick, erelease):
        if eclick.xdata is None or erelease.xdata is None:
            return
        x0, x1 = sorted([round(float(eclick.xdata), 2), round(float(erelease.xdata), 2)])
        y0, y1 = sorted([round(float(eclick.ydata), 2), round(float(erelease.ydata), 2)])
        self.selected_region = [x0, x1, y0, y1]
        self.rect_patch.set_xy((x0, y0))
        self.rect_patch.set_width(x1 - x0)
        self.rect_patch.set_height(y1 - y0)
        self.lbl_coords.configure(text=self._fmt_region(self.selected_region))
        self.canvas.draw_idle()

    def _world_view(self):
        self.ax.set_global()
        self.canvas.draw_idle()

    def _zoom_selection(self):
        x0, x1, y0, y1 = self.selected_region
        pad_x = max(2.0, (x1 - x0) * 0.35)
        pad_y = max(2.0, (y1 - y0) * 0.35)
        self.ax.set_extent([max(-180, x0 - pad_x), min(180, x1 + pad_x), max(-90, y0 - pad_y), min(90, y1 + pad_y)], crs=self.ccrs.PlateCarree())
        self.canvas.draw_idle()

    def _apply(self):
        self.on_apply(self.selected_region)
        self.destroy()

class MapPointPickerDialog(tk.Toplevel):
    def __init__(
        self,
        parent,
        extent,
        on_pick,
        title="Pick Coordinates on Map (Click Point)",
        prompt_text="Click anywhere on the map to select (Lon, Lat):",
    ):
        super().__init__(parent)
        self.title(title)
        self.geometry("820x580")
        self.on_pick = on_pick

        ccrs, cfeature, LatitudeFormatter, LongitudeFormatter, _mpatches, FigureCanvasTkAgg, Figure, _RS = _import_cartopy_mpl()
        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)
        ttk.Label(top, text=prompt_text).pack(side=tk.LEFT)
        ttk.Button(top, text="World View", command=lambda: (self.ax.set_global(), self.canvas.draw_idle())).pack(side=tk.RIGHT)

        self.fig = Figure(figsize=(8.0, 5.0), dpi=100)
        self.ax = self.fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
        _configure_map_axes(self.ax, ccrs, cfeature, LatitudeFormatter, LongitudeFormatter, extent=extent)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.canvas.mpl_connect("button_press_event", self._on_click)
        self.canvas.draw()

    def _on_click(self, event):
        if event.inaxes == self.ax and event.xdata is not None and event.ydata is not None and event.button == 1:
            self.on_pick(round(float(event.xdata), 4), round(float(event.ydata), 4))
            self.destroy()

class MapCirclePickerDialog(tk.Toplevel):

    def __init__(self, parent, extent, initial_center, initial_diameter, on_apply):
        super().__init__(parent)
        self.title("Draw Circle on Map (Click Center & Drag Radius)")
        self.geometry("920x640")
        self.minsize(720, 520)
        self.on_apply = on_apply
        self.center = [round(float(initial_center[0]), 4), round(float(initial_center[1]), 4)]
        self.diameter = max(0.05, round(float(initial_diameter), 4))
        self._dragging = False

        ccrs, cfeature, LatitudeFormatter, LongitudeFormatter, mpatches, FigureCanvasTkAgg, Figure, _RS = _import_cartopy_mpl()
        self.ccrs = ccrs

        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)
        self.lbl_coords = ttk.Label(top, text=self._fmt_circle())
        self.lbl_coords.pack(side=tk.LEFT)

        ttk.Button(top, text="Apply Circle", command=self._apply).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(top, text="World View", command=lambda: (self.ax.set_global(), self.canvas.draw_idle())).pack(side=tk.RIGHT, padx=4)
        ttk.Button(top, text="Zoom to Selection", command=self._zoom_selection).pack(side=tk.RIGHT, padx=4)

        self.fig = Figure(figsize=(8.6, 5.4), dpi=100)
        self.ax = self.fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
        _configure_map_axes(self.ax, ccrs, cfeature, LatitudeFormatter, LongitudeFormatter, extent=extent)

        self.circle_patch = mpatches.Circle(
            tuple(self.center), self.diameter * 0.5,
            edgecolor="#DC2626", facecolor="#EF4444", alpha=0.22, linewidth=1.8,
            transform=ccrs.PlateCarree(), zorder=5,
        )
        self.ax.add_patch(self.circle_patch)
        (self.center_marker,) = self.ax.plot(
            [self.center[0]], [self.center[1]], marker="+", markersize=10,
            color="#991B1B", markeredgewidth=1.8, transform=ccrs.PlateCarree(), zorder=6,
        )

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.draw()

    def _fmt_circle(self):
        return f"Circle: Center=({self.center[0]:.4f}, {self.center[1]:.4f}), Diameter={self.diameter:.4f}°"

    def _refresh_artist(self):
        self.circle_patch.set_center(tuple(self.center))
        self.circle_patch.set_radius(self.diameter * 0.5)
        self.center_marker.set_data([self.center[0]], [self.center[1]])
        self.lbl_coords.configure(text=self._fmt_circle())
        self.canvas.draw_idle()

    def _on_press(self, event):
        if event.inaxes == self.ax and event.xdata is not None and event.ydata is not None and event.button == 1:
            self._dragging = True
            self.center = [round(float(event.xdata), 4), round(float(event.ydata), 4)]
            self._refresh_artist()

    def _on_motion(self, event):
        if not self._dragging or event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        r = math.hypot(float(event.xdata) - self.center[0], float(event.ydata) - self.center[1])
        if r >= 0.01:
            self.diameter = round(2.0 * r, 4)
        self._refresh_artist()

    def _on_release(self, event):
        if self._dragging and event.button == 1:
            if event.inaxes == self.ax and event.xdata is not None and event.ydata is not None:
                r = math.hypot(float(event.xdata) - self.center[0], float(event.ydata) - self.center[1])
                if r >= 0.01:
                    self.diameter = round(2.0 * r, 4)
            self._dragging = False
            self._refresh_artist()

    def _zoom_selection(self):
        r = max(1.0, self.diameter * 0.5)
        pad = max(1.5, r * 0.8)
        cx, cy = self.center
        self.ax.set_extent(
            [max(-180, cx - r - pad), min(180, cx + r + pad), max(-90, cy - r - pad), min(90, cy + r + pad)],
            crs=self.ccrs.PlateCarree(),
        )
        self.canvas.draw_idle()

    def _apply(self):
        self.on_apply(self.center[0], self.center[1], self.diameter)
        self.destroy()

class MapTransectPickerDialog(tk.Toplevel):

    def __init__(self, parent, extent, initial_start, initial_end, on_apply):
        super().__init__(parent)
        self.title("Draw Transect on Map (Drag Start → End)")
        self.geometry("920x640")
        self.minsize(720, 520)
        self.on_apply = on_apply
        self.start = [round(float(initial_start[0]), 4), round(float(initial_start[1]), 4)]
        self.end = [round(float(initial_end[0]), 4), round(float(initial_end[1]), 4)]
        self._dragging = False

        ccrs, cfeature, LatitudeFormatter, LongitudeFormatter, _mpatches, FigureCanvasTkAgg, Figure, _RS = _import_cartopy_mpl()
        self.ccrs = ccrs

        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)
        self.lbl_coords = ttk.Label(top, text=self._fmt_transect())
        self.lbl_coords.pack(side=tk.LEFT)

        ttk.Button(top, text="Apply Transect", command=self._apply).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(top, text="World View", command=lambda: (self.ax.set_global(), self.canvas.draw_idle())).pack(side=tk.RIGHT, padx=4)
        ttk.Button(top, text="Zoom to Selection", command=self._zoom_selection).pack(side=tk.RIGHT, padx=4)

        self.fig = Figure(figsize=(8.6, 5.4), dpi=100)
        self.ax = self.fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
        _configure_map_axes(self.ax, ccrs, cfeature, LatitudeFormatter, LongitudeFormatter, extent=extent)

        (self.line_artist,) = self.ax.plot(
            [self.start[0], self.end[0]], [self.start[1], self.end[1]],
            color="#DC2626", linewidth=2.2, marker="o", markersize=6,
            markerfacecolor="#EF4444", markeredgecolor="#7F1D1D",
            transform=ccrs.PlateCarree(), zorder=6,
        )

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.draw()

    def _fmt_transect(self):
        return f"Transect: Start=({self.start[0]:.4f}, {self.start[1]:.4f}) → End=({self.end[0]:.4f}, {self.end[1]:.4f})"

    def _refresh_artist(self):
        self.line_artist.set_data([self.start[0], self.end[0]], [self.start[1], self.end[1]])
        self.lbl_coords.configure(text=self._fmt_transect())
        self.canvas.draw_idle()

    def _on_press(self, event):
        if event.inaxes == self.ax and event.xdata is not None and event.ydata is not None and event.button == 1:
            self._dragging = True
            pt = [round(float(event.xdata), 4), round(float(event.ydata), 4)]
            self.start = list(pt)
            self.end = list(pt)
            self._refresh_artist()

    def _on_motion(self, event):
        if not self._dragging or event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        self.end = [round(float(event.xdata), 4), round(float(event.ydata), 4)]
        self._refresh_artist()

    def _on_release(self, event):
        if self._dragging and event.button == 1:
            if event.inaxes == self.ax and event.xdata is not None and event.ydata is not None:
                self.end = [round(float(event.xdata), 4), round(float(event.ydata), 4)]
            self._dragging = False
            self._refresh_artist()

    def _zoom_selection(self):
        x0, x1 = sorted([self.start[0], self.end[0]])
        y0, y1 = sorted([self.start[1], self.end[1]])
        pad_x = max(2.0, (x1 - x0) * 0.35)
        pad_y = max(2.0, (y1 - y0) * 0.35)
        self.ax.set_extent(
            [max(-180, x0 - pad_x), min(180, x1 + pad_x), max(-90, y0 - pad_y), min(90, y1 + pad_y)],
            crs=self.ccrs.PlateCarree(),
        )
        self.canvas.draw_idle()

    def _apply(self):
        self.on_apply(self.start[0], self.start[1], self.end[0], self.end[1])
        self.destroy()

def _decimal_to_sparta_dms(val, is_lon=True):
    hemi = ("E" if val >= 0 else "W") if is_lon else ("N" if val >= 0 else "S")
    abs_val = abs(float(val))
    deg = int(abs_val)
    rem_min = (abs_val - deg) * 60.0
    minutes = int(rem_min)
    sec = round((rem_min - minutes) * 60.0, 1)
    if sec >= 60.0:
        sec = 0.0
        minutes += 1
    if minutes >= 60:
        minutes = 0
        deg += 1
    return f'{deg}˚{minutes:02d}"{sec:04.1f}{hemi}'

def _convert_dms_if_needed(val_str):
    s = str(val_str).strip()
    if "˚" not in s:
        return float(s)
    sign = -1.0 if s.endswith(("S", "W")) else 1.0
    parts = s.lstrip("+-").rstrip("NSWE").split("˚")
    deg = float(parts[0])
    parts = parts[1].split('"')
    minutes = float(parts[0])
    sec_parts = parts[1].split(".")
    sec = float(sec_parts[0])
    csec = float(sec_parts[1]) if len(sec_parts) > 1 else 0.0
    return sign * (deg + minutes / 60.0 + sec / 3600.0 + csec / 360000.0)

def _build_land_checker():
    import cartopy
    cartopy.config["data_dir"] = MAPS_DIR
    from cartopy.io.shapereader import Reader, natural_earth
    from shapely.geometry import Point
    from shapely.strtree import STRtree

    shp = natural_earth(resolution="10m", category="physical", name="land")
    geoms = list(Reader(shp).geometries())
    tree = STRtree(geoms)

    def _is_on_land(lon, lat):
        pt = Point(lon, lat)
        for idx in tree.query(pt):
            if geoms[idx].contains(pt):
                return True
        return False

    return _is_on_land

class MapPreviewDialog(tk.Toplevel):
    def __init__(self, parent, extent, title, particles=None, objects=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("880x640")

        ccrs, cfeature, LatitudeFormatter, LongitudeFormatter, mpatches, FigureCanvasTkAgg, Figure, _RS = _import_cartopy_mpl()
        fig = Figure(figsize=(8.4, 5.8), dpi=100)
        ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
        if len(extent) == 4:
            ax.set_extent(extent, crs=ccrs.PlateCarree())
        else:
            ax.set_global()

        ax.add_feature(cfeature.OCEAN.with_scale("10m"), facecolor="#EEF6FC", zorder=0)
        ax.add_feature(cfeature.LAND.with_scale("10m"), facecolor="#DCDCDC", edgecolor="black", linewidth=0.35, zorder=1)
        ax.add_feature(cfeature.COASTLINE.with_scale("10m"), edgecolor="black", linewidth=0.7, zorder=2)
        ax.add_feature(cfeature.BORDERS.with_scale("10m"), edgecolor="#64748B", linewidth=0.45, zorder=2)
        gl = ax.gridlines(crs=ccrs.PlateCarree(), draw_labels=True, linewidth=0.5, color="gray", alpha=0.5, linestyle="--")
        gl.top_labels = False
        gl.right_labels = False
        gl.xformatter = LongitudeFormatter()
        gl.yformatter = LatitudeFormatter()

        if particles:
            lons = [p[1] for p in particles]
            lats = [p[2] for p in particles]
            ax.scatter(lons, lats, c="#DC2626", s=36, marker="o", edgecolors="black", linewidths=0.5, transform=ccrs.PlateCarree(), zorder=6, label=f"Particles ({len(particles)})")
            ax.legend(loc="upper right")

        if objects:
            for row in objects:
                otype = row[0].lower()
                try:
                    if otype == "mark":
                        ax.plot(_convert_dms_if_needed(row[1]), _convert_dms_if_needed(row[2]), marker=row[3] or "o", markersize=float(row[4] or 6), color=row[5] or "red", transform=ccrs.PlateCarree(), zorder=6)
                    elif otype == "text":
                        ax.text(_convert_dms_if_needed(row[1]), _convert_dms_if_needed(row[2]), row[3], fontsize=float(row[4] or 9), color=row[5] or "blue", transform=ccrs.PlateCarree(), zorder=7)
                    elif otype in ("circle", "fcircle", "tcircle"):
                        fc = (row[4] or "blue") if otype == "fcircle" else "none"
                        alpha = 0.25 if otype == "fcircle" else 1.0
                        c = mpatches.Circle((_convert_dms_if_needed(row[1]), _convert_dms_if_needed(row[2])), float(row[3]), edgecolor=row[4] or "blue", facecolor=fc, alpha=alpha, transform=ccrs.PlateCarree(), zorder=5)
                        ax.add_patch(c)
                    elif otype in ("rectangle", "frectangle", "trectangle"):
                        x1, y1 = _convert_dms_if_needed(row[1]), _convert_dms_if_needed(row[2])
                        x2, y2 = _convert_dms_if_needed(row[3]), _convert_dms_if_needed(row[4])
                        fc = (row[5] or "green") if otype == "frectangle" else "none"
                        alpha = 0.25 if otype == "frectangle" else 1.0
                        r = mpatches.Rectangle((x1, y1), x2 - x1, y2 - y1, edgecolor=row[5] or "green", facecolor=fc, alpha=alpha, transform=ccrs.PlateCarree(), zorder=5)
                        ax.add_patch(r)
                except (IndexError, ValueError):
                    continue

        ax.set_title(title, fontsize=11, fontweight="bold")
        canvas = FigureCanvasTkAgg(fig, master=self)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        canvas.draw()

class ParticleCSVEditorDialog(tk.Toplevel):
    GEN_METHODS = [
        "Jitter around point (±Δ°)",
        "Circle around point (Diameter °)",
        "Rectangle (BBox)",
        "Regular Grid (Ocean only)",
        "Line / Transect",
    ]

    def __init__(self, parent, csv_path, study_region):
        super().__init__(parent)
        self.title(f"Particle CSV Editor — {os.path.basename(csv_path) or 'particles.csv'}")
        self.geometry("1140x720")
        self.minsize(1100, 620)
        self.csv_path = csv_path
        self.study_region = study_region if len(study_region) == 4 else [-40.0, -10.0, -22.0, 0.0]

        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)
        ttk.Label(top, text=f"File: {csv_path}", wraplength=940).pack(anchor=tk.W)

        tree_frame = ttk.Frame(self, padding=(8, 0))
        tree_frame.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=("name", "lon", "lat"), show="headings", selectmode="browse")
        self.tree.heading("name", text="Particle Name")
        self.tree.heading("lon", text="Longitude")
        self.tree.heading("lat", text="Latitude")
        self.tree.column("name", width=260)
        self.tree.column("lon", width=240)
        self.tree.column("lat", width=240)
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        form = ttk.LabelFrame(self, text="Single Particle Entry", padding=8)
        form.pack(fill=tk.X, padx=8, pady=(6, 4))

        self.var_name = tk.StringVar()
        self.var_lon = tk.StringVar()
        self.var_lat = tk.StringVar()

        ttk.Label(form, text="Name:").grid(row=0, column=0, padx=4, pady=3)
        ttk.Entry(form, textvariable=self.var_name, width=16).grid(row=0, column=1, padx=4, pady=3)
        ttk.Label(form, text="Lon:").grid(row=0, column=2, padx=4, pady=3)
        ttk.Entry(form, textvariable=self.var_lon, width=12).grid(row=0, column=3, padx=4, pady=3)
        ttk.Label(form, text="Lat:").grid(row=0, column=4, padx=4, pady=3)
        ttk.Entry(form, textvariable=self.var_lat, width=12).grid(row=0, column=5, padx=4, pady=3)
        ttk.Button(form, text="Pick on Map...", command=self._pick_map).grid(row=0, column=6, padx=6, pady=3)
        ttk.Button(form, text="Add", command=self._add_row, width=7).grid(row=0, column=7, padx=3, pady=3)
        ttk.Button(form, text="Update", command=self._update_row, width=8).grid(row=0, column=8, padx=3, pady=3)
        ttk.Button(form, text="Delete", command=self._delete_row, width=8).grid(row=0, column=9, padx=3, pady=3)

        gen_lf = ttk.LabelFrame(self, text="Particle Generator (Ocean-Safe)", padding=8)
        gen_lf.pack(fill=tk.X, padx=8, pady=(4, 6))

        cx = round((self.study_region[0] + self.study_region[1]) * 0.5, 2)
        cy = round((self.study_region[2] + self.study_region[3]) * 0.5, 2)
        self.gen_method_var = tk.StringVar(value=self.GEN_METHODS[1])
        self.gen_prefix_var = tk.StringVar(value="P")
        self.gen_count_var = tk.IntVar(value=15)
        self.gen_lon0_var = tk.DoubleVar(value=cx)
        self.gen_lat0_var = tk.DoubleVar(value=cy)
        self.gen_span_var = tk.DoubleVar(value=2.0)
        self.gen_lon1_var = tk.DoubleVar(value=self.study_region[0] + 1.0)
        self.gen_lat1_var = tk.DoubleVar(value=self.study_region[2] + 1.0)
        self.gen_lon2_var = tk.DoubleVar(value=self.study_region[1] - 1.0)
        self.gen_lat2_var = tk.DoubleVar(value=self.study_region[3] - 1.0)
        self.gen_exclude_land_var = tk.BooleanVar(value=True)
        self.gen_replace_var = tk.BooleanVar(value=False)

        r0 = ttk.Frame(gen_lf)
        r0.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(r0, text="Method:").pack(side=tk.LEFT)
        cb = ttk.Combobox(r0, textvariable=self.gen_method_var, values=self.GEN_METHODS, state="readonly", width=30)
        cb.pack(side=tk.LEFT, padx=(4, 10))
        cb.bind("<<ComboboxSelected>>", lambda _e: self._refresh_gen_fields())
        ttk.Label(r0, text="Prefix:").pack(side=tk.LEFT)
        ttk.Entry(r0, textvariable=self.gen_prefix_var, width=6).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(r0, text="Count:").pack(side=tk.LEFT)
        ttk.Spinbox(r0, from_=1, to=2000, increment=1, textvariable=self.gen_count_var, width=6).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Checkbutton(r0, text="Exclude land (10m)", variable=self.gen_exclude_land_var).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(r0, text="Replace existing", variable=self.gen_replace_var).pack(side=tk.LEFT, padx=4)

        self.gen_params_frame = ttk.Frame(gen_lf)
        self.gen_params_frame.pack(fill=tk.X, pady=2)
        self._refresh_gen_fields()

        btns = ttk.Frame(self, padding=(8, 0, 8, 8))
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Generate Particles", command=self._generate_particles).pack(side=tk.LEFT, padx=3)
        ttk.Button(btns, text="Clear All", command=self._clear_all).pack(side=tk.LEFT, padx=3)
        ttk.Button(btns, text="Preview on Map...", command=self._preview_on_map).pack(side=tk.LEFT, padx=12)
        ttk.Button(btns, text="Save CSV", command=self._save_csv).pack(side=tk.RIGHT, padx=3)

        self._load_csv()

    def _refresh_gen_fields(self):
        for w in self.gen_params_frame.winfo_children():
            w.destroy()
        m = self.gen_method_var.get()
        if m in (self.GEN_METHODS[0], self.GEN_METHODS[1]):
            span_lbl = "±Δ (deg):" if m == self.GEN_METHODS[0] else "Diameter (deg):"
            ttk.Label(self.gen_params_frame, text="Center Lon:").pack(side=tk.LEFT)
            ttk.Entry(self.gen_params_frame, textvariable=self.gen_lon0_var, width=9).pack(side=tk.LEFT, padx=(4, 8))
            ttk.Label(self.gen_params_frame, text="Center Lat:").pack(side=tk.LEFT)
            ttk.Entry(self.gen_params_frame, textvariable=self.gen_lat0_var, width=9).pack(side=tk.LEFT, padx=(4, 8))
            ttk.Label(self.gen_params_frame, text=span_lbl).pack(side=tk.LEFT)
            ttk.Entry(self.gen_params_frame, textvariable=self.gen_span_var, width=8).pack(side=tk.LEFT, padx=(4, 8))
        else:
            l1 = "Start Lon:" if m == self.GEN_METHODS[4] else "Lon Min:"
            l2 = "Start Lat:" if m == self.GEN_METHODS[4] else "Lat Min:"
            l3 = "End Lon:" if m == self.GEN_METHODS[4] else "Lon Max:"
            l4 = "End Lat:" if m == self.GEN_METHODS[4] else "Lat Max:"
            for lbl, var in [(l1, self.gen_lon1_var), (l2, self.gen_lat1_var), (l3, self.gen_lon2_var), (l4, self.gen_lat2_var)]:
                ttk.Label(self.gen_params_frame, text=lbl).pack(side=tk.LEFT)
                ttk.Entry(self.gen_params_frame, textvariable=var, width=8).pack(side=tk.LEFT, padx=(3, 8))
            if m == self.GEN_METHODS[4]:
                ttk.Label(self.gen_params_frame, text="Jitter ±Δ°:").pack(side=tk.LEFT)
                ttk.Entry(self.gen_params_frame, textvariable=self.gen_span_var, width=6).pack(side=tk.LEFT, padx=3)
        ttk.Button(self.gen_params_frame, text="Pick on Map...", command=self._pick_gen_on_map).pack(side=tk.LEFT, padx=6)

    def _pick_gen_on_map(self):
        try:
            m = self.gen_method_var.get()
            if m == self.GEN_METHODS[0]:
                MapPointPickerDialog(
                    self,
                    self.study_region,
                    lambda lon, lat: (self.gen_lon0_var.set(lon), self.gen_lat0_var.set(lat)),
                    title="Pick Center on Map (Click Point)",
                    prompt_text="Click anywhere on the map to select center (Lon, Lat):",
                )
            elif m == self.GEN_METHODS[1]:
                c_lon = float(self.gen_lon0_var.get())
                c_lat = float(self.gen_lat0_var.get())
                diam = abs(float(self.gen_span_var.get()))
                MapCirclePickerDialog(
                    self,
                    self.study_region,
                    (c_lon, c_lat),
                    diam,
                    lambda lon, lat, d: (
                        self.gen_lon0_var.set(lon),
                        self.gen_lat0_var.set(lat),
                        self.gen_span_var.set(d),
                    ),
                )
            elif m in (self.GEN_METHODS[2], self.GEN_METHODS[3]):
                x1, x2 = sorted([float(self.gen_lon1_var.get()), float(self.gen_lon2_var.get())])
                y1, y2 = sorted([float(self.gen_lat1_var.get()), float(self.gen_lat2_var.get())])
                MapRegionSelectorDialog(
                    self,
                    [x1, x2, y1, y2],
                    lambda reg: (
                        self.gen_lon1_var.set(reg[0]),
                        self.gen_lon2_var.set(reg[1]),
                        self.gen_lat1_var.set(reg[2]),
                        self.gen_lat2_var.set(reg[3]),
                    ),
                    title="Select Generation BBox on Map (Drag Rectangle)",
                    label_prefix="BBox",
                    initial_extent=self.study_region,
                    apply_text="Apply BBox",
                )
            elif m == self.GEN_METHODS[4]:
                x1, y1 = float(self.gen_lon1_var.get()), float(self.gen_lat1_var.get())
                x2, y2 = float(self.gen_lon2_var.get()), float(self.gen_lat2_var.get())
                MapTransectPickerDialog(
                    self,
                    self.study_region,
                    (x1, y1),
                    (x2, y2),
                    lambda lon1, lat1, lon2, lat2: (
                        self.gen_lon1_var.set(lon1),
                        self.gen_lat1_var.set(lat1),
                        self.gen_lon2_var.set(lon2),
                        self.gen_lat2_var.set(lat2),
                    ),
                )
        except Exception as exc:
            messagebox.showerror("Map Error", str(exc))

    def _generate_particles(self):
        try:
            m = self.gen_method_var.get()
            n_target = max(1, int(self.gen_count_var.get()))
            prefix = self.gen_prefix_var.get().strip() or "P"
            exclude_land = self.gen_exclude_land_var.get()
            land_fn = _build_land_checker() if exclude_land else (lambda _x, _y: False)

            pts = []
            max_tries = max(n_target * 40, 1000)

            if m == self.GEN_METHODS[0]:
                c_lon, c_lat = float(self.gen_lon0_var.get()), float(self.gen_lat0_var.get())
                d = abs(float(self.gen_span_var.get()))
                for _ in range(max_tries):
                    if len(pts) >= n_target:
                        break
                    x = round(c_lon + random.uniform(-d, d), 4)
                    y = round(c_lat + random.uniform(-d, d), 4)
                    if not land_fn(x, y):
                        pts.append((x, y))

            elif m == self.GEN_METHODS[1]:
                c_lon, c_lat = float(self.gen_lon0_var.get()), float(self.gen_lat0_var.get())
                radius = abs(float(self.gen_span_var.get())) * 0.5
                for _ in range(max_tries):
                    if len(pts) >= n_target:
                        break
                    r = radius * math.sqrt(random.random())
                    theta = random.uniform(0.0, 2.0 * math.pi)
                    x = round(c_lon + r * math.cos(theta), 4)
                    y = round(c_lat + r * math.sin(theta), 4)
                    if not land_fn(x, y):
                        pts.append((x, y))

            elif m == self.GEN_METHODS[2]:
                x1, x2 = sorted([float(self.gen_lon1_var.get()), float(self.gen_lon2_var.get())])
                y1, y2 = sorted([float(self.gen_lat1_var.get()), float(self.gen_lat2_var.get())])
                for _ in range(max_tries):
                    if len(pts) >= n_target:
                        break
                    x = round(random.uniform(x1, x2), 4)
                    y = round(random.uniform(y1, y2), 4)
                    if not land_fn(x, y):
                        pts.append((x, y))

            elif m == self.GEN_METHODS[3]:
                x1, x2 = sorted([float(self.gen_lon1_var.get()), float(self.gen_lon2_var.get())])
                y1, y2 = sorted([float(self.gen_lat1_var.get()), float(self.gen_lat2_var.get())])
                nx = max(2, int(round(math.sqrt(n_target * max(0.2, (x2 - x1) / max(0.1, y2 - y1))))))
                ny = max(2, int(math.ceil(n_target / nx)))
                xs = [x1 + i * (x2 - x1) / max(1, nx - 1) for i in range(nx)]
                ys = [y1 + j * (y2 - y1) / max(1, ny - 1) for j in range(ny)]
                for y in ys:
                    for x in xs:
                        rx, ry = round(x, 4), round(y, 4)
                        if not land_fn(rx, ry):
                            pts.append((rx, ry))

            elif m == self.GEN_METHODS[4]:
                x1, y1 = float(self.gen_lon1_var.get()), float(self.gen_lat1_var.get())
                x2, y2 = float(self.gen_lon2_var.get()), float(self.gen_lat2_var.get())
                jitter = abs(float(self.gen_span_var.get())) * 0.1
                for i in range(n_target * 3):
                    if len(pts) >= n_target:
                        break
                    t = (i % n_target) / max(1, n_target - 1)
                    x = round(x1 + t * (x2 - x1) + random.uniform(-jitter, jitter), 4)
                    y = round(y1 + t * (y2 - y1) + random.uniform(-jitter, jitter), 4)
                    if not land_fn(x, y):
                        pts.append((x, y))

            if self.gen_replace_var.get():
                self._clear_all()

            start_idx = len(self.tree.get_children()) + 1
            for idx, (x, y) in enumerate(pts):
                self.tree.insert("", tk.END, values=(f"{prefix}_{start_idx + idx:02d}", str(x), str(y)))

            if len(pts) < n_target and m != self.GEN_METHODS[3]:
                messagebox.showwarning("Partial Generation", f"Generated {len(pts)} of {n_target} ocean particles (land excluded).")
        except Exception as exc:
            messagebox.showerror("Generator Error", str(exc))

    def _clear_all(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    def _preview_on_map(self):
        particles = []
        for item in self.tree.get_children():
            vals = self.tree.item(item, "values")
            try:
                particles.append((vals[0], float(vals[1]), float(vals[2])))
            except (IndexError, ValueError):
                continue
        if not particles:
            messagebox.showinfo("No Particles", "Add or generate particles first to preview them on the map.")
            return
        MapPreviewDialog(self, self.study_region, f"Particle Locations Preview ({len(particles)} particles)", particles=particles)

    def _load_csv(self):
        if os.path.isfile(self.csv_path):
            with open(self.csv_path, newline="", encoding="utf-8") as fh:
                for row in csv.reader(fh):
                    if len(row) >= 3:
                        self.tree.insert("", tk.END, values=(row[0].strip(), row[1].strip(), row[2].strip()))

    def _on_select(self, _e=None):
        sel = self.tree.selection()
        if sel:
            vals = self.tree.item(sel[0], "values")
            self.var_name.set(vals[0])
            self.var_lon.set(vals[1])
            self.var_lat.set(vals[2])

    def _pick_map(self):
        try:
            MapPointPickerDialog(self, self.study_region, lambda lon, lat: (self.var_lon.set(str(lon)), self.var_lat.set(str(lat))))
        except Exception as exc:
            messagebox.showerror("Map Error", str(exc))

    def _validate_inputs(self):
        name = self.var_name.get().strip()
        if not name:
            raise ValueError("Particle Name is required.")
        lon = float(self.var_lon.get().strip())
        lat = float(self.var_lat.get().strip())
        return name, str(lon), str(lat)

    def _add_row(self):
        try:
            vals = self._validate_inputs()
            self.tree.insert("", tk.END, values=vals)
        except ValueError as exc:
            messagebox.showerror("Invalid Particle", str(exc))

    def _update_row(self):
        sel = self.tree.selection()
        if not sel:
            return
        try:
            vals = self._validate_inputs()
            self.tree.item(sel[0], values=vals)
        except ValueError as exc:
            messagebox.showerror("Invalid Particle", str(exc))

    def _delete_row(self):
        sel = self.tree.selection()
        if sel:
            self.tree.delete(sel[0])

    def _save_csv(self):
        os.makedirs(os.path.dirname(self.csv_path), exist_ok=True)
        with open(self.csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            for item in self.tree.get_children():
                writer.writerow(self.tree.item(item, "values"))
        messagebox.showinfo("Saved", f"Saved {len(self.tree.get_children())} particles to:\n{self.csv_path}")

class MapObjectsEditorDialog(tk.Toplevel):
    def __init__(self, parent, obj_path, study_region):
        super().__init__(parent)
        self.title(f"Map Objects (.obj) Editor — {os.path.basename(obj_path) or 'objects.obj'}")
        self.geometry("1140x680")
        self.minsize(1060, 580)
        self.obj_path = obj_path
        self.study_region = study_region

        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)
        ttk.Label(top, text=f"File: {obj_path}", wraplength=940).pack(anchor=tk.W)

        tree_frame = ttk.Frame(self, padding=(8, 0))
        tree_frame.pack(fill=tk.BOTH, expand=True)
        cols = ("type", "a1", "a2", "a3", "a4", "a5", "a6")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        headers = ["Type", "Arg1 (Lon/Lon1)", "Arg2 (Lat/Lat1)", "Arg3 (Shape/Label/Rad/Lon2)", "Arg4 (Size/Color/Lat2)", "Arg5 (Color)", "Arg6 (Align)"]
        for c, h in zip(cols, headers):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=130)
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        form = ttk.LabelFrame(self, text="Object Definition (Dynamic Arg Labels per Type)", padding=8)
        form.pack(fill=tk.X, padx=8, pady=8)

        self.vars = [tk.StringVar() for _ in range(7)]
        self.vars[0].set("mark")

        ttk.Label(form, text="Type:").grid(row=0, column=0, padx=4, pady=3, sticky=tk.W)
        cb_type = ttk.Combobox(form, textvariable=self.vars[0], values=OBJ_TYPES, state="readonly", width=14)
        cb_type.grid(row=0, column=1, padx=4, pady=3, sticky=tk.W)
        cb_type.bind("<<ComboboxSelected>>", lambda _e: self._update_arg_labels())

        self.syntax_lbl = ttk.Label(form, text="", foreground="#2563EB")
        self.syntax_lbl.grid(row=0, column=2, padx=8, pady=3, sticky=tk.W)
        ttk.Button(form, text="Pick on Map...", command=self._pick_map).grid(row=0, column=3, padx=6, pady=3, sticky=tk.E)

        self.arg_labels = []
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)
        for idx in range(6):
            r = 1 + (idx // 2)
            c_base = (idx % 2) * 2
            lbl = ttk.Label(form, text=f"Arg{idx + 1}:", width=24, anchor=tk.W)
            lbl.grid(row=r, column=c_base, padx=4, pady=3, sticky=tk.W)
            ttk.Entry(form, textvariable=self.vars[idx + 1], width=24).grid(row=r, column=c_base + 1, padx=4, pady=3, sticky=tk.EW)
            self.arg_labels.append(lbl)

        self._update_arg_labels()

        btns = ttk.Frame(self, padding=(8, 0, 8, 8))
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Add", command=self._add_row).pack(side=tk.LEFT, padx=3)
        ttk.Button(btns, text="Update Selected", command=self._update_row).pack(side=tk.LEFT, padx=3)
        ttk.Button(btns, text="Delete Selected", command=self._delete_row).pack(side=tk.LEFT, padx=3)
        ttk.Button(btns, text="Preview on Map...", command=self._preview_on_map).pack(side=tk.LEFT, padx=12)
        ttk.Button(btns, text="Save .obj", command=self._save_obj).pack(side=tk.RIGHT, padx=3)

        self._load_obj()

    def _update_arg_labels(self):
        otype = self.vars[0].get().lower()
        names, syntax = OBJ_FIELD_SPECS.get(
            otype,
            (["Lon", "Lat", "Arg3", "Arg4", "Arg5", "Arg6"], "Format: type, arg1, arg2, ..."),
        )
        for lbl, name in zip(self.arg_labels, names):
            lbl.configure(text=f"{name}:")
        self.syntax_lbl.configure(text=syntax)

    def _preview_on_map(self):
        objs = []
        for item in self.tree.get_children():
            objs.append(list(self.tree.item(item, "values")))
        if not objs:
            messagebox.showinfo("No Objects", "Add objects first to preview them on the map.")
            return
        MapPreviewDialog(self, self.study_region, f"Map Objects Preview ({len(objs)} objects)", objects=objs)

    def _load_obj(self):
        if os.path.isfile(self.obj_path):
            with open(self.obj_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = [p.strip() for p in line.split(",")]
                    padded = (parts + [""] * 7)[:7]
                    self.tree.insert("", tk.END, values=padded)

    def _on_select(self, _e=None):
        sel = self.tree.selection()
        if sel:
            vals = self.tree.item(sel[0], "values")
            for i in range(7):
                self.vars[i].set(vals[i] if i < len(vals) else "")
            self._update_arg_labels()

    def _pick_map(self):
        try:
            MapPointPickerDialog(
                self,
                self.study_region,
                lambda lon, lat: (
                    self.vars[1].set(_decimal_to_sparta_dms(lon, is_lon=True)),
                    self.vars[2].set(_decimal_to_sparta_dms(lat, is_lon=False)),
                ),
            )
        except Exception as exc:
            messagebox.showerror("Map Error", str(exc))

    def _current_tuple(self):
        vals = [v.get().strip() for v in self.vars]
        if not vals[0]:
            raise ValueError("Object type is required.")
        return tuple(vals)

    def _add_row(self):
        try:
            self.tree.insert("", tk.END, values=self._current_tuple())
        except ValueError as exc:
            messagebox.showerror("Invalid Object", str(exc))

    def _update_row(self):
        sel = self.tree.selection()
        if not sel:
            return
        try:
            self.tree.item(sel[0], values=self._current_tuple())
        except ValueError as exc:
            messagebox.showerror("Invalid Object", str(exc))

    def _delete_row(self):
        sel = self.tree.selection()
        if sel:
            self.tree.delete(sel[0])

    def _save_obj(self):
        os.makedirs(os.path.dirname(self.obj_path), exist_ok=True)
        with open(self.obj_path, "w", encoding="utf-8") as fh:
            for item in self.tree.get_children():
                vals = [v for v in self.tree.item(item, "values") if v != ""]
                fh.write(",".join(vals) + "\n")
        messagebox.showinfo("Saved", f"Saved {len(self.tree.get_children())} objects to:\n{self.obj_path}")

class TimeIndexCalculatorDialog(tk.Toplevel):

    _DT_FORMATS = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
    )
    _UNIT_SECONDS = {
        "seconds": 1.0,
        "minutes": 60.0,
        "hours": 3600.0,
        "days": 86400.0,
    }

    def __init__(self, parent, target_label, current_index, on_insert, nc_path="", time_var_name="time"):
        super().__init__(parent)
        self.title(f"Time Index Calculator — {target_label}")
        self.geometry("610x420")
        self.resizable(False, False)
        self.transient(parent)
        self.on_insert = on_insert
        self.nc_path = nc_path
        self.time_var_name = time_var_name or "time"
        self.calculated_index = None
        self.nc_times = None
        self._syncing_nc = False

        default_origin = datetime(2020, 1, 1, 0, 0, 0)
        try:
            self._init_idx = max(0, int(current_index))
        except (TypeError, ValueError):
            self._init_idx = 0
        default_target = default_origin + timedelta(hours=self._init_idx)

        self.origin_var = tk.StringVar(value=default_origin.strftime("%Y-%m-%d %H:%M:%S"))
        self.step_val_var = tk.StringVar(value="1")
        self.step_unit_var = tk.StringVar(value="hours")
        self.target_var = tk.StringVar(value=default_target.strftime("%Y-%m-%d %H:%M:%S"))
        self.round_mode_var = tk.StringVar(value="Nearest")
        self.manual_mode_var = tk.BooleanVar(value=False)

        body = ttk.Frame(self, padding=14)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="NetCDF Start Date (Index 0):").grid(row=0, column=0, sticky=tk.W, pady=5, padx=(0, 8))
        self.origin_entry = ttk.Entry(body, textvariable=self.origin_var, width=26)
        self.origin_entry.grid(row=0, column=1, columnspan=2, sticky=tk.EW, pady=5)

        ttk.Label(body, text="Time Step (Δt per index):").grid(row=1, column=0, sticky=tk.W, pady=5, padx=(0, 8))
        step_fr = ttk.Frame(body)
        step_fr.grid(row=1, column=1, columnspan=2, sticky=tk.EW, pady=5)
        self.step_entry = ttk.Entry(step_fr, textvariable=self.step_val_var, width=10)
        self.step_entry.pack(side=tk.LEFT)
        self.step_unit_cb = ttk.Combobox(
            step_fr, textvariable=self.step_unit_var,
            values=list(self._UNIT_SECONDS.keys()), state="readonly", width=12,
        )
        self.step_unit_cb.pack(side=tk.LEFT, padx=(6, 10))
        ttk.Checkbutton(
            step_fr, text="Manual override", variable=self.manual_mode_var,
            command=self._toggle_manual_mode,
        ).pack(side=tk.LEFT)

        ttk.Label(body, text=f"Target Date ({target_label}):", font=("TkDefaultFont", 10, "bold")).grid(
            row=2, column=0, sticky=tk.W, pady=6, padx=(0, 8)
        )
        target_fr = ttk.Frame(body)
        target_fr.grid(row=2, column=1, columnspan=2, sticky=tk.EW, pady=6)
        self.target_entry = ttk.Entry(target_fr, textvariable=self.target_var, width=24)
        self.target_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(target_fr, text="Calculate", width=10, command=self._recalculate).pack(side=tk.LEFT, padx=(6, 0))

        ttk.Label(body, text="Rounding Mode:").grid(row=3, column=0, sticky=tk.W, pady=5, padx=(0, 8))
        ttk.Combobox(
            body, textvariable=self.round_mode_var,
            values=["Nearest", "Floor", "Ceil"], state="readonly", width=14,
        ).grid(row=3, column=1, sticky=tk.W, pady=5)

        self.nc_info_lbl = ttk.Label(
            body,
            text="Accepted formats: YYYY-MM-DD HH:MM:SS  or  YYYY-MM-DD",
            style="Hint.TLabel",
        )
        self.nc_info_lbl.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=(2, 8))

        self.result_lbl = ttk.Label(body, text="", font=("TkDefaultFont", 11, "bold"))
        self.result_lbl.grid(row=5, column=0, columnspan=3, sticky=tk.W, pady=(4, 2))
        self.detail_lbl = ttk.Label(body, text="", style="Hint.TLabel")
        self.detail_lbl.grid(row=6, column=0, columnspan=3, sticky=tk.W, pady=(0, 10))

        btns = ttk.Frame(body)
        btns.grid(row=7, column=0, columnspan=3, sticky=tk.EW, pady=(6, 0))
        if self.nc_path:
            ttk.Button(btns, text="Read from NetCDF", command=lambda: self._read_from_nc(silent=False, init_target=False)).pack(side=tk.LEFT)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=(6, 0))
        self.insert_btn = ttk.Button(btns, text=f"Insert into {target_label}", command=self._apply)
        self.insert_btn.pack(side=tk.RIGHT)

        for var in (self.origin_var, self.step_val_var, self.step_unit_var):
            var.trace_add("write", lambda *_a: self._on_manual_param_change())
        for var in (self.target_var, self.round_mode_var):
            var.trace_add("write", lambda *_a: self._recalculate())

        if self.nc_path and os.path.isfile(self.nc_path):
            self._read_from_nc(silent=True, init_target=True)
        self._update_field_states()
        self._recalculate()
        self.target_entry.focus_set()
        self.target_entry.selection_range(0, tk.END)

    def _update_field_states(self):
        using_nc = bool(self.nc_times) and not self.manual_mode_var.get()
        state_entry = "readonly" if using_nc else "normal"
        state_cb = "disabled" if using_nc else "readonly"
        self.origin_entry.configure(state=state_entry)
        self.step_entry.configure(state=state_entry)
        self.step_unit_cb.configure(state=state_cb)

    def _toggle_manual_mode(self):
        self._update_field_states()
        self._recalculate()

    def _on_manual_param_change(self):
        if not self._syncing_nc and self.manual_mode_var.get():
            self._recalculate()

    @classmethod
    def _parse_dt(cls, text):
        s = text.strip()
        for fmt in cls._DT_FORMATS:
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        raise ValueError(f"Unrecognized date/time: '{s}'")

    def _recalculate(self):
        try:
            target = self._parse_dt(self.target_var.get())
            mode = self.round_mode_var.get()

            if self.nc_times and not self.manual_mode_var.get():
                if mode == "Floor":
                    valid = [i for i, t in enumerate(self.nc_times) if t <= target]
                    if not valid:
                        self.calculated_index = None
                        self.result_lbl.configure(text="Out of range (< NetCDF start)", foreground="#DC2626")
                        self.detail_lbl.configure(text=f"NetCDF starts at {self.nc_times[0].strftime('%Y-%m-%d %H:%M:%S')}.")
                        self.insert_btn.configure(state=tk.DISABLED)
                        return
                    idx = valid[-1]
                elif mode == "Ceil":
                    valid = [i for i, t in enumerate(self.nc_times) if t >= target]
                    if not valid:
                        self.calculated_index = None
                        self.result_lbl.configure(text="Out of range (> NetCDF end)", foreground="#DC2626")
                        self.detail_lbl.configure(text=f"NetCDF ends at {self.nc_times[-1].strftime('%Y-%m-%d %H:%M:%S')}.")
                        self.insert_btn.configure(state=tk.DISABLED)
                        return
                    idx = valid[0]
                else:
                    idx = min(
                        range(len(self.nc_times)),
                        key=lambda i: abs((self.nc_times[i] - target).total_seconds()),
                    )

                self.calculated_index = idx
                exact_dt = self.nc_times[idx]
                diff_sec = (target - exact_dt).total_seconds()
                self.result_lbl.configure(text=f"Calculated Time Index: {idx}", foreground="#15803D")
                self.detail_lbl.configure(
                    text=f"NetCDF time[{idx}]: {exact_dt.strftime('%Y-%m-%d %H:%M:%S')}  (Δ = {diff_sec:+.0f} s)"
                )
                self.insert_btn.configure(state=tk.NORMAL)
                return

            origin = self._parse_dt(self.origin_var.get())
            step_val = float(self.step_val_var.get())
            if step_val <= 0:
                raise ValueError("Time step must be > 0.")
            dt_sec = step_val * self._UNIT_SECONDS[self.step_unit_var.get()]
            raw_idx = (target - origin).total_seconds() / dt_sec

            if mode == "Floor":
                idx = math.floor(raw_idx)
            elif mode == "Ceil":
                idx = math.ceil(raw_idx)
            else:
                idx = int(round(raw_idx))

            if idx < 0:
                self.calculated_index = None
                self.result_lbl.configure(text=f"Calculated Time Index: {idx} (invalid: < 0)", foreground="#DC2626")
                self.detail_lbl.configure(text="Target date is earlier than NetCDF Start Date (Index 0).")
                self.insert_btn.configure(state=tk.DISABLED)
                return

            self.calculated_index = idx
            exact_dt = origin + timedelta(seconds=idx * dt_sec)
            self.result_lbl.configure(text=f"Calculated Time Index: {idx}", foreground="#15803D")
            self.detail_lbl.configure(
                text=f"Exact step date: {exact_dt.strftime('%Y-%m-%d %H:%M:%S')}  (raw: {raw_idx:.3f})"
            )
            self.insert_btn.configure(state=tk.NORMAL)
        except Exception as exc:
            self.calculated_index = None
            self.result_lbl.configure(text=f"Error: {exc}", foreground="#DC2626")
            self.detail_lbl.configure(text="")
            self.insert_btn.configure(state=tk.DISABLED)

    def _read_from_nc(self, silent=False, init_target=True):
        if not os.path.isfile(self.nc_path):
            if not silent:
                messagebox.showwarning("NetCDF Not Found", f"Hydrodynamic NetCDF file not found:\n{self.nc_path}", parent=self)
            return
        try:
            import netCDF4
        except ImportError:
            if not silent:
                messagebox.showinfo(
                    "netCDF4 Not Installed",
                    "Optional package 'netCDF4' is not installed in this environment.\nEnter Start Date and Time Step manually.",
                    parent=self,
                )
            return
        try:
            with netCDF4.Dataset(self.nc_path, "r") as ds:
                tname = self.time_var_name if self.time_var_name in ds.variables else "time"
                if tname not in ds.variables:
                    raise KeyError(f"Time variable '{self.time_var_name}' not found in NetCDF.")
                tvar = ds.variables[tname]
                units = getattr(tvar, "units", "")
                cal = getattr(tvar, "calendar", "standard")
                raw_dates = netCDF4.num2date(tvar[:], units=units, calendar=cal)
                nc_times = [
                    datetime(d.year, d.month, d.day, d.hour, d.minute, d.second)
                    for d in raw_dates
                ]
            if not nc_times:
                raise ValueError("NetCDF time variable is empty.")

            self._syncing_nc = True
            try:
                self.nc_times = nc_times
                self.origin_var.set(nc_times[0].strftime("%Y-%m-%d %H:%M:%S"))
                if len(nc_times) >= 2:
                    sec = (nc_times[1] - nc_times[0]).total_seconds()
                    if sec > 0:
                        if sec % 86400 == 0:
                            self.step_val_var.set(str(int(sec // 86400)))
                            self.step_unit_var.set("days")
                        elif sec % 3600 == 0:
                            self.step_val_var.set(str(int(sec // 3600)))
                            self.step_unit_var.set("hours")
                        elif sec % 60 == 0:
                            self.step_val_var.set(str(int(sec // 60)))
                            self.step_unit_var.set("minutes")
                        else:
                            self.step_val_var.set(str(sec))
                            self.step_unit_var.set("seconds")
                if init_target or not self.target_var.get().strip():
                    clamped = min(self._init_idx, len(nc_times) - 1)
                    self.target_var.set(nc_times[clamped].strftime("%Y-%m-%d %H:%M:%S"))
                self.manual_mode_var.set(False)
                self.nc_info_lbl.configure(
                    text=f"NetCDF '{tname}': {nc_times[0].strftime('%Y-%m-%d %H:%M:%S')} → {nc_times[-1].strftime('%Y-%m-%d %H:%M:%S')} ({len(nc_times)} steps)"
                )
            finally:
                self._syncing_nc = False
            self._update_field_states()
            self._recalculate()
        except Exception as exc:
            if not silent:
                messagebox.showerror("NetCDF Read Error", str(exc), parent=self)

    def _apply(self):
        if self.calculated_index is not None:
            self.on_insert(self.calculated_index)
            self.destroy()

class NetCDFVariablesDialog(tk.Toplevel):

    def __init__(self, parent, nc_path, variables_info, dims_info):
        super().__init__(parent)
        self.title(f"NetCDF Variables — {os.path.basename(nc_path)}")
        self.geometry("900x500")
        self.minsize(720, 380)
        self.transient(parent)

        top = ttk.Frame(self, padding=10)
        top.pack(fill=tk.X)
        dims_str = ", ".join(f"{k}={v}" for k, v in dims_info.items())
        ttk.Label(
            top,
            text=f"File: {nc_path}\nVariables: {len(variables_info)}   |   Dimensions: {dims_str}",
            wraplength=860,
        ).pack(anchor=tk.W)

        tree_fr = ttk.Frame(self, padding=(10, 0, 10, 6))
        tree_fr.pack(fill=tk.BOTH, expand=True)
        cols = ("name", "dims", "shape", "dtype", "units", "long_name")
        tree = ttk.Treeview(tree_fr, columns=cols, show="headings", selectmode="browse")
        tree.heading("name", text="Variable")
        tree.heading("dims", text="Dimensions")
        tree.heading("shape", text="Shape")
        tree.heading("dtype", text="DType")
        tree.heading("units", text="Units")
        tree.heading("long_name", text="Long / Standard Name")
        tree.column("name", width=130)
        tree.column("dims", width=170)
        tree.column("shape", width=110)
        tree.column("dtype", width=80)
        tree.column("units", width=140)
        tree.column("long_name", width=230)

        sb = ttk.Scrollbar(tree_fr, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        for info in variables_info:
            tree.insert("", tk.END, values=(
                info["name"],
                info["dims"],
                info["shape"],
                info["dtype"],
                info["units"],
                info["long_name"],
            ))

        btns = ttk.Frame(self, padding=(10, 0, 10, 10))
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Close", command=self.destroy).pack(side=tk.RIGHT)

class StokesComputeDialog(tk.Toplevel):

    def __init__(self, parent, wind_nc_path, out_nc_path, lon_var, lat_var, u10_var, v10_var, c_stokes, on_complete):
        super().__init__(parent)
        self.title("Compute Stokes Drift from Winds")
        self.geometry("540x230")
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self.wind_nc_path = wind_nc_path
        self.out_nc_path = out_nc_path
        self.lon_var = lon_var
        self.lat_var = lat_var
        self.u10_var = u10_var
        self.v10_var = v10_var
        self.c_stokes = float(c_stokes)
        self.on_complete = on_complete
        self.cancelled = False
        self.completed = False
        self._queue = queue.Queue()

        body = ttk.Frame(self, padding=16)
        body.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            body,
            text=(
                f"Source Wind NetCDF: {os.path.basename(wind_nc_path)}\n"
                f"Output Stokes NetCDF: {os.path.basename(out_nc_path)}\n"
                f"Formula: ustokes = {self.c_stokes} * {u10_var},  vstokes = {self.c_stokes} * {v10_var}"
            ),
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 12))

        self.progress = ttk.Progressbar(body, orient=tk.HORIZONTAL, length=490, mode="determinate", maximum=100)
        self.progress.pack(fill=tk.X, pady=(0, 8))

        self.status_lbl = ttk.Label(body, text="0% — Starting...", style="Hint.TLabel")
        self.status_lbl.pack(anchor=tk.W, pady=(0, 14))

        btns = ttk.Frame(body)
        btns.pack(fill=tk.X)
        self.cancel_btn = ttk.Button(btns, text="Cancel", width=12, command=self._on_cancel)
        self.cancel_btn.pack(side=tk.RIGHT, padx=(8, 0))
        self.ok_btn = ttk.Button(btns, text="Ok", width=12, state=tk.DISABLED, command=self.destroy)
        self.ok_btn.pack(side=tk.RIGHT)

        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._worker.start()
        self.after(40, self._poll_queue)

    def _poll_queue(self):
        if not self.winfo_exists():
            return
        finished = False
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == "progress":
                    self._update_progress(item[1], item[2])
                elif kind == "done":
                    self._finish_success()
                    finished = True
                elif kind == "cancel":
                    self._finish_cancelled()
                    finished = True
                elif kind == "error":
                    self._finish_error(item[1])
                    finished = True
        except queue.Empty:
            pass
        if not finished and self.winfo_exists():
            self.after(40, self._poll_queue)

    def _on_cancel(self):
        if self.completed:
            self.destroy()
            return
        self.cancelled = True
        self.status_lbl.configure(text="Cancelling...")
        self.cancel_btn.configure(state=tk.DISABLED)

    def _update_progress(self, pct, msg):
        if self.winfo_exists():
            self.progress["value"] = pct
            self.status_lbl.configure(text=f"{pct:.0f}% — {msg}")

    def _finish_cancelled(self):
        if os.path.isfile(self.out_nc_path):
            try:
                os.remove(self.out_nc_path)
            except OSError:
                pass
        if self.winfo_exists():
            self.destroy()

    def _finish_success(self):
        self.completed = True
        if self.winfo_exists():
            self.progress["value"] = 100
            self.status_lbl.configure(text=f"100% — Created {os.path.basename(self.out_nc_path)}")
            self.ok_btn.configure(state=tk.NORMAL)
            self.cancel_btn.configure(state=tk.DISABLED)
            self.ok_btn.focus_set()
        self.on_complete()

    def _finish_error(self, err_msg):
        if os.path.isfile(self.out_nc_path):
            try:
                os.remove(self.out_nc_path)
            except OSError:
                pass
        if self.winfo_exists():
            messagebox.showerror("Stokes Computation Error", err_msg, parent=self)
            self.destroy()

    def _run_worker(self):
        try:
            import netCDF4
            import numpy as np

            os.makedirs(os.path.dirname(self.out_nc_path), exist_ok=True)
            with netCDF4.Dataset(self.wind_nc_path, "r") as src, netCDF4.Dataset(self.out_nc_path, "w") as dst:
                u_in = src.variables[self.u10_var]
                v_in = src.variables[self.v10_var]

                needed_dims = list(dict.fromkeys(
                    list(u_in.dimensions)
                    + list(src.variables[self.lon_var].dimensions)
                    + list(src.variables[self.lat_var].dimensions)
                ))
                for dname in needed_dims:
                    dim = src.dimensions[dname]
                    dst.createDimension(dname, None if dim.isunlimited() else len(dim))

                coord_names = list(dict.fromkeys(
                    [self.lon_var, self.lat_var]
                    + [d for d in needed_dims if d in src.variables and src.variables[d].ndim == 1]
                ))
                for cname in coord_names:
                    c_src = src.variables[cname]
                    c_dst = dst.createVariable(cname, c_src.dtype, c_src.dimensions)
                    for attr in c_src.ncattrs():
                        if attr != "_FillValue":
                            setattr(c_dst, attr, getattr(c_src, attr))
                    c_dst[:] = c_src[:]

                fill_val = np.float32(np.nan)
                u_out = dst.createVariable("ustokes", "f4", u_in.dimensions, fill_value=fill_val)
                u_out.units = "m s-1"
                u_out.standard_name = "sea_surface_wave_stokes_drift_x_velocity"
                u_out.long_name = "Eastward surface Stokes drift computed from wind"

                v_out = dst.createVariable("vstokes", "f4", v_in.dimensions, fill_value=fill_val)
                v_out.units = "m s-1"
                v_out.standard_name = "sea_surface_wave_stokes_drift_y_velocity"
                v_out.long_name = "Northward surface Stokes drift computed from wind"

                dst.title = f"Stokes drift computed from {os.path.basename(self.wind_nc_path)}"
                dst.stokes_wind_coef = self.c_stokes

                total_steps = u_in.shape[0] if u_in.ndim >= 1 else 1
                chunk = max(1, total_steps // 50)
                if u_in.ndim >= 2:
                    for start in range(0, total_steps, chunk):
                        if self.cancelled:
                            self._queue.put(("cancel",))
                            return
                        end = min(total_steps, start + chunk)
                        u_chunk = np.asarray(u_in[start:end], dtype=np.float32)
                        v_chunk = np.asarray(v_in[start:end], dtype=np.float32)
                        u_out[start:end] = u_chunk * np.float32(self.c_stokes)
                        v_out[start:end] = v_chunk * np.float32(self.c_stokes)
                        pct = (end / total_steps) * 100.0
                        self._queue.put(("progress", pct, f"Step {end} / {total_steps}"))
                else:
                    u_out[:] = np.asarray(u_in[:], dtype=np.float32) * np.float32(self.c_stokes)
                    v_out[:] = np.asarray(v_in[:], dtype=np.float32) * np.float32(self.c_stokes)

            if self.cancelled:
                self._queue.put(("cancel",))
            else:
                self._queue.put(("done",))
        except Exception as exc:
            self._queue.put(("error", str(exc)))

class SPartAConfigApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SPartA-config v3.0 — Configuration Editor")
        self.geometry("1260x840")
        self.minsize(1080, 700)

        self._increase_all_fonts(delta=2)

        self.current_path = None
        self.raw_data = json.loads(json.dumps(DEFAULT_CONFIG))
        self.field_specs = {}
        self.field_widgets = {}
        self.sample_map = {}
        self.tab_names = self._discover_tab_names()

        self._build_ui()
        self._load_samples_list()

        if "test3.conf" in self.sample_map:
            self.sample_var.set("test3.conf")
            self.load_file(self.sample_map["test3.conf"])
        elif self.sample_map:
            first = next(iter(self.sample_map))
            self.sample_var.set(first)
            self.load_file(self.sample_map[first])
        else:
            self._populate_fields(self.raw_data)

    def _increase_all_fonts(self, delta=2):
        for fname in ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont", "TkHeadingFont"):
            try:
                f = tkfont.nametofont(fname)
                sz = f.cget("size")
                new_sz = (sz - delta) if sz < 0 else (sz + delta)
                f.configure(size=new_sz)
            except tk.TclError:
                pass

    def _discover_tab_names(self):
        names = set()
        for d in (PROJECT_ROOT, APP_DIR, os.path.join(PROJECT_ROOT, "SPartA-GUI")):
            for p in glob.glob(os.path.join(d, "*.tab")):
                names.add(os.path.basename(p))
        return sorted(names) or ["vivid_contrast.tab", "mixedcolors.tab"]

    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Header.TLabel", font=("TkDefaultFont", 13, "bold"), foreground="#1E3A5F")
        style.configure("Hint.TLabel", foreground="#64748B", font=("TkDefaultFont", 11))
        style.configure("Treeview", rowheight=26)
        style.configure(
            "TEntry",
            fieldbackground="#FFFFFF",
            foreground="#0F172A",
            insertcolor="#000000",
            insertwidth=2,
        )
        style.configure(
            "TSpinbox",
            fieldbackground="#FFFFFF",
            foreground="#0F172A",
            insertcolor="#000000",
            insertwidth=2,
        )
        self.option_add("*TEntry.cursor", "xterm")
        self.option_add("*TSpinbox.cursor", "xterm")
        self.option_add("*Entry.insertBackground", "#000000")
        self.option_add("*Entry.insertWidth", 2)

        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Default", command=self.new_config, accelerator="Ctrl+N")
        file_menu.add_command(label="Open .conf...", command=self.open_dialog, accelerator="Ctrl+O")
        file_menu.add_command(label="Save", command=self.save_file, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As...", command=self.save_as_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        self.config(menu=menubar)

        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="New", command=self.new_config, width=7).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="Open...", command=self.open_dialog, width=8).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="Save", command=self.save_file, width=8).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="Save As...", command=self.save_as_dialog, width=9).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Label(toolbar, text="Sample (.conf):").pack(side=tk.LEFT)
        self.sample_var = tk.StringVar()
        self.sample_combo = ttk.Combobox(toolbar, textvariable=self.sample_var, state="readonly", width=18)
        self.sample_combo.pack(side=tk.LEFT, padx=(4, 12))
        self.sample_combo.bind("<<ComboboxSelected>>", self._on_sample_selected)

        ttk.Button(toolbar, text="Validate", command=self.validate_only, width=9).pack(side=tk.RIGHT)

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_general_tab()
        self._build_inputs_tab()
        self._build_physics_tab()
        self._build_time_coeffs_tab()
        self._build_outputs_analysis_tab()
        self._build_plots_tab()
        self._build_json_tab()

        status_frame = ttk.Frame(self, padding=(10, 4))
        status_frame.pack(fill=tk.X)
        self.status_var = tk.StringVar(value="Ready.")
        self.path_var = tk.StringVar(value="Unsaved configuration")
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self.path_var, style="Hint.TLabel").pack(side=tk.RIGHT)

        self.bind("<Control-o>", lambda _e: self.open_dialog())
        self.bind("<Control-s>", lambda _e: self.save_file())
        self.bind("<Control-n>", lambda _e: self.new_config())

    def _add_row(self, parent, row_idx, section, key, label, kind="str", hint="", values=None, browse=None, extra_btn=None, extra_btn2=None):
        ttk.Label(parent, text=label, width=max(28, len(label)), anchor=tk.W).grid(row=row_idx, column=0, sticky=tk.W, pady=4, padx=(0, 8))

        if kind == "bool_int":
            var = tk.IntVar(value=0)
            widget = ttk.Checkbutton(parent, variable=var, onvalue=1, offvalue=0, text="Enabled (1)")
            widget.grid(row=row_idx, column=1, sticky=tk.W, pady=4, padx=(0, 8))
        elif kind == "combo":
            var = tk.StringVar()
            widget = ttk.Combobox(parent, textvariable=var, values=values or [], state="readonly", width=44)
            widget.grid(row=row_idx, column=1, sticky=tk.EW, pady=4, padx=(0, 8))
        else:
            var = tk.StringVar()
            widget = ttk.Entry(parent, textvariable=var, width=48)
            widget.grid(row=row_idx, column=1, sticky=tk.EW, pady=4, padx=(0, 8))

        if browse:
            ttk.Button(
                parent, text="Browse...", width=10,
                command=lambda v=var, b=browse, s=section: self._browse_for(v, b, section=s)
            ).grid(row=row_idx, column=2, padx=(4, 0), pady=4, sticky=tk.W)

        if extra_btn:
            btn_text, btn_cb = extra_btn
            col = 3 if browse else 2
            ttk.Button(
                parent, text=btn_text, width=max(16, len(btn_text) + 1),
                command=btn_cb
            ).grid(row=row_idx, column=col, padx=(6 if col == 3 else 4, 0), pady=4, sticky=tk.W)

        if extra_btn2:
            btn_text2, btn_cb2 = extra_btn2
            ttk.Button(
                parent, text=btn_text2, width=17,
                command=btn_cb2
            ).grid(row=row_idx, column=3, padx=(6, 0), pady=4, sticky=tk.W)

        if hint:
            ttk.Label(parent, text=hint, style="Hint.TLabel").grid(
                row=row_idx, column=4, sticky=tk.W, padx=(12, 0), pady=4
            )

        self.field_specs[(section, key)] = (var, kind)
        self.field_widgets[(section, key)] = widget
        return row_idx + 1

    def _resolve_section_dir(self, section):
        dir_key = "input_directory" if section == "Inputs" else ("output_directory" if section == "Outputs" else None)
        if not dir_key or (section, dir_key) not in self.field_specs:
            return None
        raw = self.field_specs[(section, dir_key)][0].get().strip()
        if not raw:
            return None
        if os.path.isabs(raw):
            return os.path.normpath(raw)
        return os.path.normpath(os.path.join(PROJECT_ROOT, raw))

    def _browse_for(self, var, mode, section=None):
        base_dir = self._resolve_section_dir(section)
        fallback_dir = os.path.join(PROJECT_ROOT, "samples")
        init_dir = base_dir if (base_dir and os.path.isdir(base_dir)) else fallback_dir

        if mode == "dir":
            cur = var.get().strip()
            cur_abs = cur if os.path.isabs(cur) else (os.path.normpath(os.path.join(PROJECT_ROOT, cur)) if cur else PROJECT_ROOT)
            start_dir = cur_abs if os.path.isdir(cur_abs) else PROJECT_ROOT
            chosen = filedialog.askdirectory(initialdir=start_dir)
            if chosen:
                try:
                    rel = os.path.relpath(chosen, PROJECT_ROOT)
                    if not rel.startswith(".."):
                        chosen = rel
                except ValueError:
                    pass
                chosen = chosen.replace("\\", "/")
                if not chosen.endswith("/"):
                    chosen += "/"
                var.set(chosen)
        elif mode == "save":
            cur_name = os.path.basename(var.get().strip()) if var.get().strip() else ""
            chosen = filedialog.asksaveasfilename(initialdir=init_dir, initialfile=cur_name)
            if chosen:
                if base_dir:
                    try:
                        rel = os.path.relpath(chosen, base_dir)
                        if not rel.startswith(".."):
                            var.set(rel.replace("\\", "/"))
                            return
                    except ValueError:
                        pass
                var.set(chosen.replace("\\", "/") if os.path.isabs(chosen) else chosen)
        else:
            chosen = filedialog.askopenfilename(initialdir=init_dir)
            if chosen:
                if base_dir:
                    try:
                        rel = os.path.relpath(chosen, base_dir)
                        if not rel.startswith(".."):
                            var.set(rel.replace("\\", "/"))
                            return
                    except ValueError:
                        pass
                var.set(os.path.basename(chosen) if not base_dir else chosen.replace("\\", "/"))

    def _get_study_region_list(self):
        raw = self.field_specs[("Plots", "study_region")][0].get()
        try:
            vals = [float(x.strip()) for x in raw.split(",") if x.strip()]
            return vals if len(vals) == 4 else [-40.0, -10.0, -22.0, 0.0]
        except ValueError:
            return [-40.0, -10.0, -22.0, 0.0]

    def _open_region_map_selector(self):
        init_reg = self._get_study_region_list()
        def _apply(reg):
            self.field_specs[("Plots", "study_region")][0].set(", ".join(str(x) for x in reg))
            self.status_var.set(f"Study region updated: {reg}")
        try:
            MapRegionSelectorDialog(self, init_reg, _apply)
        except Exception as exc:
            messagebox.showerror("Map Selector Error", str(exc))

    def _open_residence_map_selector(self):
        raw = self.field_specs[("Physics", "residence_bbox")][0].get()
        try:
            vals = [float(x.strip()) for x in raw.split(",") if x.strip()]
            init_reg = vals if len(vals) == 4 else self._get_study_region_list()
        except ValueError:
            init_reg = self._get_study_region_list()

        def _apply(reg):
            self.field_specs[("Physics", "residence_bbox")][0].set(", ".join(str(x) for x in reg))
            self.status_var.set(f"Residence BBox updated: {reg}")
        try:
            MapRegionSelectorDialog(self, init_reg, _apply)
        except Exception as exc:
            messagebox.showerror("Map Selector Error", str(exc))

    def _open_particles_editor(self):
        inp_dir = self.field_specs[("Inputs", "input_directory")][0].get().strip()
        p_file = self.field_specs[("Inputs", "particles_file")][0].get().strip() or "particles.csv"
        full_path = resolve_input_file(inp_dir, p_file)
        ParticleCSVEditorDialog(self, full_path, self._get_study_region_list())

    def _open_objects_editor(self):
        inp_dir = self.field_specs[("Inputs", "input_directory")][0].get().strip()
        o_file = self.field_specs[("Inputs", "objects_files")][0].get().strip() or "objects.obj"
        full_path = resolve_input_file(inp_dir, o_file)
        MapObjectsEditorDialog(self, full_path, self._get_study_region_list())

    def _resolve_inputs_nc(self, file_key, file_label):
        inp_dir = self.field_specs[("Inputs", "input_directory")][0].get().strip()
        if not inp_dir:
            messagebox.showerror(
                "Missing Input Directory",
                "Please specify 'Input Directory' before reading NetCDF variables.",
            )
            return None
        nc_file = self.field_specs[("Inputs", file_key)][0].get().strip()
        if not nc_file:
            messagebox.showerror(
                "Missing NetCDF File",
                f"Please specify '{file_label}' before reading NetCDF variables.",
            )
            return None
        full_path = resolve_input_file(inp_dir, nc_file)
        if not os.path.isfile(full_path):
            messagebox.showerror(
                "NetCDF File Not Found",
                f"The specified NetCDF file does not exist:\n{full_path}",
            )
            return None
        return full_path

    @staticmethod
    def _read_nc_metadata(nc_path):
        try:
            import netCDF4
        except ImportError:
            messagebox.showerror(
                "netCDF4 Not Installed",
                "The 'netCDF4' package is required to inspect NetCDF files.",
            )
            return None, None
        try:
            with netCDF4.Dataset(nc_path, "r") as ds:
                dims_info = {k: len(v) for k, v in ds.dimensions.items()}
                vars_info = []
                for name, var in ds.variables.items():
                    units = str(getattr(var, "units", "") or "")
                    long_name = str(getattr(var, "long_name", "") or getattr(var, "standard_name", "") or "")
                    std_name = str(getattr(var, "standard_name", "") or "")
                    axis = str(getattr(var, "axis", "") or "")
                    vars_info.append({
                        "name": name,
                        "dims": ", ".join(var.dimensions),
                        "shape": " x ".join(str(s) for s in var.shape),
                        "dtype": str(var.dtype),
                        "units": units,
                        "long_name": long_name,
                        "standard_name": std_name,
                        "axis": axis,
                    })
                return vars_info, dims_info
        except Exception as exc:
            messagebox.showerror("NetCDF Read Error", f"Failed to read '{nc_path}':\n{exc}")
            return None, None

    def _view_vars_from_nc(self, file_key, file_label):
        nc_path = self._resolve_inputs_nc(file_key, file_label)
        if not nc_path:
            return
        vars_info, dims_info = self._read_nc_metadata(nc_path)
        if vars_info is not None:
            NetCDFVariablesDialog(self, nc_path, vars_info, dims_info)

    def _get_vars_from_nc(self, file_key, file_label, param_key):
        nc_path = self._resolve_inputs_nc(file_key, file_label)
        if not nc_path:
            return
        vars_info, _dims = self._read_nc_metadata(nc_path)
        if vars_info is None:
            return

        def _pick(candidates, std_hints=(), axis_hint=None, unit_hints=()):
            by_lower = {v["name"].lower(): v["name"] for v in vars_info}
            for cand in candidates:
                if cand.lower() in by_lower:
                    return by_lower[cand.lower()]
            for v in vars_info:
                if axis_hint and v["axis"].upper() == axis_hint:
                    return v["name"]
            for v in vars_info:
                sn = v["standard_name"].lower()
                if any(h in sn for h in std_hints):
                    return v["name"]
            for v in vars_info:
                un = v["units"].lower()
                if any(h in un for h in unit_hints):
                    return v["name"]
            return None

        lon = _pick(["lon", "longitude", "lon_u", "nav_lon", "x"], ("longitude",), "X", ("degrees_east",))
        lat = _pick(["lat", "latitude", "lat_u", "nav_lat", "y"], ("latitude",), "Y", ("degrees_north",))
        time_v = _pick(["time", "t", "time_counter"], ("time",), "T", (" since ",))

        if param_key == "htd_paramlist":
            u = _pick(["water_u", "uo", "u", "u_curr", "eastward_sea_water_velocity"], ("eastward_sea_water_velocity", "sea_water_x_velocity"))
            v = _pick(["water_v", "vo", "v", "v_curr", "northward_sea_water_velocity"], ("northward_sea_water_velocity", "sea_water_y_velocity"))
            slots = [("lon", lon), ("lat", lat), ("time", time_v), ("u", u), ("v", v)]
        elif param_key == "swp_paramlist":
            temp = _pick(["water_temp", "thetao", "temp", "temperature", "to", "sst"], ("sea_water_temperature", "sea_water_potential_temperature"))
            sal = _pick(["salinity", "so", "sal", "salt"], ("sea_water_salinity", "sea_water_practical_salinity"))
            slots = [("lon", lon), ("lat", lat), ("time", time_v), ("temp", temp), ("salinity", sal)]
        elif param_key == "wind_paramlist":
            u10 = _pick(["u10", "uwnd", "u_wind", "u10m", "u", "eastward_wind"], ("eastward_wind",))
            v10 = _pick(["v10", "vwnd", "v_wind", "v10m", "v", "northward_wind"], ("northward_wind",))
            slots = [("lon", lon), ("lat", lat), ("time", time_v), ("u10", u10), ("v10", v10)]
        else:
            us = _pick(["ustokes", "uuss", "u_stokes", "vsdx", "stokes_u"], ("stokes_drift_x_velocity",))
            vs = _pick(["vstokes", "vuss", "v_stokes", "vsdy", "stokes_v"], ("stokes_drift_y_velocity",))
            slots = [("lon", lon), ("lat", lat), ("time", time_v), ("ustokes", us), ("vstokes", vs)]

        found = [val for _lbl, val in slots if val]
        missing = [lbl for lbl, val in slots if not val]
        if found:
            self.field_specs[("Inputs", param_key)][0].set(", ".join(found))
        if missing:
            messagebox.showwarning(
                "Partial Variable Detection",
                f"Could not auto-detect: {', '.join(missing)}.\n"
                f"Detected: {', '.join(found) or '(none)'}\n\n"
                "Use 'View from NetCDF' to inspect all variable names.",
            )
        else:
            self.status_var.set(f"{param_key} updated from {os.path.basename(nc_path)}: {', '.join(found)}")

    def _compute_stokes_from_winds(self):
        wind_nc_path = self._resolve_inputs_nc("wind_file", "Wind NetCDF")
        if not wind_nc_path:
            return
        vars_info, _dims = self._read_nc_metadata(wind_nc_path)
        if vars_info is None:
            return

        available = {v["name"] for v in vars_info}
        def _extract_wind_4(parts):
            if len(parts) >= 5 and all(v in available for v in parts[:5]):
                return parts[0], parts[1], parts[3], parts[4]
            if len(parts) == 4 and all(v in available for v in parts[:4]):
                return parts[0], parts[1], parts[2], parts[3]
            return None

        raw_wind_vars = [x.strip() for x in self.field_specs[("Inputs", "wind_paramlist")][0].get().split(",") if x.strip()]
        picked = _extract_wind_4(raw_wind_vars)
        if not picked:
            self._get_vars_from_nc("wind_file", "Wind NetCDF", "wind_paramlist")
            raw_wind_vars = [x.strip() for x in self.field_specs[("Inputs", "wind_paramlist")][0].get().split(",") if x.strip()]
            picked = _extract_wind_4(raw_wind_vars)
            if not picked:
                messagebox.showerror(
                    "Missing Wind Variables",
                    "Could not identify wind variables (lon, lat, [time,] u10, v10) in the Wind NetCDF.\n"
                    "Please check 'Wind Vars (list)' or use 'View from NetCDF'.",
                )
                return
        lon_var, lat_var, u10_var, v10_var = picked

        try:
            c_stokes = float(self.field_specs[("Physics", "stokes_wind_coef")][0].get() or 0.015)
        except ValueError:
            c_stokes = 0.015

        wind_rel = self.field_specs[("Inputs", "wind_file")][0].get().strip()
        wind_dir_rel = os.path.dirname(wind_rel)
        wind_stem = os.path.splitext(os.path.basename(wind_nc_path))[0]
        out_name = f"stokes_{wind_stem}.nc"
        out_rel = os.path.join(wind_dir_rel, out_name).replace("\\", "/") if wind_dir_rel else out_name
        out_nc_path = os.path.join(os.path.dirname(wind_nc_path), out_name)

        def _on_complete():
            self.field_specs[("Inputs", "stokes_file")][0].set(out_rel)
            time_part = next((v["name"] for v in vars_info if v["axis"].upper() == "T" or v["name"].lower() in ("time", "t", "time_counter")), None)
            if time_part:
                self.field_specs[("Inputs", "stokes_paramlist")][0].set(f"{lon_var}, {lat_var}, {time_part}, ustokes, vstokes")
            else:
                self.field_specs[("Inputs", "stokes_paramlist")][0].set(f"{lon_var}, {lat_var}, ustokes, vstokes")
            self.status_var.set(f"Computed Stokes Drift NetCDF: {out_rel}")

        StokesComputeDialog(
            self,
            wind_nc_path,
            out_nc_path,
            lon_var,
            lat_var,
            u10_var,
            v10_var,
            c_stokes,
            _on_complete,
        )

    def _open_time_index_calculator(self, key, label):
        inp_dir = self.field_specs[("Inputs", "input_directory")][0].get().strip()
        nc_file = self.field_specs[("Inputs", "hydrodynamic_file")][0].get().strip()
        nc_path = resolve_input_file(inp_dir, nc_file) if nc_file else ""
        htd_raw = self.field_specs[("Inputs", "htd_paramlist")][0].get()
        htd_parts = [p.strip() for p in htd_raw.split(",") if p.strip()]
        time_var = htd_parts[2] if len(htd_parts) >= 3 else "time"
        current_val = self.field_specs[("Parameters", key)][0].get()

        def _insert(idx):
            self.field_specs[("Parameters", key)][0].set(str(idx))
            self.status_var.set(f"{label} set to {idx}")

        TimeIndexCalculatorDialog(self, label, current_val, _insert, nc_path=nc_path, time_var_name=time_var)

    def _build_general_tab(self):
        sf = ScrollableFrame(self.notebook)
        self.notebook.add(sf, text="General & Numerical")
        p = sf.inner
        p.columnconfigure(1, weight=3, minsize=380)

        ttk.Label(p, text="General", style="Header.TLabel").grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 6))
        r = 1
        r = self._add_row(p, r, "General", "model_name", "Model Name", "str", "Run identifier (e.g., TEST3)")
        r = self._add_row(p, r, "General", "description", "Description", "str", "Human-readable simulation notes")
        r = self._add_row(p, r, "General", "model_type", "Model Type", "combo", "One of the 18 implemented models", values=MODEL_TYPES)
        r = self._add_row(p, r, "General", "verbose", "Verbose Level", "combo", "0 = silent, 1 = normal, 2 = detailed", values=["0", "1", "2"])

        ttk.Separator(p, orient=tk.HORIZONTAL).grid(row=r, column=0, columnspan=5, sticky=tk.EW, pady=12)
        r += 1
        ttk.Label(p, text="Numerical Methods", style="Header.TLabel").grid(row=r, column=0, columnspan=4, sticky=tk.W, pady=(0, 6))
        r += 1
        r = self._add_row(p, r, "Numerical_methods", "interpolation_method", "Interpolation Method", "combo", "scipy.interpolate.griddata", values=INTERP_METHODS)
        r = self._add_row(p, r, "Numerical_methods", "auxiliary_interpolation_method", "Auxiliary Method (k-NN)", "combo", "cKDTree fallback (k4, k12, k16)", values=AUX_INTERP_METHODS)

    def _build_inputs_tab(self):
        sf = ScrollableFrame(self.notebook)
        self.notebook.add(sf, text="Inputs")
        p = sf.inner
        p.columnconfigure(1, weight=3, minsize=380)

        ttk.Label(p, text="Input Files & Variable Mapping", style="Header.TLabel").grid(row=0, column=0, columnspan=5, sticky=tk.W, pady=(0, 6))
        r = 1
        r = self._add_row(p, r, "Inputs", "input_directory", "Input Directory", "str", "Base folder for input files", browse="dir")
        r = self._add_row(p, r, "Inputs", "hydrodynamic_file", "Hydrodynamic NetCDF", "str", "Ocean currents file (u, v)", browse="file")
        r = self._add_row(
            p, r, "Inputs", "htd_paramlist", "Hydrodynamic Vars (list)", "str_list",
            "Comma-separated: lon, lat, time, water_u, water_v",
            extra_btn=("Get from NetCDF", lambda: self._get_vars_from_nc("hydrodynamic_file", "Hydrodynamic NetCDF", "htd_paramlist")),
            extra_btn2=("View from NetCDF", lambda: self._view_vars_from_nc("hydrodynamic_file", "Hydrodynamic NetCDF")),
        )
        r = self._add_row(p, r, "Inputs", "seawater_properties_file", "Seawater Properties NetCDF", "str", "Optional T/S NetCDF", browse="file")
        r = self._add_row(
            p, r, "Inputs", "swp_paramlist", "Seawater Vars (list)", "str_list",
            "Comma-separated: lon, lat, time, water_temp, salinity",
            extra_btn=("Get from NetCDF", lambda: self._get_vars_from_nc("seawater_properties_file", "Seawater Properties NetCDF", "swp_paramlist")),
            extra_btn2=("View from NetCDF", lambda: self._view_vars_from_nc("seawater_properties_file", "Seawater Properties NetCDF")),
        )
        r = self._add_row(p, r, "Inputs", "wind_file", "Wind NetCDF", "str", "Optional wind file (u10, v10)", browse="file")
        r = self._add_row(
            p, r, "Inputs", "wind_paramlist", "Wind Vars (list)", "str_list",
            "Comma-separated: lon, lat, time, u10, v10",
            extra_btn=("Get from NetCDF", lambda: self._get_vars_from_nc("wind_file", "Wind NetCDF", "wind_paramlist")),
            extra_btn2=("View from NetCDF", lambda: self._view_vars_from_nc("wind_file", "Wind NetCDF")),
        )
        r = self._add_row(
            p, r, "Inputs", "stokes_file", "Stokes Drift NetCDF", "str",
            "Optional Stokes drift NetCDF", browse="file",
            extra_btn=("Compute from Winds", self._compute_stokes_from_winds),
        )
        r = self._add_row(
            p, r, "Inputs", "stokes_paramlist", "Stokes Vars (list)", "str_list",
            "Comma-separated: lon, lat, time, ustokes, vstokes",
            extra_btn=("Get from NetCDF", lambda: self._get_vars_from_nc("stokes_file", "Stokes Drift NetCDF", "stokes_paramlist")),
            extra_btn2=("View from NetCDF", lambda: self._view_vars_from_nc("stokes_file", "Stokes Drift NetCDF")),
        )
        r = self._add_row(
            p, r, "Inputs", "particles_file", "Particles CSV", "str",
            "Initial particle release CSV", browse="file",
            extra_btn=("Edit CSV...", self._open_particles_editor)
        )
        r = self._add_row(p, r, "Inputs", "active_particles", "Active Particles", "str", "'all' or list/range")
        r = self._add_row(p, r, "Inputs", "coast_file", "Coastline File (.shp/.bln)", "str", "Optional coastline boundary", browse="file")
        r = self._add_row(
            p, r, "Inputs", "objects_files", "Map Objects File (.obj)", "str",
            "Overlay markers (e.g., islands.obj)", browse="file",
            extra_btn=("Edit .obj...", self._open_objects_editor)
        )

    def _build_physics_tab(self):
        sf = ScrollableFrame(self.notebook)
        self.notebook.add(sf, text="Physics")
        p = sf.inner
        p.columnconfigure(1, weight=3, minsize=380)

        groups = [
            ("Core Transport & Dispersion", [
                ("invert_vector_fields", "Invert Vector Fields", "bool_int", "0 = forward, 1 = backtracking"),
                ("compute_transport", "Compute Transport", "bool_int", "1 = enable advection"),
                ("seawater_properties", "Use Seawater Properties", "bool_int", "1 = enable EOS-80 density"),
                ("horizdiff", "Horizontal Diffusivity", "number", "m²/s (e.g., 100)"),
                ("currcoef", "Current Coefficient", "float", "Advection multiplier (e.g., 1.0)"),
                ("windwavecoef", "Wind/Wave Coefficient", "float", "Wind drift factor"),
                ("leeway_angle", "Leeway Angle", "float", "Degrees"),
                ("stokes_wind_coef", "Stokes Wind Coef", "float", "Stokes multiplier (e.g., 0.015)"),
                ("random_term", "Random Term", "bool_int", "1 = enable turbulent diffusion"),
                ("rt_method", "Random Method", "combo", "Diffusion algorithm", RT_METHODS),
            ]),
            ("Larvae (LARVAE)", [
                ("larvae_u_active", "Active Swimming u", "float", "m/s"),
                ("larvae_v_active", "Active Swimming v", "float", "m/s"),
                ("larvae_pld", "Pelagic Larval Duration", "int", "Seconds or steps"),
                ("larvae_mortality_rate", "Mortality Rate", "float", "1/s"),
            ]),
            ("Microplastics, Sargassum & Debris", [
                ("plastic_density", "Plastic Density", "float", "kg/m³ (e.g., 920.0)"),
                ("biofouling_rate", "Biofouling Rate", "float", "kg/m³/s"),
                ("sargassum_biomass_init", "Sargassum Initial Biomass", "float", "kg"),
                ("sargassum_growth_rate", "Sargassum Growth Rate", "float", "1/s"),
                ("sargassum_mortality_rate", "Sargassum Mortality Rate", "float", "1/s"),
                ("debris_windage", "Debris Windage", "float", "Windage factor (e.g., 0.02)"),
            ]),
            ("Icebergs (ICEFLOES)", [
                ("ice_volume_init", "Initial Ice Volume", "float", "m³"),
                ("ice_u_grad", "Ice u Gradient", "float", "m/s"),
                ("ice_v_grad", "Ice v Gradient", "float", "m/s"),
                ("ice_coriolis_coef", "Ice Coriolis Coef", "float", "Multiplier"),
                ("ice_ablation_basal", "Basal Ablation", "float", "Rate"),
                ("ice_ablation_lateral", "Lateral Ablation", "float", "Rate"),
                ("ice_ablation_thermal", "Thermal Ablation", "float", "Rate"),
            ]),
            ("Decay, Residence, Okubo & Subsurface", [
                ("decay_rate", "Decay Rate (λ)", "float", "1/s (DECAY_TRACER)"),
                ("decay_min_threshold", "Min Threshold (C_min)", "float", "Stop criterion (DECAY_TRACER)"),
                ("residence_bbox", "Residence BBox [4]", "num_list", "[lon_min, lon_max, lat_min, lat_max]"),
                ("okubo_ref_length", "Okubo Ref Length (l0)", "float", "m (e.g., 1000.0)"),
                ("subsurface_depth_init", "Initial Depth (z0)", "float", "m (SUBSURFACE)"),
                ("subsurface_settling_rate", "Settling Rate (w)", "float", "m/s (SUBSURFACE)"),
                ("subsurface_max_depth", "Max Depth (z_max)", "float", "m (SUBSURFACE)"),
            ]),
        ]

        r = 0
        for grp_title, items in groups:
            ttk.Label(p, text=grp_title, style="Header.TLabel").grid(row=r, column=0, columnspan=4, sticky=tk.W, pady=(8 if r > 0 else 0, 4))
            r += 1
            for item in items:
                key, lbl, kind, hint = item[:4]
                vals = item[4] if len(item) > 4 else None
                extra = ("Select on Map...", self._open_residence_map_selector) if key == "residence_bbox" else None
                r = self._add_row(p, r, "Physics", key, lbl, kind, hint, values=vals, extra_btn=extra)
                if key == "windwavecoef":
                    auto_var = tk.IntVar(value=0)
                    ttk.Checkbutton(
                        p, text="Automatic", variable=auto_var, onvalue=1, offvalue=0,
                    ).grid(row=r - 1, column=2, padx=(4, 0), pady=4, sticky=tk.W)
                    self.field_specs[("Physics", "windwavecoef_automatic")] = (auto_var, "bool_int")

                    def _sync_ww_state(*_args, av=auto_var):
                        w = self.field_widgets.get(("Physics", "windwavecoef"))
                        if w is not None:
                            w.configure(state="disabled" if av.get() == 1 else "normal")

                    auto_var.trace_add("write", _sync_ww_state)
                    _sync_ww_state()

    def _build_time_coeffs_tab(self):
        sf = ScrollableFrame(self.notebook)
        self.notebook.add(sf, text="Time & Coeffs")
        p = sf.inner
        p.columnconfigure(1, weight=3, minsize=380)

        ttk.Label(p, text="Parameters", style="Header.TLabel").grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 6))
        r = 1
        r = self._add_row(
            p, r, "Parameters", "start_time", "Start Time Index", "int",
            "0-based NetCDF time index",
            extra_btn=("Calculate...", lambda: self._open_time_index_calculator("start_time", "Start Time Index")),
        )
        r = self._add_row(
            p, r, "Parameters", "stop_time", "Stop Time Index", "int",
            "End NetCDF time index",
            extra_btn=("Calculate...", lambda: self._open_time_index_calculator("stop_time", "Stop Time Index")),
        )
        r = self._add_row(p, r, "Parameters", "time_step", "Time Step", "int", "Sub-step / stride (e.g., 1)")

        ttk.Separator(p, orient=tk.HORIZONTAL).grid(row=r, column=0, columnspan=4, sticky=tk.EW, pady=12)
        r += 1
        ttk.Label(p, text="Random Term Coefficients", style="Header.TLabel").grid(row=r, column=0, columnspan=3, sticky=tk.W, pady=(0, 6))
        r += 1
        r = self._add_row(p, r, "Coefficients", "C1", "Coefficient C1 (Amplitude)", "number", "Model-specific coefficient")
        r = self._add_row(p, r, "Coefficients", "C2", "Coefficient C2 (Period or Lambda de Poisson)", "number", "Model-specific coefficient")

    def _build_outputs_analysis_tab(self):
        sf = ScrollableFrame(self.notebook)
        self.notebook.add(sf, text="Outputs & Analysis")
        p = sf.inner
        p.columnconfigure(1, weight=3, minsize=380)

        ttk.Label(p, text="Outputs", style="Header.TLabel").grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 6))
        r = 1
        r = self._add_row(p, r, "Outputs", "output_directory", "Output Directory", "str", "Must end with '/'", browse="dir")
        r = self._add_row(p, r, "Outputs", "track_file", "Track NetCDF File", "str", "Output trajectory filename (.nc)", browse="save")
        r = self._add_row(p, r, "Outputs", "report_file", "Report Info File", "str", "Summary metadata file (.info)", browse="save")
        r = self._add_row(p, r, "Outputs", "activate_multilayer_shapefile", "Multilayer Shapefile", "bool_int", "1 = export ESRI Shapefile")
        r = self._add_row(p, r, "Outputs", "particle_map_file", "Particle Map Image", "str", "Output figure (.png, .jpeg, .pdf, .tiff)", browse="save")

        ttk.Separator(p, orient=tk.HORIZONTAL).grid(row=r, column=0, columnspan=4, sticky=tk.EW, pady=12)
        r += 1
        ttk.Label(p, text="Analysis", style="Header.TLabel").grid(row=r, column=0, columnspan=3, sticky=tk.W, pady=(0, 6))
        r += 1
        r = self._add_row(p, r, "Analysis", "time_interval_filter", "Time Interval Filter", "bool_int", "1 = slice trajectories by time_range")
        r = self._add_row(p, r, "Analysis", "time_range", "Time Range [2]", "int_list", "Comma-separated: start_idx, end_idx")

    def _build_plots_tab(self):
        sf = ScrollableFrame(self.notebook)
        self.notebook.add(sf, text="Plots")
        p = sf.inner
        p.columnconfigure(1, weight=3, minsize=380)

        ttk.Label(p, text="Map & Trajectory Styling", style="Header.TLabel").grid(row=0, column=0, columnspan=5, sticky=tk.W, pady=(0, 6))
        r = 1
        r = self._add_row(
            p, r, "Plots", "study_region", "Study Region [4]", "num_list",
            "lon_min, lon_max, lat_min, lat_max",
            extra_btn=("Select on Map...", self._open_region_map_selector)
        )
        r = self._add_row(p, r, "Plots", "dpi", "Figure DPI", "int", "e.g., 300 or 500")
        r = self._add_row(p, r, "Plots", "particles_to_show", "Particles to Show", "str", "'all' or comma-separated indices")
        r = self._add_row(p, r, "Plots", "plot_objects", "Plot Objects (.obj)", "bool_int", "1 = draw objects_files overlay")
        r = self._add_row(p, r, "Plots", "track_lines", "Draw Track Lines", "bool_int", "1 = lines, 0 = points only")
        r = self._add_row(p, r, "Plots", "show_particle_label", "Show Particle Labels", "bool_int", "1 = display particle IDs")
        r = self._add_row(p, r, "Plots", "label_color", "Label Color", "str", "Matplotlib color name or hex")
        r = self._add_row(p, r, "Plots", "label_fontsize", "Label Font Size", "int", "Points (e.g., 8)")
        r = self._add_row(p, r, "Plots", "tack_linewidth", "Track Line Width", "float", "Points (e.g., 1.2)")
        r = self._add_row(p, r, "Plots", "track_linestyle", "Track Line Style", "combo", "Matplotlib linestyle", values=LINESTYLES)
        r = self._add_row(p, r, "Plots", "track_colortable", "Track Colortable (.tab)", "combo", "RGB palette file", values=self.tab_names)
        r = self._add_row(p, r, "Plots", "triangle_size", "Triangle Marker Size", "float", "Release (^) and arrival (v) size")
        r = self._add_row(p, r, "Plots", "legend_position", "Legend Position", "combo", "Inside or outside plot legend loc", values=LEGEND_POSITIONS)
        r = self._add_row(p, r, "Plots", "legend_fontsize", "Legend Font Size", "int", "Points (e.g., 9)")
        r = self._add_row(p, r, "Plots", "legend_numcol", "Legend Columns", "int", "Number of columns (e.g., 2)")
        r = self._add_row(p, r, "Plots", "hidden_legend", "Hide Legend", "bool_int", "1 = hide legend, 0 = show")

    def _build_json_tab(self):
        frame = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(frame, text="JSON Preview")
        self.json_text = tk.Text(frame, wrap=tk.NONE, font=("TkFixedFont", 12), state=tk.DISABLED)
        ybar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.json_text.yview)
        xbar = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.json_text.xview)
        self.json_text.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.json_text.grid(row=0, column=0, sticky=tk.NSEW)
        ybar.grid(row=0, column=1, sticky=tk.NS)
        xbar.grid(row=1, column=0, sticky=tk.EW)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

    def _on_tab_changed(self, _event=None):
        if self.notebook.tab(self.notebook.select(), "text") == "JSON Preview":
            try:
                data = self.collect_data()
                txt = json.dumps(data, indent=4, ensure_ascii=False)
            except ValueError as exc:
                txt = f"Validation error:\n{exc}"
            self.json_text.configure(state=tk.NORMAL)
            self.json_text.delete("1.0", tk.END)
            self.json_text.insert("1.0", txt)
            self.json_text.configure(state=tk.DISABLED)

    def _load_samples_list(self):
        samples_dir = os.path.join(PROJECT_ROOT, "samples")
        confs = sorted(glob.glob(os.path.join(samples_dir, "*.conf"))) if os.path.isdir(samples_dir) else []
        self.sample_map = {os.path.basename(p): p for p in confs}
        self.sample_combo["values"] = list(self.sample_map.keys())

    def _on_sample_selected(self, _event=None):
        name = self.sample_var.get()
        if name in self.sample_map:
            self.load_file(self.sample_map[name])

    def _populate_fields(self, data):
        for (sec, key), (var, kind) in self.field_specs.items():
            val = data.get(sec, {}).get(key, DEFAULT_CONFIG.get(sec, {}).get(key, ""))
            if kind == "bool_int":
                var.set(1 if int(val) else 0)
            elif kind in ("str_list", "num_list", "int_list"):
                if isinstance(val, list):
                    var.set(", ".join(str(x) for x in val))
                else:
                    var.set(str(val))
            else:
                var.set(str(val))

    def collect_data(self):
        out = json.loads(json.dumps(self.raw_data))
        for (sec, key), (var, kind) in self.field_specs.items():
            out.setdefault(sec, {})
            raw = var.get()
            try:
                if kind == "bool_int":
                    out[sec][key] = int(raw)
                elif kind == "int":
                    out[sec][key] = int(float(str(raw).strip()))
                elif kind == "float":
                    out[sec][key] = float(str(raw).strip())
                elif kind == "number":
                    s = str(raw).strip()
                    f = float(s)
                    out[sec][key] = int(f) if (f.is_integer() and "." not in s) else f
                elif kind == "str_list":
                    out[sec][key] = [x.strip() for x in str(raw).split(",") if x.strip()]
                elif kind == "int_list":
                    out[sec][key] = [int(float(x.strip())) for x in str(raw).split(",") if x.strip()]
                elif kind == "num_list":
                    vals = []
                    for x in str(raw).split(","):
                        xs = x.strip()
                        if not xs:
                            continue
                        f = float(xs)
                        vals.append(int(f) if (f.is_integer() and "." not in xs) else f)
                    out[sec][key] = vals
                elif kind == "combo" and key == "verbose":
                    out[sec][key] = int(raw)
                else:
                    out[sec][key] = str(raw)
            except ValueError as exc:
                raise ValueError(f"Invalid value in [{sec} -> {key}]: {raw!r} ({exc})") from exc

        if len(out["Plots"]["study_region"]) != 4:
            raise ValueError("[Plots -> study_region] must contain 4 numbers: lon_min, lon_max, lat_min, lat_max.")
        if len(out["Analysis"]["time_range"]) != 2:
            raise ValueError("[Analysis -> time_range] must contain 2 integers: start_idx, end_idx.")
        return out

    def new_config(self):
        self.current_path = None
        self.raw_data = json.loads(json.dumps(DEFAULT_CONFIG))
        self._populate_fields(self.raw_data)
        self.path_var.set("Unsaved configuration")
        self.status_var.set("New default configuration created.")

    def open_dialog(self):
        path = filedialog.askopenfilename(
            title="Open SPartA Configuration (.conf)",
            initialdir=os.path.join(PROJECT_ROOT, "samples"),
            filetypes=[("SPartA Config", "*.conf"), ("JSON", "*.json"), ("All Files", "*.*")],
        )
        if path:
            self.load_file(path)

    def load_file(self, path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            messagebox.showerror("Error loading .conf", f"Could not read {path}:\n{exc}")
            return
        self.current_path = path
        self.raw_data = data
        self._populate_fields(data)
        self.path_var.set(path)
        self.status_var.set(f"Loaded: {os.path.basename(path)}")
        self._on_tab_changed()

    def validate_only(self):
        try:
            self.collect_data()
            self.status_var.set("Validation passed: all parameters are valid.")
            messagebox.showinfo("Validation", "All configuration parameters are valid.")
        except ValueError as exc:
            messagebox.showerror("Validation Error", str(exc))

    def save_file(self, target_path=None):
        path = target_path or self.current_path
        if not path:
            return self.save_as_dialog()
        try:
            data = self.collect_data()
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=4, ensure_ascii=False)
                fh.write("\n")
            self.current_path = path
            self.raw_data = data
            self.path_var.set(path)
            self.status_var.set(f"Saved: {os.path.basename(path)}")
            if int(data.get("Physics", {}).get("invert_vector_fields", 0)) == 1:
                self._show_inverted_fields_warning()
            return True
        except Exception as exc:
            messagebox.showerror("Error saving .conf", str(exc))
            return False

    def _show_inverted_fields_warning(self):
        dlg = tk.Toplevel(self)
        dlg.title("Inverted Vector Fields")
        dlg.resizable(False, False)
        dlg.transient(self)

        frame = ttk.Frame(dlg, padding=18)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame,
            text="⚠ WARNING: INVERTED VECTOR FIELDS ENABLED",
            font=("TkDefaultFont", 15, "bold"),
            fg="#DC2626",
            justify=tk.CENTER,
        ).pack(pady=(0, 10))

        tk.Label(
            frame,
            text=(
                "'Invert Vector Fields' is set to 1 (backtracking).\n"
                "Velocity fields will be inverted for backward-in-time tracking."
            ),
            font=("TkDefaultFont", 13, "bold"),
            fg="#DC2626",
            justify=tk.CENTER,
            wraplength=460,
        ).pack(pady=(0, 14))

        btn = ttk.Button(frame, text="OK", width=12, command=dlg.destroy)
        btn.pack()
        btn.focus_set()

        dlg.bind("<Return>", lambda _e: dlg.destroy())
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - dlg.winfo_width()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - dlg.winfo_height()) // 2)
        dlg.geometry(f"+{x}+{y}")
        dlg.grab_set()
        self.wait_window(dlg)

    def save_as_dialog(self):
        path = filedialog.asksaveasfilename(
            title="Save SPartA Configuration As (.conf)",
            initialdir=os.path.join(PROJECT_ROOT, "samples"),
            defaultextension=".conf",
            filetypes=[("SPartA Config", "*.conf"), ("JSON", "*.json")],
        )
        if path:
            return self.save_file(target_path=path)
        return False

def main():
    app = SPartAConfigApp()
    app.mainloop()

if __name__ == "__main__":
    main()
