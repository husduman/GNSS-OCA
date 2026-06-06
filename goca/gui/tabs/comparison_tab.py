import os
import re
import tkinter as tk
import numpy as np
from datetime import datetime
import multiprocessing as mp
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

# Local library imports
from goca.io.read_sp3 import read_sp3, read_sp3_headerline
from goca.io.read_clk import read_clk, read_clk_date
from goca.core.alignment import align_reference_target
from goca.core.predict_velocity import predict_velocity
from goca.core.rac import (
    compute_rac,
    write_rac_output,
    write_rac_output_overall,
    compute_overall_rac_stats
)
from goca.core.sun_shadow import SunEarthGeometry
from goca.core.clock_statistics import (
    compute_clock_stats,
    write_clock_output,
    write_clock_stats_overall
)
from goca.core.densify_sp3_epoch import densify_sp3_epoch
from goca.io.file_utils import build_output_filename

nanosec = 1e9
C = 299792458.0  # m/s

class ComparisonTab:
    """
    Orbit / Clock Comparison interface.
    Left panel:
    - Import Reference / Target files (SP3 or CLK depending on the mode)
    - Reference <-> Target swap
    - Clear File(s), Clear All
    - Satellite system selection
    - Radial corrected clock (RCC SP3 import within clock comparison)
    - Sampling strategy
    - Output options
    """
    def __init__(self, parent_frame, mode="orbit_compare"):
        self.mode = mode
        self.parent = parent_frame

        # Main comparison files (CLK or SP3 depending on mode)
        self.file_paths = {}   # tree item → {"ref": fullpath, "tgt": fullpath}

        # RCC (Radial Corrected Clock) SP3 files (only meaningful in clock_compare)
        self.rcc_sp3_paths = {}     # parent_item -> {"ref": sp3_path, "tgt": sp3_path}
        self.rcc_tree_items = {}    # parent_item -> child_item (RCC row)
        
        self._build_ui()

    # ------------------------------------------------------
    def _build_ui(self):
        frame = self.parent

        self.sat_system_prefix = {
            "GPS": "PG",
            "GLONASS": "PR",
            "Galileo": "PE",
            "BeiDou": "PC",
            "QZSS": "PJ",
            "IRNSS": "PI",
        }

        # ---------------------------------------------------
        # OPERATIONS
        # ---------------------------------------------------
        self.left_panel = ttk.LabelFrame(frame, text="Operations", padding=5)
        self.left_panel.configure(width=350)
        self.left_panel.pack(side="left", fill="y")
        self.left_panel.pack_propagate(False)

        btn_row = tk.Frame(self.left_panel)
        btn_row.pack(pady=3, padx=3, fill="x")

        # Determine labels by mode
        if self.mode == "orbit_compare":
            ref_label = "Import Reference SP3(s)"
            tgt_label = "Import Target SP3(s)"
        else:
            ref_label = "Import Reference CLK/SP3(s)"
            tgt_label = "Import Target CLK/SP3(s)"

        # IMPORT REFERENCE (full-width)
        ref_btn = ttk.Button(btn_row, text=ref_label, command=self.import_reference)
        ref_btn.pack(fill="x", pady=(0, 10))

        # IMPORT TARGET (full-width)
        tgt_btn = ttk.Button(btn_row, text=tgt_label, command=self.import_target)
        tgt_btn.pack(fill="x", pady=(0, 10))

        # REFERENCE <--> TARGET SWAP BUTTON
        swap_btn = ttk.Button(
            btn_row,
            text="Reference <--> Target",
            command=self.swap_reference_target
        )
        swap_btn.pack(fill="x", pady=(0, 10))

        # --- Clear buttons row (SIDE BY SIDE) ---
        clear_row = tk.Frame(btn_row)
        clear_row.pack(fill="x", pady=(0, 5))

        clear_btn = ttk.Button(clear_row, text="Clear File(s)", command=self.clear_files)
        clear_btn.pack(side="left", expand=True, fill="x", padx=(0, 3))

        clear_all_btn = ttk.Button(clear_row, text="Clear All", command=self.clear_all)
        clear_all_btn.pack(side="left", expand=True, fill="x", padx=(3, 0))

        # ---------------------------------------------------
        # SATELLITE SYSTEM CHECKBOXES
        # ---------------------------------------------------
        self.chk_vars = {}

        sat_frame = ttk.LabelFrame(self.left_panel, text="Satellite System", padding=5)
        sat_frame.pack(padx=5, pady=10, fill="x")

        col1 = tk.Frame(sat_frame)
        col1.pack(side="left", padx=10)
        col2 = tk.Frame(sat_frame)
        col2.pack(side="left", padx=10)

        # Column 1
        for name in ["GPS", "GLONASS", "Galileo"]:
            var = tk.IntVar(value=1)
            cb = tk.Checkbutton(col1, text=name, variable=var)
            cb.pack(anchor="w", pady=2)
            self.chk_vars[name] = var

        # Column 2
        for name in ["BeiDou", "QZSS", "IRNSS"]:
            var = tk.IntVar(value=1)
            cb = tk.Checkbutton(col2, text=name, variable=var)
            cb.pack(anchor="w", pady=2)
            self.chk_vars[name] = var

        # ---------------------------------------------------
        # RADIAL CORRECTED CLOCK (RCC)
        # ---------------------------------------------------
        if self.mode == 'clock_compare':
            radial_corrected_clock_frame = ttk.LabelFrame(self.left_panel, text="Radial Corrected Clock (RCC)", padding=5)
            radial_corrected_clock_frame.pack(padx=5, pady=10, fill="x")

            self.radial_correct_check = tk.IntVar(value=1)

            chk_radial_corrected_clock = tk.Checkbutton(
                radial_corrected_clock_frame,
                text="Enable RCC",
                variable=self.radial_correct_check,
                command=self._toggle_rcc_import_buttons,   # <-- ADD
            )
            chk_radial_corrected_clock.pack(anchor="w", pady=2)

            rad_corr_clock_row = tk.Frame(radial_corrected_clock_frame)
            rad_corr_clock_row.pack(fill="x", pady=(0, 5))

            # NOTE: RCC SP3 import must be separate from CLK import
            self.rcc_ref_sp3_btn = ttk.Button(             # <-- self.
                rad_corr_clock_row,
                text="Import Ref. SP3(s)",
                command=self.import_rcc_reference_sp3
            )
            self.rcc_ref_sp3_btn.pack(side="left", expand=True, fill="x", padx=(0, 3))

            self.rcc_tgt_sp3_btn = ttk.Button(             # <-- self.
                rad_corr_clock_row,
                text="Import Tar. SP3(s)",
                command=self.import_rcc_target_sp3
            )
            self.rcc_tgt_sp3_btn.pack(side="left", expand=True, fill="x", padx=(3, 0))


        # ---------------------------------------------------
        # SAMPLING STRATEGY (CHECKMARK STYLE)
        # ---------------------------------------------------
        sampling_frame = ttk.LabelFrame(self.left_panel, text="Sampling Strategy", padding=5)
        sampling_frame.pack(padx=5, pady=10, fill="x")

        # Default sampling option
        self.sampling_option = "common"

        # Checkbutton variables
        self.cb_common = tk.IntVar(value=1)  # default selected
        self.cb_higher = tk.IntVar(value=0)

        # Callback for mutual exclusivity
        def update_sampling_common():
            if self.cb_common.get() == 1:
                self.cb_higher.set(0)
                self.sampling_option = "common"
            else:
                self.cb_higher.set(1)
                self.sampling_option = "higher"

        def update_sampling_higher():
            if self.cb_higher.get() == 1:
                self.cb_common.set(0)
                self.sampling_option = "higher"
            else:
                self.cb_common.set(1)
                self.sampling_option = "common"

        chk_common = tk.Checkbutton(
            sampling_frame,
            text="Common Epochs (No Interpolation)",
            variable=self.cb_common,
            command=update_sampling_common
        )
        chk_common.pack(anchor="w", pady=2)

        chk_higher = tk.Checkbutton(
            sampling_frame,
            text="Higher Sampling (Interpolation)",
            variable=self.cb_higher,
            command=update_sampling_higher
        )
        chk_higher.pack(anchor="w", pady=2)

        # ---------------------------------------------------
        # OUTPUT OPTIONS FRAME
        # ---------------------------------------------------
        output_frame = ttk.LabelFrame(self.left_panel, text="Output", padding=5)
        output_frame.pack(padx=5, pady=10, fill="x")

        # 1) EPOCHWISE OUTPUT
        self.save_epochwise_var = tk.IntVar(value=1)

        chk_save_epochwise = tk.Checkbutton(
            output_frame,
            text="Save Epochwise Statistics",
            variable=self.save_epochwise_var,
            command=self._toggle_epochwise_state
        )
        chk_save_epochwise.pack(anchor="w", pady=(2, 0))

        epoch_inner = tk.Frame(output_frame)
        epoch_inner.pack(fill="x", padx=20, pady=5)

        epoch_path_frame = tk.Frame(epoch_inner)
        epoch_path_frame.pack(fill="x", pady=(0, 5))

        self.epoch_output_var = tk.StringVar()
        self.epoch_output_var.set(os.getcwd())

        self.epoch_entry = ttk.Entry(epoch_path_frame, textvariable=self.epoch_output_var)
        self.epoch_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.epoch_browse = ttk.Button(
            epoch_path_frame,
            text="...",
            width=3,
            command=self.select_epochwise_output_path
        )
        self.epoch_browse.pack(side="left")

        # ECLIPSE OPTION (Orbit compare only)
        self.find_eclipse_var = tk.IntVar(value=0)
        self.chk_find_eclipse = tk.Checkbutton(
            epoch_inner,
            text="Find Eclipse Epoch (Umbra/Penumbra)",
            variable=self.find_eclipse_var
        )
        self.chk_find_eclipse.pack(anchor="w", pady=(0, 5))

        sep = ttk.Separator(output_frame, orient="horizontal")
        sep.pack(fill="x", pady=10)

        # 2) OVERALL OUTPUT
        self.save_overall_var = tk.IntVar(value=1)

        chk_save_overall = tk.Checkbutton(
            output_frame,
            text="Save Overall Statistics",
            variable=self.save_overall_var,
            command=self._toggle_overall_state
        )
        chk_save_overall.pack(anchor="w", pady=(2, 0))

        overall_inner = tk.Frame(output_frame)
        overall_inner.pack(fill="x", padx=20, pady=5)

        overall_path_frame = tk.Frame(overall_inner)
        overall_path_frame.pack(fill="x")

        self.overall_output_var = tk.StringVar()
        self.overall_output_var.set(os.getcwd())

        self.overall_entry = ttk.Entry(overall_path_frame, textvariable=self.overall_output_var)
        self.overall_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.overall_browse = ttk.Button(
            overall_path_frame,
            text="...",
            width=3,
            command=self.select_overall_output_path
        )
        self.overall_browse.pack(side="left")

        # INITIAL STATE UPDATE
        self._toggle_epochwise_state()
        self._toggle_overall_state()
        self._toggle_rcc_import_buttons()

        # ---------------------------------------------------
        # RUN BUTTON (BOTTOM)
        # ---------------------------------------------------
        btn_bottom = tk.Frame(self.left_panel)
        btn_bottom.pack(side="bottom", padx=5, pady=5, fill="x")

        run_button = tk.Button(
            btn_bottom,
            text="RUN",
            font=("Helvetica", 12, "bold"),
            padx=5,
            pady=10,
            cursor="hand2",
            command=self.run_process
        )
        run_button.pack(side="right", expand=True, fill="x")

        # MAIN AREA ---------------------------------------------------
        self.main_area = tk.Frame(frame)
        self.main_area.pack(side="left", fill="both", expand=True)

        columns = ("Reference File", "Target File", "Date", "Status")
        self.tree = ttk.Treeview(self.main_area, columns=columns, show="tree headings")
        self.tree.pack(side="left", fill="both", expand=True)

        # ZEBRA STRIPING
        self.tree.tag_configure("odd",  background="#f0f0f0")
        self.tree.tag_configure("even", background="#ffffff")

        # Matched / unmatched (foreground only)
        self.tree.tag_configure("unmatched", foreground="red")
        self.tree.tag_configure("matched",   foreground="black")

        self.tree.bind("<Button-1>", self._on_tree_click)

        scrollbar = ttk.Scrollbar(self.main_area, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        # TREEVIEW CONFIGURATION
        self.tree.heading("#0", text="")
        self.tree.column("#0", width=25, stretch=False)

        narrow_width = 120
        wide_width = narrow_width * 2

        for col in columns:
            if col in ["Reference File", "Target File"]:
                self.tree.column(col, width=wide_width, anchor="w", stretch=True)
            else:
                self.tree.column(col, width=narrow_width, anchor="center", stretch=True)
            self.tree.heading(col, text=col)

    # ------------------------------------------------------
    def _get_mode_for_naming(self):
        return "orbit" if self.mode == "orbit_compare" else "clock"

    def get_selected_system_prefixes(self):
        systems = []
        for name, var in self.chk_vars.items():
            if var.get() == 1:
                prefix = self.sat_system_prefix.get(name)
                if prefix:
                    systems.append(prefix)
        return systems

    def _on_tree_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region == "nothing":
            self.tree.selection_remove(*self.tree.selection())

    def reset_all_values(self):
        for item in self.tree.get_children():
            vals = list(self.tree.item(item, "values"))
            vals[2] = ""
            vals[3] = "Imported"
            self.tree.item(item, values=vals)
        tk.messagebox.showinfo("Info", "All computed comparison values have been reset.")

    # ------------------------------------------------------
    # RCC HELPERS
    # ------------------------------------------------------
    def _toggle_rcc_import_buttons(self):
        """Enable/disable RCC SP3 import buttons and Eclipse option based on RCC checkbox (clock_compare only)."""
        if self.mode != "clock_compare":
            return

        rcc_on = (self.radial_correct_check.get() == 1)
        state = "normal" if rcc_on else "disabled"

        # RCC import buttons
        if getattr(self, "rcc_ref_sp3_btn", None) is not None:
            self.rcc_ref_sp3_btn.configure(state=state)
        if getattr(self, "rcc_tgt_sp3_btn", None) is not None:
            self.rcc_tgt_sp3_btn.configure(state=state)

        # Eclipse checkbox should follow RCC state
        if getattr(self, "chk_find_eclipse", None) is not None:
            self.chk_find_eclipse.configure(state=state)
            if not rcc_on:
                self.find_eclipse_var.set(0)


    def _extract_prefix_from_filename(self, path_or_name: str) -> str:
        name = os.path.basename(path_or_name)
        name_up = name.upper()

        # ----------------------------------
        # 1) LONG FORMAT (v3)
        # ----------------------------------
        # IGS2R03FIN_20220010000_01D_30S_CLK.CLK → IGS2R03FIN
        if "_" in name_up:
            return name_up.split("_")[0]

        # ----------------------------------
        # 2) SHORT FORMAT (v2)
        # ----------------------------------
        # igs21501.clk → IGS
        m = re.match(r"([A-Z]{3})\d{4,5}", name_up)
        if m:
            return m.group(1)

        return ""


    def _extract_date_sp3(self, path):
        d, _, _ = read_sp3_headerline(path)
        return d.strftime("%Y-%m-%d")

    def _update_rcc_row(self, parent_item):
        entry = self.rcc_sp3_paths.get(parent_item, {"ref": None, "tgt": None})
        ref_sp3 = entry.get("ref")
        tgt_sp3 = entry.get("tgt")

        child = self.rcc_tree_items.get(parent_item)

        if not ref_sp3 and not tgt_sp3:
            if child and self.tree.exists(child):
                self.tree.delete(child)
            self.rcc_tree_items.pop(parent_item, None)
            return

        ref_name = os.path.basename(ref_sp3) if ref_sp3 else ""
        tgt_name = os.path.basename(tgt_sp3) if tgt_sp3 else ""
        status = "RCC SP3 Matched" if (ref_name and tgt_name) else "RCC SP3 Imported"

        parent_tags = list(self.tree.item(parent_item, "tags"))
        zebra = "odd" if "odd" in parent_tags else "even"
        mt = "matched" if (ref_name and tgt_name) else "unmatched"

        if child and self.tree.exists(child):
            self.tree.item(child, values=(ref_name, tgt_name, "", status), tags=(zebra, mt))
        else:
            child = self.tree.insert(
                parent_item, "end",
                values=(ref_name, tgt_name, "", status),
                tags=(zebra, mt)
            )
            self.rcc_tree_items[parent_item] = child

        self.tree.item(parent_item, open=True)


    # ------------------------------------------------------
    # MULTIPROCESS WORKER (for Kill Process support)
    # ------------------------------------------------------
    @staticmethod
    def _comparison_worker(payload, q):
        """Multiprocess worker for one comparison item (allows Kill/terminate)."""
        try:
            mode = payload.get("mode")
            ref_path = payload.get("ref_path")
            tgt_path = payload.get("tgt_path")
            date_str = payload.get("date_str")

            sampling_option = payload.get("sampling_option", "common")
            interpolate_coordinate = bool(payload.get("interpolate_coordinate", False))
            selected_systems = payload.get("selected_systems", [])

            save_epochwise = int(payload.get("save_epochwise", 0))
            epoch_folder = payload.get("epoch_folder", "")
            save_overall = int(payload.get("save_overall", 0))
            overall_folder = payload.get("overall_folder", "")

            eclipse_enabled = bool(payload.get("eclipse_enabled", False))

            rcc_enabled = bool(payload.get("rcc_enabled", False))
            rcc_ref_sp3 = payload.get("rcc_ref_sp3")
            rcc_tgt_sp3 = payload.get("rcc_tgt_sp3")

            # LOAD FILES
            if mode == "orbit_compare":
                ref_df = read_sp3(ref_path)
                tgt_df = read_sp3(tgt_path)
            else:
                nanosec = 1e9
                #ref_df = read_clk(ref_path)
                #tgt_df = read_clk(tgt_path)                
                
                ext_ref_path = Path(ref_path).suffix.lower()
                if ext_ref_path in [".sp3", ".eph", ".eph_m"]:
                    ref_df = read_sp3(ref_path)
                    ref_df = (
                        ref_df[['epoch', 'sat', 'clk']]
                        .rename(columns={'clk': 'clock'})
                        .loc[np.isfinite(ref_df['clk'])]
                        .reset_index(drop=True)
                    )
                else:
                    ref_df = read_clk(ref_path)               
                
                
                ext_tgt_path = Path(tgt_path).suffix.lower()
                if ext_tgt_path in [".sp3", ".eph", ".eph_m"]:
                    tgt_df = read_sp3(tgt_path)
                    tgt_df = (
                        tgt_df[['epoch', 'sat', 'clk']]
                        .rename(columns={'clk': 'clock'})
                        .loc[np.isfinite(tgt_df['clk'])]
                        .reset_index(drop=True)
                    )
                else:
                    tgt_df = read_clk(tgt_path)
                    
                
                
                ref_df["clock"] = ref_df["clock"] * nanosec
                tgt_df["clock"] = tgt_df["clock"] * nanosec

            # ALIGN
            df_align = align_reference_target(
                ref_df, tgt_df,
                sampling_option=sampling_option,
                interpolate_coordinate=interpolate_coordinate,
                system=selected_systems
            )

            naming_mode = "orbit" if mode == "orbit_compare" else "clock"

            # ANALYSIS + OUTPUTS
            if mode == "orbit_compare":
                df_vel = predict_velocity(df_align, k=10, dt=0.001)
                df_rac = compute_rac(df_vel)

                df_ecl = None
                if eclipse_enabled:
                    df_ecl = SunEarthGeometry.compute_eclipse(df_rac)

                if save_epochwise == 1:
                    os.makedirs(epoch_folder, exist_ok=True)
                    out_name = build_output_filename(ref_path, tgt_path, date_str, mode=naming_mode, type="epoch_wise")
                    out_file = os.path.join(epoch_folder, out_name)

                    if df_ecl is not None:
                        write_rac_output(df_ecl, out_file, ref_path, tgt_path, system=selected_systems, eclipse=True)
                    else:
                        write_rac_output(df_rac, out_file, ref_path, tgt_path, system=selected_systems, eclipse=False)

                if save_overall == 1:
                    os.makedirs(overall_folder, exist_ok=True)
                    out_name = build_output_filename(ref_path, tgt_path, date_str, mode=naming_mode, type="summary")
                    out_file = os.path.join(overall_folder, out_name)

                    df_sum = compute_overall_rac_stats(df_ecl if df_ecl is not None else df_rac)
                    write_rac_output_overall(df_sum, out_file, ref_path, tgt_path, system=selected_systems)

            else:
                # ---------------- CLOCK COMPARISON --------------------
                df_stats, df_clock = compute_clock_stats(df_align)
                # Apply RCC (Radial Corrected Clock) if enabled AND both SP3 files exist
                if rcc_enabled and rcc_ref_sp3 and rcc_tgt_sp3:
                    # determine clock interval (robust)
                    try:
                        #diffs = df_clock["epoch"].sort_values().diff().dropna()
                        diffs = df_clock["epoch"].drop_duplicates().sort_values().diff().dropna()
                        interval = diffs.iloc[0] if len(diffs) > 0 else None
                    except Exception:
                        interval = None
                        

                    rcc_ref_sp3_df_v0 = read_sp3(rcc_ref_sp3)
                    rcc_tgt_sp3_df_v0 = read_sp3(rcc_tgt_sp3)

                    if interval is not None:
                        rcc_ref_sp3_df = densify_sp3_epoch(rcc_ref_sp3_df_v0, interval)
                        rcc_tgt_sp3_df = densify_sp3_epoch(rcc_tgt_sp3_df_v0, interval)
                    else:
                        # fallback: use original sampling
                        rcc_ref_sp3_df = rcc_ref_sp3_df_v0
                        rcc_tgt_sp3_df = rcc_tgt_sp3_df_v0
                        
                    rcc_df_align = align_reference_target(
                        rcc_ref_sp3_df, rcc_tgt_sp3_df,
                        sampling_option="higher",
                        interpolate_coordinate=True
                    )

                    rcc_df_vel = predict_velocity(rcc_df_align, k=10, dt=0.001)
                    rcc_df_rac = compute_rac(rcc_df_vel)

                    rcc_df_ecl = None
                    if eclipse_enabled:
                        rcc_df_ecl = SunEarthGeometry.compute_eclipse(rcc_df_rac)

                    df_rcc_clk = df_clock[["epoch", "sat", "sat_delta"]].rename(columns={"sat_delta": "clock"})

                    df_rcc_sp3 = rcc_df_rac[["epoch", "sat", "radial"]].copy()
                    df_rcc_sp3["radial_ns"] = df_rcc_sp3["radial"] * (nanosec / C / 100)
                    df_rcc_sp3 = df_rcc_sp3.rename(columns={"radial_ns": "clock"})

                    df_align_last = align_reference_target(
                        df_rcc_clk, df_rcc_sp3,
                        sampling_option="common",
                        interpolate_coordinate=False
                    )
                    
                    df_clock_rcc = df_align_last.rename(columns={"clock_ref": "sat_delta", "clock_tgt": "radial_ns"})
                    df_clock_rcc["Rclk"] = df_clock_rcc["sat_delta"] - df_clock_rcc["radial_ns"]
                    df_clock = df_clock_rcc[["epoch", "sat", "sat_delta", "Rclk"]]

                    if eclipse_enabled and (rcc_df_ecl is not None):
                        df_clock = df_clock.merge(
                            rcc_df_ecl[["epoch", "sat", "eclipse"]],
                            on=["epoch", "sat"],
                            how="left"
                        )

                    df_stats = (
                        df_clock.groupby("sat")
                            .agg(
                                rms_ns=("sat_delta", lambda x: np.sqrt(np.mean(x**2))),
                                std_ns=("sat_delta", lambda x: np.std(x)),
                                Rclk_rms_ns=("Rclk", lambda x: np.sqrt(np.mean(x**2))),
                                Rclk_std_ns=("Rclk", lambda x: np.std(x)),
                            )
                            .reset_index()
                    )
                    df_stats["Rclk_rms_cm"] = df_stats["Rclk_rms_ns"] * (1e-9 * C) * 100
                    df_stats["Rclk_std_cm"] = df_stats["Rclk_std_ns"] * (1e-9 * C) * 100
                    df_stats["rms_cm"] = df_stats["rms_ns"] * (1e-9 * C) * 100
                    df_stats["std_cm"] = df_stats["std_ns"] * (1e-9 * C) * 100
                else:
                    # RCC is off or incomplete
                    rcc_ref_sp3 = None
                    rcc_tgt_sp3 = None

                if save_epochwise == 1:
                    os.makedirs(epoch_folder, exist_ok=True)
                    out_name = build_output_filename(ref_path, tgt_path, date_str, mode=naming_mode, type="epoch_wise")
                    out_file = os.path.join(epoch_folder, out_name)

                    write_clock_output(
                        df_clock, out_file, ref_path, tgt_path,
                        reference_sp3_file=rcc_ref_sp3, target_sp3_file=rcc_tgt_sp3,
                        system=selected_systems
                    )

                if save_overall == 1:
                    os.makedirs(overall_folder, exist_ok=True)
                    out_name = build_output_filename(ref_path, tgt_path, date_str, mode=naming_mode, type="summary")
                    out_file = os.path.join(overall_folder, out_name)
                    
                    write_clock_stats_overall(
                        df_stats, out_file,
                        ref_path, tgt_path,
                        reference_sp3_file=rcc_ref_sp3, target_sp3_file=rcc_tgt_sp3,
                        system=selected_systems
                    )

            q.put({"ok": True})
        except Exception:
            import traceback
            q.put({"ok": False, "err": traceback.format_exc()})

    # ------------------------------------------------------
    # RUN PROCESS
    # ------------------------------------------------------

    def run_process(self):
        items = list(self.tree.get_children())
        total_items = len(items)

        if total_items == 0:
            tk.messagebox.showinfo("Info", "No files to process.")
            return

        self._cancel_requested = False
        self._active_proc = None
        self._active_q = None

        # PROGRESS WINDOW
        progress_win = tk.Toplevel(self.parent)
        progress_win.withdraw()
        progress_win.title("Processing...")
        progress_win.resizable(False, False)
        progress_win.transient(self.parent)
        progress_win.grab_set()

        w, h = 380, 200
        root = self.parent.winfo_toplevel()
        rx, ry = root.winfo_x(), root.winfo_y()
        rw, rh = root.winfo_width(), root.winfo_height()
        posx = rx + (rw // 2) - (w // 2)
        posy = ry + (rh // 2) - (h // 2)
        progress_win.geometry(f"{w}x{h}+{posx}+{posy}")

        tk.Label(progress_win, text="Processing, please wait...", font=("Arial", 11)).pack(pady=(10, 6))

        pb = ttk.Progressbar(progress_win, mode="determinate", length=300)
        pb.pack(pady=6)
        pb["value"] = 0
        pb["maximum"] = total_items

        percent_label = ttk.Label(progress_win, text="0%")
        percent_label.pack(pady=(2, 4))

        status_label = ttk.Label(progress_win, text="", font=("Arial", 10))
        status_label.pack(pady=(2, 6))

        btn_row = tk.Frame(progress_win)
        btn_row.pack(fill="x", padx=12, pady=(2, 10))

        def _kill():
            self._cancel_requested = True
            try:
                if self._active_proc is not None and self._active_proc.is_alive():
                    self._active_proc.terminate()
                    self._active_proc.join(timeout=0.2)
            except Exception:
                pass

            try:
                if progress_win.winfo_exists():
                    progress_win.destroy()
            except Exception:
                pass

            for it in self.tree.get_children():
                vals = list(self.tree.item(it, "values"))
                if len(vals) >= 4:
                    vals[3] = "Imported"
                    self.tree.item(it, values=vals)

        tk.Button(
            btn_row,
            text="Kill Process",
            font=("Helvetica", 11),
            padx=10,
            pady=6,
            cursor="hand2",
            command=_kill
        ).pack(expand=True)

        # Disable closing the progress window (use Kill Process)
        progress_win.protocol("WM_DELETE_WINDOW", lambda: None)
        progress_win.deiconify()
        progress_win.update_idletasks()

        def _start_one(idx: int):
            if self._cancel_requested:
                return

            if idx >= total_items:
                if progress_win.winfo_exists():
                    progress_win.destroy()
                tk.messagebox.showinfo("Info", "Processing complete!")
                return

            item = items[idx]
            paths = self.file_paths.get(item, {})
            ref_path = paths.get("ref")
            tgt_path = paths.get("tgt")

            vals = list(self.tree.item(item, "values"))
            date_str = vals[2] if len(vals) > 2 else ""

            status_label.config(text=f"{idx+1}/{total_items}: {date_str}")
            progress_win.update_idletasks()

            if not (ref_path and tgt_path and date_str):
                #pb["value"] = idx + 1
                #percent_label.config(text=f"{int(((idx+1)/total_items)*100)}%")
                    
                save_will_run = (
                    self.save_epochwise_var.get() == 1 or
                    self.save_overall_var.get() == 1
                )

                pb["value"] = idx + 1
                percent = int(((idx + 1) / total_items) * 100)

                if percent == 100 and save_will_run:
                    percent_label.config(
                        text="Orbit comparison completed.\n"
                             "Statistics are writing to file(s). Please wait..."
                    )
                else:
                    percent_label.config(text=f"{percent}%")
                self.parent.after(10, lambda: _start_one(idx + 1))
                return

            sampling_option = getattr(self, "sampling_option", "common")
            interpolate_coordinate = (sampling_option == "higher")
            selected_systems = self.get_selected_system_prefixes()

            eclipse_enabled = bool(getattr(self, "find_eclipse_var", tk.IntVar(value=0)).get() == 1)

            # RCC SP3 (clock_compare only)
            rcc_enabled = False
            rcc_ref_sp3 = None
            rcc_tgt_sp3 = None
            if self.mode == "clock_compare":
                try:
                    rcc_enabled = bool(getattr(self, "radial_correct_check", tk.IntVar(value=0)).get() == 1)
                except Exception:
                    rcc_enabled = False
                if rcc_enabled:
                    rcc_entry = self.rcc_sp3_paths.get(item, {}) or {}
                    rcc_ref_sp3 = rcc_entry.get("ref")
                    rcc_tgt_sp3 = rcc_entry.get("tgt")

            payload = {
                "mode": self.mode,
                "ref_path": ref_path,
                "tgt_path": tgt_path,
                "date_str": date_str,
                "sampling_option": sampling_option,
                "interpolate_coordinate": bool(interpolate_coordinate),
                "selected_systems": selected_systems,

                "save_epochwise": int(getattr(self, "save_epochwise_var", tk.IntVar(value=0)).get()),
                "epoch_folder": getattr(self, "epoch_output_var", tk.StringVar(value="")).get().strip() if getattr(self, "epoch_output_var", None) is not None else "",
                "save_overall": int(getattr(self, "save_overall_var", tk.IntVar(value=0)).get()),
                "overall_folder": getattr(self, "overall_output_var", tk.StringVar(value="")).get().strip() if getattr(self, "overall_output_var", None) is not None else "",

                "eclipse_enabled": eclipse_enabled,

                "rcc_enabled": rcc_enabled,
                "rcc_ref_sp3": rcc_ref_sp3,
                "rcc_tgt_sp3": rcc_tgt_sp3,
            }

            self._active_q = mp.Queue()
            self._active_proc = mp.Process(
                target=ComparisonTab._comparison_worker,
                args=(payload, self._active_q),
                daemon=True
            )
            self._active_proc.start()

            def _poll():
                if self._cancel_requested or (not progress_win.winfo_exists()):
                    return

                if self._active_q is not None and (not self._active_q.empty()):
                    msg = self._active_q.get()
                    ok = bool(msg.get("ok", False))

                    vals2 = list(self.tree.item(item, "values"))
                    if len(vals2) >= 4:
                        vals2[3] = "Analyzed" if ok else "Error"
                        self.tree.item(item, values=vals2)

                    if not ok:
                        print("Comparison worker error:\n", msg.get("err", ""))

                    try:
                        if self._active_proc is not None and self._active_proc.is_alive():
                            self._active_proc.join(timeout=0.1)
                    except Exception:
                        pass
                    self._active_proc = None

                    #pb["value"] = idx + 1
                    #percent_label.config(text=f"{int(((idx+1)/total_items)*100)}%")
                    
                    save_will_run = (
                        self.save_epochwise_var.get() == 1 or
                        self.save_overall_var.get() == 1
                    )

                    pb["value"] = idx + 1
                    percent = int(((idx + 1) / total_items) * 100)

                    if percent == 100 and save_will_run:
                        percent_label.config(
                            text="Orbit comparison completed.\n"
                                 "Statistics are writing to file(s). Please wait..."
                        )
                    else:
                        percent_label.config(text=f"{percent}%")
                        
                        
                    progress_win.update_idletasks()

                    self.parent.after(10, lambda: _start_one(idx + 1))
                    return

                self.parent.after(100, _poll)

            _poll()

        self.parent.after(50, lambda: _start_one(0))


    # ------------------------------------------------------
    # OUTPUT PATHS
    # ------------------------------------------------------
    def select_epochwise_output_path(self):
        folder = filedialog.askdirectory(
            title="Select Folder for Epochwise Output",
            initialdir=os.getcwd()
        )
        if folder:
            self.epoch_output_var.set(folder)

    def select_overall_output_path(self):
        folder = filedialog.askdirectory(
            title="Select Folder for Overall Output",
            initialdir=os.getcwd()
        )
        if folder:
            self.overall_output_var.set(folder)

    def _toggle_epochwise_state(self):
        state = "normal" if self.save_epochwise_var.get() == 1 else "disabled"
        self.epoch_entry.configure(state=state)
        self.epoch_browse.configure(state=state)

    def _toggle_overall_state(self):
        state = "normal" if self.save_overall_var.get() == 1 else "disabled"
        self.overall_entry.configure(state=state)
        self.overall_browse.configure(state=state)

    # ------------------------------------------------------
    # IMPORT (MAIN) REFERENCE FILES (SP3 or CLK by mode)
    # ------------------------------------------------------
    def import_reference(self):
        if self.mode == "orbit_compare":
            filetypes = [("Orbit files", ("*.sp3", "*.SP3", "*.eph", "*.EPH")), ("All files", "*.*")]
        else:
            filetypes = [("Clock files", ("*.clk", "*.CLK", "*.CLK_05S", "*.CLK_30S")), 
                         ("Orbit files", ("*.sp3", "*.SP3", "*.eph", "*.EPH")),
                         ("All files", "*.*")]

        files = filedialog.askopenfilenames(title="Select Reference Files", filetypes=filetypes)
        if not files:
            return

        import_win, pb = self._open_import_dialog()
        try:
            for path in files:
                fname = os.path.basename(path)
                date_str = self._extract_date(path)

                self._insert_or_match_row(
                    ref_value=fname, tgt_value="",
                    date_str=date_str,
                    path_ref=path, path_tgt=None
                )
        finally:
            pb.stop()
            import_win.destroy()

    # ------------------------------------------------------
    # IMPORT (MAIN) TARGET FILES (SP3 or CLK by mode)
    # ------------------------------------------------------
    def import_target(self):
        if self.mode == "orbit_compare":
            filetypes = [("Orbit files", ("*.sp3", "*.SP3", "*.eph", "*.EPH")), ("All files", "*.*")]
        else:
            filetypes = [("Clock files", ("*.clk", "*.CLK", "*.CLK_05S", "*.CLK_30S")), 
                         ("Orbit files", ("*.sp3", "*.SP3", "*.eph", "*.EPH")),
                         ("All files", "*.*")]

        files = filedialog.askopenfilenames(title="Select Target Files", filetypes=filetypes)
        if not files:
            return

        import_win, pb = self._open_import_dialog()
        try:
            for path in files:
                fname = os.path.basename(path)
                date_str = self._extract_date(path)

                self._insert_or_match_row(
                    ref_value="", tgt_value=fname,
                    date_str=date_str,
                    path_ref=None, path_tgt=path
                )
        finally:
            pb.stop()
            import_win.destroy()

    # ------------------------------------------------------
    # RCC IMPORT: SP3 files must be imported AFTER CLK rows exist
    # ------------------------------------------------------
    def import_rcc_reference_sp3(self):
        """
        Import RCC (Radial Corrected Clock) *reference* SP3 files.

        Rules:
          - RCC SP3 files can only be attached to existing CLK rows.
          - Matching is done using (date, prefix), where:
              * date   : extracted from SP3 header
              * prefix : first '_' separated token in filename
          - If no matching CLK row exists, the SP3 file is rejected with a warning.
          - Successfully imported SP3 files are displayed as a child row
            directly under the matched CLK row.
        """

        filetypes = [
            ("Orbit files", ("*.sp3", "*.SP3", "*.eph", "*.EPH")),
            ("All files", "*.*")
        ]

        files = filedialog.askopenfilenames(
            title="Select RCC Reference SP3 Files",
            filetypes=filetypes
        )
        if not files:
            return

        import_win, pb = self._open_import_dialog()

        try:
            for path in files:
                # --------------------------------------------------
                # Extract matching keys from SP3
                # --------------------------------------------------
                try:
                    date_str = self._extract_date_sp3(path)
                except Exception:
                    messagebox.showwarning(
                        "Warning",
                        f"Could not extract date from SP3 file:\n{os.path.basename(path)}"
                    )
                    continue

                prefix = self._extract_prefix_from_filename(path)

                # --------------------------------------------------
                # Find matching CLK row using (date, prefix)
                # --------------------------------------------------
                item = self._find_clk_row_for_rcc(date_str, prefix)
                if item is None:
                    messagebox.showwarning(
                        "Missing CLK",
                        "RCC SP3 import requires existing CLK files "
                        "with the same date and prefix.\n\n"
                        f"Date   : {date_str}\n"
                        f"Prefix : {prefix}\n"
                        f"SP3    : {os.path.basename(path)}"
                    )
                    continue

                # --------------------------------------------------
                # Store RCC reference SP3 path
                # --------------------------------------------------
                entry = self.rcc_sp3_paths.get(item, {"ref": None, "tgt": None})
                entry["ref"] = path
                self.rcc_sp3_paths[item] = entry

                # --------------------------------------------------
                # Update / create RCC child row under the CLK row
                # --------------------------------------------------
                self._update_rcc_row(item)

        finally:
            pb.stop()
            import_win.destroy()


    def import_rcc_target_sp3(self):
        """
        Import RCC (Radial Corrected Clock) *target* SP3 files.

        Rules:
          - RCC SP3 files can only be attached to existing CLK rows.
          - Matching is done using (date, prefix), where:
              * date   : extracted from SP3 header
              * prefix : first '_' separated token in filename
          - If no matching CLK row exists, the SP3 file is rejected with a warning.
          - Successfully imported SP3 files are displayed as a child row
            directly under the matched CLK row.
        """

        filetypes = [
            ("Orbit files", ("*.sp3", "*.SP3", "*.eph", "*.EPH")),
            ("All files", "*.*")
        ]

        files = filedialog.askopenfilenames(
            title="Select RCC Target SP3 Files",
            filetypes=filetypes
        )
        if not files:
            return

        import_win, pb = self._open_import_dialog()

        try:
            for path in files:
                # --------------------------------------------------
                # Extract matching keys from SP3
                # --------------------------------------------------
                try:
                    date_str = self._extract_date_sp3(path)
                except Exception:
                    messagebox.showwarning(
                        "Warning",
                        f"Could not extract date from SP3 file:\n{os.path.basename(path)}"
                    )
                    continue

                prefix = self._extract_prefix_from_filename(path)

                # --------------------------------------------------
                # Find matching CLK row using (date, prefix)
                # --------------------------------------------------
                item = self._find_clk_row_for_rcc(date_str, prefix)
                if item is None:
                    messagebox.showwarning(
                        "Missing CLK",
                        "RCC SP3 import requires existing CLK files "
                        "with the same date and prefix.\n\n"
                        f"Date   : {date_str}\n"
                        f"Prefix : {prefix}\n"
                        f"SP3    : {os.path.basename(path)}"
                    )
                    continue

                # --------------------------------------------------
                # Store RCC target SP3 path
                # --------------------------------------------------
                entry = self.rcc_sp3_paths.get(item, {"ref": None, "tgt": None})
                entry["tgt"] = path
                self.rcc_sp3_paths[item] = entry

                # --------------------------------------------------
                # Update / create RCC child row under the CLK row
                # --------------------------------------------------
                self._update_rcc_row(item)

        finally:
            pb.stop()
            import_win.destroy()


    # ------------------------------------------------------
    def _extract_date(self, path):
        try:
            if self.mode == "orbit_compare":
                d, _, _ = read_sp3_headerline(path)
                return d.strftime("%Y-%m-%d")
            else:
                ext_path = Path(path).suffix.lower()
                if ext_path in [".sp3", ".eph", ".eph_m"]:
                    d, _, _ = read_sp3_headerline(path)
                    return d.strftime("%Y-%m-%d")
                else:
                    return read_clk_date(path)

        except Exception:
            return ""


    def _open_import_dialog(self):
        win = tk.Toplevel(self.parent)
        win.title("Please wait...")
        win.resizable(False, False)
        win.transient(self.parent)
        win.grab_set()

        w, h = 300, 120
        root = self.parent.winfo_toplevel()
        rx, ry = root.winfo_x(), root.winfo_y()
        rw, rh = root.winfo_width(), root.winfo_height()
        posx = rx + (rw // 2) - (w // 2)
        posy = ry + (rh // 2) - (h // 2)
        win.geometry(f"{w}x{h}+{posx}+{posy}")

        tk.Label(win, text="File(s) are importing...", font=("Arial", 11)).pack(pady=20)

        pb = ttk.Progressbar(win, mode="indeterminate", length=250)
        pb.pack()
        pb.start()

        win.update_idletasks()
        return win, pb

    def _insert_or_match_row(self, ref_value, tgt_value, date_str, path_ref, path_tgt):
        """
        Insert or update a TreeView row based on DATE only.

        - Reference CLK and Target CLK are matched ONLY by date_str.
        - Prefix is NOT used here (prefix will be used later for RCC SP3 matching).
        """

        matched_row = None

        # 1) Find an existing top-level row with the same date
        for item in self.tree.get_children():
            vals = list(self.tree.item(item, "values"))  # (ref, tgt, date, status)
            row_date = vals[2] if len(vals) > 2 else ""
            if row_date == date_str:
                matched_row = item
                break

        # 2) Update existing row
        if matched_row:
            vals = list(self.tree.item(matched_row, "values"))

            if ref_value and not vals[0]:
                vals[0] = ref_value
            if tgt_value and not vals[1]:
                vals[1] = tgt_value

            # Update stored paths
            entry = self.file_paths.get(matched_row, {"ref": None, "tgt": None})
            if path_ref:
                entry["ref"] = path_ref
            if path_tgt:
                entry["tgt"] = path_tgt
            self.file_paths[matched_row] = entry

            # Preserve zebra tag and update matched/unmatched
            current_tags = list(self.tree.item(matched_row, "tags"))
            zebra_tag = "odd" if "odd" in current_tags else "even"

            if vals[0] and vals[1]:
                vals[3] = "Matched"
                self.tree.item(matched_row, tags=(zebra_tag, "matched"))
            else:
                vals[3] = "Imported"
                self.tree.item(matched_row, tags=(zebra_tag, "unmatched"))

            self.tree.item(matched_row, values=vals)
            return matched_row

        # 3) Insert new row (zebra)
        row_index = len(self.tree.get_children())
        zebra_tag = "even" if row_index % 2 == 0 else "odd"

        item = self.tree.insert(
            "",
            "end",
            values=(ref_value, tgt_value, date_str, "Imported"),
            tags=(zebra_tag, "unmatched")
        )

        self.file_paths[item] = {"ref": path_ref, "tgt": path_tgt}
        return item

    def _find_clk_row_for_rcc(self, date_str, sp3_prefix):
        """
        Find the correct CLK parent row for an RCC SP3 using:
          - same date (mandatory)
          - and prefix match against the CLK filenames in that row (ref or tgt)
        """
        for item in self.tree.get_children():
            vals = list(self.tree.item(item, "values"))
            row_date = vals[2] if len(vals) > 2 else ""
            if row_date != date_str:
                continue

            # Check prefix match against CLK filenames in the row
            ref_clk_name = vals[0] if len(vals) > 0 else ""
            tgt_clk_name = vals[1] if len(vals) > 1 else ""

            ref_prefix = self._extract_prefix_from_filename(ref_clk_name) if ref_clk_name else ""
            tgt_prefix = self._extract_prefix_from_filename(tgt_clk_name) if tgt_clk_name else ""

            if sp3_prefix and (sp3_prefix == ref_prefix or sp3_prefix == tgt_prefix):
                return item

        return None



    # ------------------------------------------------------
    def clear_files(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Info", "No file selected.")
            return

        ok = messagebox.askyesno(
            "Confirm",
            "Selected file(s) will be removed from the list.\nDo you want to continue?"
        )
        if not ok:
            return

        for item in selected:
            # If user selected RCC child row, map it to its parent
            parent = self.tree.parent(item)
            if parent:
                # item is a child; delete parent instead (and everything under it)
                item = parent

            # delete RCC child (if exists)
            child = self.rcc_tree_items.pop(item, None)
            if child and self.tree.exists(child):
                self.tree.delete(child)

            # delete RCC paths
            self.rcc_sp3_paths.pop(item, None)

            # delete main paths and row
            self.file_paths.pop(item, None)
            if self.tree.exists(item):
                self.tree.delete(item)

    # ------------------------------------------------------
    def clear_all(self):
        items = self.tree.get_children()
        if not items:
            messagebox.showinfo("Info", "There is no file to clear.")
            return

        ok = messagebox.askyesno(
            "Confirm",
            "All files will be removed from the list.\nDo you want to continue?"
        )
        if not ok:
            return

        for it in items:
            if self.tree.exists(it):
                self.tree.delete(it)

        self.file_paths.clear()
        self.rcc_sp3_paths.clear()
        self.rcc_tree_items.clear()


    # ------------------------------------------------------
    def swap_reference_target(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Info", "Please select at least one row to swap.")
            return

        for item in selected:
            # If user selected RCC child row, swap on its parent
            parent = self.tree.parent(item)
            if parent:
                item = parent

            vals = list(self.tree.item(item, "values"))
            ref_file = vals[0]
            tgt_file = vals[1]

            if not ref_file and not tgt_file:
                continue

            vals[0], vals[1] = tgt_file, ref_file
            self.tree.item(item, values=vals)

            entry = self.file_paths.get(item, {"ref": None, "tgt": None})
            entry["ref"], entry["tgt"] = entry["tgt"], entry["ref"]
            self.file_paths[item] = entry

            # Swap RCC SP3 too (keeps consistency)
            rcc_entry = self.rcc_sp3_paths.get(item)
            if rcc_entry:
                rcc_entry["ref"], rcc_entry["tgt"] = rcc_entry.get("tgt"), rcc_entry.get("ref")
                self.rcc_sp3_paths[item] = rcc_entry
                self._update_rcc_row(item)

            tags = list(self.tree.item(item, "tags"))
            zebra = "odd" if "odd" in tags else "even"
            if vals[0] and vals[1]:
                new_tags = (zebra, "matched")
            else:
                new_tags = (zebra, "unmatched")
            self.tree.item(item, tags=new_tags)

        messagebox.showinfo("Info", "Reference and Target values swapped.")


