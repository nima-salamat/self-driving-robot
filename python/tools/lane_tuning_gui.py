#!/usr/bin/env python3
"""Interactive PNG browser and Hough lane-detection tuner for SelfDrivingRobot."""

from __future__ import annotations

import base64
import importlib
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

import base_config
from utils import json_config
from visualization.lane_debug_overlay import render_lane_debug_overlay

BG = "#0b1220"
PANEL = "#111c2d"
ALT = "#172438"
BORDER = "#26364c"
TEXT = "#edf3fb"
MUTED = "#96a8bf"
ACCENT = "#60a5fa"


class LaneTuningApp:
    def __init__(self, root: tk.Tk, mode: str = "race", directory: str | None = None):
        self.root = root
        self.root.title("SelfDrivingRobot | Lane Vision Lab")
        self.root.geometry("1480x880")
        self.root.minsize(1080, 680)
        self.root.configure(bg=BG)

        self.mode = mode
        self.config = None
        self.processor = None
        self.paths: list[Path] = []
        self.selected_path: Path | None = None
        self.original = None
        self.detect_frame = None
        self.result = None
        self.views: dict[str, np.ndarray] = {}
        self.thumb_refs = []
        self.gallery_items = []
        self.preview_ref = None
        self.loading_vars = False

        self.folder_var = tk.StringVar()
        self.mode_var = tk.StringVar(value=mode)
        self.view_var = tk.StringVar(value="Original")
        self.resize_var = tk.BooleanVar(value=True)
        self.bev_var = tk.BooleanVar(value=False)
        self.morph_var = tk.BooleanVar(value=True)
        self.method_var = tk.StringVar(value="Sobel gradient (current)")
        self.roi_mode_var = tk.StringVar(value="rectangle")
        self.status_var = tk.StringVar(value="Choose a directory containing PNG images.")
        self.image_info_var = tk.StringVar(value="No image selected")
        self.result_info_var = tk.StringVar(value="Run detection to see the lane result.")
        self.params: dict[str, tk.IntVar] = {}

        self._style()
        self._build_ui()
        self._load_mode(mode)
        self._copy_config_to_controls()
        if directory:
            self.load_directory(directory)

    def _style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Alt.TFrame", background=ALT)
        style.configure("TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Heading.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 19))
        style.configure("Subtitle.TLabel", background=BG, foreground=MUTED)
        style.configure("PanelHeading.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI Semibold", 11))
        style.configure("TButton", padding=(9, 7), background=ALT, foreground=TEXT)
        style.map("TButton", background=[("active", "#263b55")])
        style.configure("Accent.TButton", padding=(10, 9), background="#2563eb", foreground="#ffffff", font=("Segoe UI Semibold", 10))
        style.map("Accent.TButton", background=[("active", "#3b82f6")])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        style.map("TCheckbutton", background=[("active", PANEL)])
        style.configure("TCombobox", fieldbackground=ALT, background=ALT, foreground=TEXT, arrowcolor=TEXT)
        style.map("TCombobox", fieldbackground=[("readonly", ALT)], foreground=[("readonly", TEXT)])

    def _build_ui(self):
        header = ttk.Frame(self.root, padding=(16, 13))
        header.pack(fill="x")
        title = ttk.Frame(header)
        title.pack(side="left", fill="x", expand=True)
        ttk.Label(title, text="Lane Vision Lab", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(title, text="Browse frames · Tune Hough · Compare real Race and City detector output", style="Subtitle.TLabel").pack(anchor="w", pady=(3, 0))
        ttk.Label(header, text="MODE", style="Subtitle.TLabel").pack(side="left", padx=(8, 6))
        mode = ttk.Combobox(header, textvariable=self.mode_var, values=("race", "city"), state="readonly", width=8)
        mode.pack(side="left")
        mode.bind("<<ComboboxSelected>>", self._mode_changed)

        toolbar = ttk.Frame(self.root, padding=(16, 0, 16, 12))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Open PNG folder", command=self.choose_folder).pack(side="left")
        ttk.Label(toolbar, textvariable=self.folder_var, style="Subtitle.TLabel").pack(side="left", padx=10, fill="x", expand=True)
        ttk.Checkbutton(toolbar, text="Resize to runtime dimensions", variable=self.resize_var, command=self._mark_dirty).pack(side="left", padx=(8, 14))
        ttk.Button(toolbar, text="← Previous", command=lambda: self.move_image(-1)).pack(side="left", padx=(0, 5))
        ttk.Button(toolbar, text="Next →", command=lambda: self.move_image(1)).pack(side="left")

        main = ttk.Frame(self.root, padding=(12, 0, 12, 10))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=0, minsize=228)
        main.columnconfigure(1, weight=1)
        main.columnconfigure(2, weight=0, minsize=300)
        main.rowconfigure(0, weight=1)

        left = ttk.Frame(main, style="Panel.TFrame", padding=9)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        ttk.Label(left, text="IMAGE LIBRARY", style="PanelHeading.TLabel").pack(anchor="w")
        self.gallery_count = ttk.Label(left, text="0 PNG files", style="Muted.TLabel")
        self.gallery_count.pack(anchor="w", pady=(3, 7))
        gallery_box = ttk.Frame(left, style="Panel.TFrame")
        gallery_box.pack(fill="both", expand=True)
        self.gallery_canvas = tk.Canvas(gallery_box, bg=PANEL, highlightthickness=0, bd=0)
        gallery_scroll = ttk.Scrollbar(gallery_box, orient="vertical", command=self.gallery_canvas.yview)
        self.gallery_inner = ttk.Frame(self.gallery_canvas, style="Panel.TFrame")
        self.gallery_window = self.gallery_canvas.create_window((0, 0), window=self.gallery_inner, anchor="nw")
        self.gallery_inner.bind("<Configure>", lambda _e: self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox("all")))
        self.gallery_canvas.bind("<Configure>", lambda e: self.gallery_canvas.itemconfigure(self.gallery_window, width=e.width))
        self.gallery_canvas.configure(yscrollcommand=gallery_scroll.set)
        self.gallery_canvas.pack(side="left", fill="both", expand=True)
        gallery_scroll.pack(side="right", fill="y")
        self.gallery_canvas.bind_all("<MouseWheel>", self._mousewheel)

        center = ttk.Frame(main, style="Panel.TFrame", padding=10)
        center.grid(row=0, column=1, sticky="nsew", padx=(0, 9))
        center.columnconfigure(0, weight=1)
        center.rowconfigure(1, weight=1)
        preview_bar = ttk.Frame(center, style="Panel.TFrame")
        preview_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        preview_bar.columnconfigure(0, weight=1)
        ttk.Label(preview_bar, textvariable=self.image_info_var, style="PanelHeading.TLabel").grid(row=0, column=0, sticky="w")
        view = ttk.Combobox(
            preview_bar, textvariable=self.view_var, state="readonly", width=21,
            values=("Original", "All Hough candidates", "Selected lane lines", "Right ROI edges", "Left ROI edges"),
        )
        view.grid(row=0, column=1, sticky="e")
        view.bind("<<ComboboxSelected>>", lambda _e: self._render())
        image_box = ttk.Frame(center, style="Alt.TFrame", padding=7)
        image_box.grid(row=1, column=0, sticky="nsew")
        image_box.rowconfigure(0, weight=1)
        image_box.columnconfigure(0, weight=1)
        self.preview = tk.Canvas(image_box, bg="#060a12", highlightthickness=0, bd=0)
        self.preview.grid(row=0, column=0, sticky="nsew")
        self.preview.bind("<Configure>", lambda _e: self._render())
        ttk.Label(center, textvariable=self.result_info_var, style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 2))
        ttk.Label(center, text="Green = all candidates · Blue = selected left · Amber = selected right", style="Muted.TLabel").grid(row=3, column=0, sticky="w")

        right = ttk.Frame(main, style="Panel.TFrame", padding=10)
        right.grid(row=0, column=2, sticky="nsew")
        ttk.Label(right, text="DETECTION PARAMETERS", style="PanelHeading.TLabel").pack(anchor="w")
        ttk.Label(right, text="Changes are temporary until you save the mode preset.", style="Muted.TLabel", wraplength=270).pack(anchor="w", pady=(4, 7))

        scroll_box = ttk.Frame(right, style="Panel.TFrame")
        scroll_box.pack(fill="both", expand=True)
        self.control_canvas = tk.Canvas(scroll_box, bg=PANEL, highlightthickness=0, bd=0)
        control_scroll = ttk.Scrollbar(scroll_box, orient="vertical", command=self.control_canvas.yview)
        self.control_inner = ttk.Frame(self.control_canvas, style="Panel.TFrame")
        self.control_window = self.control_canvas.create_window((0, 0), window=self.control_inner, anchor="nw")
        self.control_inner.bind("<Configure>", lambda _e: self.control_canvas.configure(scrollregion=self.control_canvas.bbox("all")))
        self.control_canvas.bind("<Configure>", lambda e: self.control_canvas.itemconfigure(self.control_window, width=e.width))
        self.control_canvas.configure(yscrollcommand=control_scroll.set)
        self.control_canvas.pack(side="left", fill="both", expand=True)
        control_scroll.pack(side="right", fill="y")

        ttk.Label(self.control_inner, text="Preprocessing", style="PanelHeading.TLabel").pack(anchor="w", pady=(3, 4))
        method = ttk.Combobox(
            self.control_inner, textvariable=self.method_var, state="readonly",
            values=("Sobel gradient (current)", "Legacy threshold + Canny"),
        )
        method.pack(fill="x", pady=(0, 5))
        method.bind("<<ComboboxSelected>>", lambda _e: self._mark_dirty())
        ttk.Checkbutton(self.control_inner, text="Apply BEV perspective transform", variable=self.bev_var, command=self._mark_dirty).pack(anchor="w", pady=3)
        ttk.Checkbutton(self.control_inner, text="Morphological close", variable=self.morph_var, command=self._mark_dirty).pack(anchor="w", pady=3)
        ttk.Separator(self.control_inner).pack(fill="x", pady=8)
        self._slider("Lane threshold", "lane", 0, 255, 1)
        self._slider("Hough vote threshold", "hough", 1, 100, 1)
        self._slider("Minimum line length (px)", "length", 1, 100, 1)
        self._slider("Maximum line gap (px)", "gap", 0, 40, 1)
        self._slider("Gaussian blur kernel (odd)", "blur", 1, 7, 2)
        ttk.Separator(self.control_inner).pack(fill="x", pady=9)
        ttk.Label(self.control_inner, text="Lane ROI geometry", style="PanelHeading.TLabel").pack(anchor="w", pady=(2, 4))
        roi_shape = ttk.Combobox(
            self.control_inner, textvariable=self.roi_mode_var, state="readonly",
            values=("rectangle", "trapezoid"),
        )
        roi_shape.pack(fill="x", pady=(0, 5))
        roi_shape.bind("<<ComboboxSelected>>", lambda _e: self._mark_dirty())
        self._slider("Right ROI top (%)", "rl_top", 0, 100, 1)
        self._slider("Right ROI bottom (%)", "rl_bottom", 0, 100, 1)
        self._slider("Right ROI left (%)", "rl_left", 0, 100, 1)
        self._slider("Right ROI right (%)", "rl_right", 0, 100, 1)
        self._slider("Left ROI top (%)", "ll_top", 0, 100, 1)
        self._slider("Left ROI bottom (%)", "ll_bottom", 0, 100, 1)
        self._slider("Left ROI left (%)", "ll_left", 0, 100, 1)
        self._slider("Left ROI right (%)", "ll_right", 0, 100, 1)
        self._slider("Right trapezoid top width (%)", "rl_factor", 0, 100, 1)
        self._slider("Left trapezoid top width (%)", "ll_factor", 0, 100, 1)
        ttk.Label(
            self.control_inner,
            text="Compare edge maps as well as the overlay. More strict settings can also remove faint real lane markings.",
            style="Muted.TLabel", wraplength=265,
        ).pack(anchor="w", pady=(8, 10))

        actions = ttk.Frame(right, style="Panel.TFrame")
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="Apply detection", style="Accent.TButton", command=self.apply_detection).pack(fill="x", pady=(0, 5))
        ttk.Button(actions, text="Save displayed PNG", command=self.save_result).pack(fill="x", pady=(0, 5))
        ttk.Button(actions, text="Save preset to mode JSON", command=self.save_preset).pack(fill="x")
        ttk.Label(right, textvariable=self.status_var, style="Muted.TLabel", wraplength=270).pack(anchor="w", pady=(8, 0))

        ttk.Label(
            self.root,
            text="Offline image analysis only: opens no camera, serial port, or Arduino connection.",
            style="Subtitle.TLabel", padding=(15, 0, 15, 9),
        ).pack(fill="x")

    def _slider(self, label: str, key: str, low: int, high: int, step: int):
        row = ttk.Frame(self.control_inner, style="Panel.TFrame")
        row.pack(fill="x", pady=(4, 1))
        row.columnconfigure(0, weight=1)
        ttk.Label(row, text=label).grid(row=0, column=0, sticky="w")
        value_label = ttk.Label(row, text=str(low), style="Muted.TLabel")
        value_label.grid(row=0, column=1, sticky="e")
        variable = tk.IntVar(value=low)
        tk.Scale(
            row, from_=low, to=high, resolution=step, orient="horizontal",
            variable=variable, showvalue=False, bg=PANEL, fg=TEXT,
            activebackground=ACCENT, troughcolor=ALT, highlightthickness=0, bd=0,
            command=lambda value, lbl=value_label: lbl.configure(text=str(int(round(float(value))))),
        ).grid(row=1, column=0, columnspan=2, sticky="ew")
        variable.trace_add("write", lambda *_a: self._mark_dirty())
        self.params[key] = variable

    def _load_mode(self, mode: str):
        self.mode = mode
        base_config.MODE = mode
        json_config.load()
        if mode == "race":
            self.config = importlib.import_module("modes.race.config_race")
            module = "vision.race_vision_processing"
        else:
            self.config = importlib.import_module("modes.city.config_city")
            module = "vision.city_vision_processing"
        self.config.DEBUG = True
        self.config.STREAM = False
        if hasattr(self.config, "USE_ML_LANE_DETECTOR"):
            self.config.USE_ML_LANE_DETECTOR = False
        processor_module = importlib.reload(importlib.import_module(module))
        self.processor = processor_module.VisionProcessor()
        self.config.HOUGH_THRESHOLD = int(getattr(self.config, "HOUGH_THRESHOLD", 20 if getattr(self.config, "OLD_METHOD", False) else 15))
        self.config.HOUGH_MIN_LINE_LENGTH = int(getattr(self.config, "HOUGH_MIN_LINE_LENGTH", 5))
        self.config.HOUGH_MAX_LINE_GAP = int(getattr(self.config, "HOUGH_MAX_LINE_GAP", 5 if getattr(self.config, "OLD_METHOD", False) else 20))
        self.config.HOUGH_BLUR_KERNEL = int(getattr(self.config, "HOUGH_BLUR_KERNEL", 3))
        self.config.HOUGH_MORPH_CLOSE = bool(getattr(self.config, "HOUGH_MORPH_CLOSE", True))

    def _copy_config_to_controls(self):
        self.loading_vars = True
        try:
            values = {
                "lane": int(getattr(self.config, "LANE_THRESHOLD", 180)),
                "hough": int(getattr(self.config, "HOUGH_THRESHOLD", 15)),
                "length": int(getattr(self.config, "HOUGH_MIN_LINE_LENGTH", 5)),
                "gap": int(getattr(self.config, "HOUGH_MAX_LINE_GAP", 20)),
                "blur": int(getattr(self.config, "HOUGH_BLUR_KERNEL", 3)),
                "rl_top": round(float(getattr(self.config, "RL_TOP_ROI", 0.8)) * 100),
                "rl_bottom": round(float(getattr(self.config, "RL_BOTTOM_ROI", 1.0)) * 100),
                "rl_left": round(float(getattr(self.config, "RL_LEFT_ROI", 0.6)) * 100),
                "rl_right": round(float(getattr(self.config, "RL_RIGHT_ROI", 0.9)) * 100),
                "ll_top": round(float(getattr(self.config, "LL_TOP_ROI", 0.8)) * 100),
                "ll_bottom": round(float(getattr(self.config, "LL_BOTTOM_ROI", 1.0)) * 100),
                "ll_left": round(float(getattr(self.config, "LL_LEFT_ROI", 0.2)) * 100),
                "ll_right": round(float(getattr(self.config, "LL_RIGHT_ROI", 0.5)) * 100),
                "rl_factor": round(float(getattr(self.config, "RL_TOP_WIDTH_FACTOR", 0.85)) * 100),
                "ll_factor": round(float(getattr(self.config, "LL_TOP_WIDTH_FACTOR", 0.85)) * 100),
            }
            for key, value in values.items():
                self.params[key].set(value)
            self.bev_var.set(bool(getattr(self.config, "USE_BEV", False)))
            self.morph_var.set(bool(getattr(self.config, "HOUGH_MORPH_CLOSE", True)))
            self.method_var.set("Legacy threshold + Canny" if bool(getattr(self.config, "OLD_METHOD", False)) else "Sobel gradient (current)")
            self.roi_mode_var.set(str(getattr(self.config, "LANE_ROI_MODE", "rectangle")))
        finally:
            self.loading_vars = False

    def _mode_changed(self, _event=None):
        selected = self.mode_var.get()
        if selected == self.mode:
            return
        try:
            self._load_mode(selected)
            self._copy_config_to_controls()
            self.result = None
            self.views = {"Original": self.original} if self.original is not None else {}
            self._render()
            self.status_var.set(f"Loaded {selected} configuration.")
        except Exception as exc:
            messagebox.showerror("Could not load mode", f"{type(exc).__name__}: {exc}")
            self.mode_var.set(self.mode)

    def _mark_dirty(self, *_args):
        if getattr(self, "loading_vars", False):
            return
        if self.selected_path is not None:
            self.status_var.set("Settings changed — click Apply detection.")

    def choose_folder(self):
        directory = filedialog.askdirectory(title="Choose folder containing PNG images")
        if directory:
            self.load_directory(directory)

    def load_directory(self, directory: str):
        folder = Path(directory).expanduser()
        if not folder.is_dir():
            messagebox.showerror("Invalid folder", str(folder))
            return
        paths = sorted(
            (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".png"),
            key=lambda p: p.name.lower(),
        )
        if not paths:
            messagebox.showinfo("No PNG files", f"No PNG files found in:\n{folder}")
            return
        self.paths = paths
        self.folder_var.set(str(folder))
        self.gallery_count.configure(text=f"{len(paths)} PNG files")
        self._build_gallery()
        self.select_image(paths[0])
        self.status_var.set(f"Loaded {len(paths)} PNG images.")

    def _build_gallery(self):
        for child in self.gallery_inner.winfo_children():
            child.destroy()
        self.thumb_refs.clear()
        self.gallery_items.clear()
        for path in self.paths:
            card = ttk.Frame(self.gallery_inner, style="Alt.TFrame", padding=4)
            card.pack(fill="x", pady=3)
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is not None:
                thumb = self._fit(image, 180, 88, upscale=False)
                photo = self._photo(thumb)
                self.thumb_refs.append(photo)
                button = tk.Button(
                    card, image=photo, command=lambda p=path: self.select_image(p),
                    bg=ALT, activebackground="#263b55", relief="flat", bd=0,
                    highlightthickness=1, highlightbackground=BORDER, cursor="hand2",
                )
            else:
                button = tk.Button(card, text="Could not preview", command=lambda p=path: self.select_image(p))
            button.pack(fill="x")
            label = tk.Label(card, text=path.name, anchor="w", bg=ALT, fg=TEXT, font=("Segoe UI", 9), wraplength=190)
            label.pack(fill="x", pady=(4, 0))
            label.bind("<Button-1>", lambda _e, p=path: self.select_image(p))
            self.gallery_items.append((path, button))

    def _highlight_gallery(self):
        for path, button in self.gallery_items:
            button.configure(
                highlightbackground=ACCENT if path == self.selected_path else BORDER,
                highlightthickness=2 if path == self.selected_path else 1,
            )

    def select_image(self, path: Path):
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            messagebox.showerror("Image read failed", str(path))
            return
        self.selected_path = path
        self.original = image
        self.detect_frame = None
        self.result = None
        self.views = {"Original": image}
        self.view_var.set("Original")
        height, width = image.shape[:2]
        self.image_info_var.set(f"{path.name}  ·  {width} × {height}")
        self.result_info_var.set("No detection result yet")
        self._highlight_gallery()
        self._render()

    def move_image(self, step: int):
        if not self.paths or self.selected_path is None:
            return
        index = self.paths.index(self.selected_path) if self.selected_path in self.paths else 0
        self.select_image(self.paths[(index + step) % len(self.paths)])

    def _mark_settings(self):
        self.config.LANE_THRESHOLD = int(self.params["lane"].get())
        self.config.HOUGH_THRESHOLD = int(self.params["hough"].get())
        self.config.HOUGH_MIN_LINE_LENGTH = int(self.params["length"].get())
        self.config.HOUGH_MAX_LINE_GAP = int(self.params["gap"].get())
        blur = int(self.params["blur"].get())
        self.config.HOUGH_BLUR_KERNEL = blur if blur % 2 else max(1, blur - 1)
        self.config.HOUGH_MORPH_CLOSE = bool(self.morph_var.get())
        self.config.USE_BEV = bool(self.bev_var.get())
        self.config.OLD_METHOD = self.method_var.get().startswith("Legacy")
        self.config.LANE_ROI_MODE = self.roi_mode_var.get()
        roi_map = {
            "RL_TOP_ROI": "rl_top", "RL_BOTTOM_ROI": "rl_bottom",
            "RL_LEFT_ROI": "rl_left", "RL_RIGHT_ROI": "rl_right",
            "LL_TOP_ROI": "ll_top", "LL_BOTTOM_ROI": "ll_bottom",
            "LL_LEFT_ROI": "ll_left", "LL_RIGHT_ROI": "ll_right",
        }
        for config_key, control_key in roi_map.items():
            setattr(self.config, config_key, int(self.params[control_key].get()) / 100.0)
        self.config.RL_TOP_WIDTH_FACTOR = int(self.params["rl_factor"].get()) / 100.0
        self.config.LL_TOP_WIDTH_FACTOR = int(self.params["ll_factor"].get()) / 100.0
        for side in ("RL", "LL"):
            top = float(getattr(self.config, f"{side}_TOP_ROI"))
            bottom = float(getattr(self.config, f"{side}_BOTTOM_ROI"))
            left = float(getattr(self.config, f"{side}_LEFT_ROI"))
            right = float(getattr(self.config, f"{side}_RIGHT_ROI"))
            if not (0.0 <= top < bottom <= 1.0 and 0.0 <= left < right <= 1.0):
                raise ValueError(f"{side} ROI is invalid: top must be above bottom and left must be left of right.")
        self.config.DEBUG = True
        self.config.STREAM = False

    def _runtime_image(self, image: np.ndarray):
        if not self.resize_var.get():
            return image.copy()
        width = int(getattr(self.config, "resize_width", 380))
        height = int(getattr(self.config, "resize_height", 230))
        if width <= 0 or height <= 0 or (image.shape[1] == width and image.shape[0] == height):
            return image.copy()
        return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)

    def apply_detection(self):
        if self.original is None:
            messagebox.showinfo("Select image", "Choose a PNG folder and select an image first.")
            return
        try:
            self._mark_settings()
            self.detect_frame = self._runtime_image(self.original)
            frame = self.detect_frame.copy()
            self.result = self.processor.detect(frame, frame.copy())
            debug = self.result.get("debug") or {}
            combined = debug.get("combined")
            if combined is not None:
                debug["combined"] = render_lane_debug_overlay(
                    combined,
                    debug.get("draw_data"),
                    self.config,
                    self.result.get("steering_angle"),
                )
            self.views = {"Original": self.original}
            if debug.get("combined") is not None:
                self.views["All Hough candidates"] = debug["combined"]
            selected = self._selected_lines_view(frame, debug)
            if selected is not None:
                self.views["Selected lane lines"] = selected
            if debug.get("rl_edges") is not None:
                self.views["Right ROI edges"] = debug["rl_edges"]
            if debug.get("ll_edges") is not None:
                self.views["Left ROI edges"] = debug["ll_edges"]
            if self.view_var.get() not in self.views:
                self.view_var.set("All Hough candidates" if "All Hough candidates" in self.views else "Original")

            right_count = len(debug["rl_lines"]) if debug.get("rl_lines") is not None else 0
            left_count = len(debug["ll_lines"]) if debug.get("ll_lines") is not None else 0
            self.result_info_var.set(
                f"Lane: {self.result.get('lane_type')}  ·  Valid: {self.result.get('perception_valid')}  ·  "
                f"Steering: {self.result.get('steering_angle')}  ·  Candidates: left {left_count} / right {right_count}"
            )
            self.status_var.set("Detection complete using the selected mode's VisionProcessor.")
            self._render()
        except Exception as exc:
            messagebox.showerror("Detection failed", f"{type(exc).__name__}: {exc}")
            self.status_var.set("Detection failed.")

    def _best_segment(self, lines, width: int, height: int, side: str):
        if lines is None or width <= 0 or height <= 0:
            return None
        best = None
        best_score = -1.0
        diagonal = float(np.hypot(width, height))
        for line in lines:
            coords = np.asarray(line).reshape(-1)
            if coords.size != 4:
                continue
            x1, y1, x2, y2 = map(float, coords)
            length = float(np.hypot(x2 - x1, y2 - y1))
            angle = abs(float(np.degrees(np.arctan((y2 - y1) / (x2 - x1 + 1e-9)))))
            x_mid, y_mid = (x1 + x2) / 2, (y1 + y2) / 2
            norm_length = min(length / max(diagonal, 1.0), 1.0)
            norm_y = min(y_mid / max(float(height), 1.0), 1.0)
            if side == "right":
                side_score = max(0.0, min(1.0, 1.0 - x_mid / width))
                target = self.processor._expected_lane_angle("right")
            else:
                side_score = max(0.0, min(1.0, x_mid / width))
                target = self.processor._expected_lane_angle("left")
            angle_score = float(np.exp(-((angle - target) ** 2) / (2.0 * 20.0 ** 2)))
            score = 0.25 * norm_length + 0.45 * side_score + 0.10 * norm_y + 0.20 * angle_score
            if score > best_score:
                best_score = score
                best = tuple(int(round(v)) for v in (x1, y1, x2, y2))
        return best

    def _bev(self, frame: np.ndarray):
        if not bool(getattr(self.config, "USE_BEV", False)):
            return frame.copy()
        height, width = frame.shape[:2]
        source = np.float32([
            [width * self.config.BEV_SRC_TL_X, height * self.config.BEV_SRC_TL_Y],
            [width * self.config.BEV_SRC_TR_X, height * self.config.BEV_SRC_TR_Y],
            [width * self.config.BEV_SRC_BR_X, height * self.config.BEV_SRC_BR_Y],
            [width * self.config.BEV_SRC_BL_X, height * self.config.BEV_SRC_BL_Y],
        ])
        destination = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
        matrix = cv2.getPerspectiveTransform(source, destination)
        return cv2.warpPerspective(frame, matrix, (width, height), flags=cv2.INTER_LINEAR)

    def _selected_lines_view(self, frame, debug):
        if self.result is None:
            return None
        if debug.get("rl_lines") is None and debug.get("ll_lines") is None:
            return None
        view = self._bev(frame)
        height, width = view.shape[:2]
        for side, line_key, edge_key, offset_key, color in (
            ("left", "ll_lines", "ll_edges", "ll_offset", (255, 155, 35)),
            ("right", "rl_lines", "rl_edges", "rl_offset", (0, 190, 255)),
        ):
            lines, edges, offset = debug.get(line_key), debug.get(edge_key), debug.get(offset_key)
            if lines is None or edges is None or offset is None:
                continue
            roi_height, roi_width = edges.shape[:2]
            chosen = self._best_segment(lines, roi_width, roi_height, side)
            if chosen is None:
                continue
            x0, y0 = int(offset[0]), int(offset[1])
            x1, y1, x2, y2 = chosen
            p1 = (max(0, min(width - 1, x0 + x1)), max(0, min(height - 1, y0 + y1)))
            p2 = (max(0, min(width - 1, x0 + x2)), max(0, min(height - 1, y0 + y2)))
            cv2.line(view, p1, p2, color, 3, cv2.LINE_AA)
            cv2.circle(view, p1, 4, color, -1, cv2.LINE_AA)
            cv2.circle(view, p2, 4, color, -1, cv2.LINE_AA)
        cv2.putText(view, "Best candidate per ROI; inspect before changing runtime settings", (7, max(18, height - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
        return view

    @staticmethod
    def _fit(image: np.ndarray, max_width: int, max_height: int, upscale: bool = True):
        height, width = image.shape[:2]
        if width <= 0 or height <= 0:
            return image
        factor = min(max_width / width, max_height / height)
        factor = min(factor, 2.0) if upscale else min(factor, 1.0)
        size = (max(1, int(width * factor)), max(1, int(height * factor)))
        if size == (width, height):
            return image
        return cv2.resize(image, size, interpolation=cv2.INTER_AREA if factor < 1 else cv2.INTER_LINEAR)

    @staticmethod
    def _photo(image: np.ndarray):
        ok, encoded = cv2.imencode(".png", image)
        if not ok:
            raise ValueError("Could not encode image preview.")
        return tk.PhotoImage(data=base64.b64encode(encoded.tobytes()).decode("ascii"))

    def _render(self):
        if not hasattr(self, "preview"):
            return
        image = self.views.get(self.view_var.get())
        if image is None:
            image = self.original
        if image is None:
            self.preview.delete("all")
            self.preview.create_text(
                max(1, self.preview.winfo_width() // 2),
                max(1, self.preview.winfo_height() // 2),
                text="Open a PNG folder to begin",
                fill=MUTED, font=("Segoe UI", 14),
            )
            return
        fitted = self._fit(image, max(100, self.preview.winfo_width() - 20), max(100, self.preview.winfo_height() - 20))
        try:
            photo = self._photo(fitted)
        except Exception as exc:
            self.status_var.set(f"Preview failed: {exc}")
            return
        self.preview_ref = photo
        self.preview.delete("all")
        self.preview.create_image(self.preview.winfo_width() // 2, self.preview.winfo_height() // 2, image=photo, anchor="center")

    def _mousewheel(self, event):
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget is self.gallery_canvas or widget is self.gallery_inner:
                self.gallery_canvas.yview_scroll(int(-event.delta / 120), "units")
                return
            if widget is self.control_canvas or widget is self.control_inner:
                self.control_canvas.yview_scroll(int(-event.delta / 120), "units")
                return
            widget = getattr(widget, "master", None)

    def save_result(self):
        image = self.views.get(self.view_var.get())
        if image is None:
            messagebox.showinfo("No result", "Apply detection first.")
            return
        stem = self.selected_path.stem if self.selected_path else "frame"
        name = f"{stem}_{self.mode}_{self.view_var.get().lower().replace(' ', '_')}.png"
        output = filedialog.asksaveasfilename(
            title="Save displayed image", defaultextension=".png", initialfile=name,
            filetypes=(("PNG image", "*.png"),),
        )
        if output:
            if cv2.imwrite(output, image):
                self.status_var.set(f"Saved {output}")
            else:
                messagebox.showerror("Save failed", output)

    def save_preset(self):
        try:
            self._mark_settings()
        except Exception as exc:
            messagebox.showerror("Invalid parameters", str(exc))
            return
        target = Path(base_config.BASE_DIR) / f"{self.mode}.json"
        values = {
            "LANE_THRESHOLD": int(self.config.LANE_THRESHOLD),
            "HOUGH_THRESHOLD": int(self.config.HOUGH_THRESHOLD),
            "HOUGH_MIN_LINE_LENGTH": int(self.config.HOUGH_MIN_LINE_LENGTH),
            "HOUGH_MAX_LINE_GAP": int(self.config.HOUGH_MAX_LINE_GAP),
            "HOUGH_BLUR_KERNEL": int(self.config.HOUGH_BLUR_KERNEL),
            "HOUGH_MORPH_CLOSE": bool(self.config.HOUGH_MORPH_CLOSE),
            "OLD_METHOD": bool(self.config.OLD_METHOD),
            "USE_BEV": bool(self.config.USE_BEV),
            "LANE_ROI_MODE": str(self.config.LANE_ROI_MODE),
            "RL_TOP_ROI": float(self.config.RL_TOP_ROI),
            "RL_BOTTOM_ROI": float(self.config.RL_BOTTOM_ROI),
            "RL_LEFT_ROI": float(self.config.RL_LEFT_ROI),
            "RL_RIGHT_ROI": float(self.config.RL_RIGHT_ROI),
            "LL_TOP_ROI": float(self.config.LL_TOP_ROI),
            "LL_BOTTOM_ROI": float(self.config.LL_BOTTOM_ROI),
            "LL_LEFT_ROI": float(self.config.LL_LEFT_ROI),
            "LL_RIGHT_ROI": float(self.config.LL_RIGHT_ROI),
            "RL_TOP_WIDTH_FACTOR": float(self.config.RL_TOP_WIDTH_FACTOR),
            "LL_TOP_WIDTH_FACTOR": float(self.config.LL_TOP_WIDTH_FACTOR),
        }
        if not messagebox.askyesno(
            "Save preset",
            f"Save detector settings to:\n{target}\n\n"
            "An adjacent .bak backup will be created. Future runs loading this JSON will use these values.",
        ):
            return
        try:
            existing = {}
            if target.exists():
                existing = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                raise ValueError("The mode JSON must contain an object.")
            if target.exists():
                target.with_suffix(target.suffix + ".bak").write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
            existing.update(values)
            target.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
            self.status_var.set(f"Saved preset to {target.name}.")
            messagebox.showinfo("Preset saved", f"Saved:\n{target}")
        except Exception as exc:
            messagebox.showerror("Could not save preset", f"{type(exc).__name__}: {exc}")



def main():
    import argparse
    parser = argparse.ArgumentParser(description="Interactive Hough tuning for PNG images.")
    parser.add_argument("--directory", default=None, help="Directory containing PNG images.")
    parser.add_argument("--mode", choices=("race", "city"), default="race")
    args = parser.parse_args()
    root = tk.Tk()
    LaneTuningApp(root, mode=args.mode, directory=args.directory)
    root.mainloop()


if __name__ == "__main__":
    main()
