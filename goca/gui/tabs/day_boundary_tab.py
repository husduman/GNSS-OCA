from __future__ import annotations

import os
import tkinter as tk
import multiprocessing as mp
import traceback
from tkinter import ttk, filedialog, messagebox
from datetime import timedelta, datetime

from goca.io.read_sp3 import read_sp3_headerline
from goca.io.read_clk import read_clk, read_clk_date
from goca.io.file_utils import build_output_filename

from goca.core.day_boundary import (
    compute_day_boundary_sp3,
    compute_day_boundary_clk,
    write_rac_day_boundary,
    write_clk_day_boundary,
)


class DayBoundaryTab:
    """
    Day-boundary RAC / clock analysis GUI (GOCC UI preserved).
    """

    def __init__(self, parent_frame, mode="orbit_day"):
        self.mode = mode
        self.parent = parent_frame

        # tree item -> {'day1': path, 'day2': path}
        self.file_paths = {}

        # RCC (Radial Corrected Clock) SP3 files (only meaningful in clock_compare)
        self.rcc_sp3_paths = {}     # parent_item -> {"ref": sp3_path, "tgt": sp3_path}
        self.rcc_tree_items = {}    # parent_item -> child_item (RCC row)

        self.sat_system_prefix = {
            "GPS": "PG",
            "GLONASS": "PR",
            "Galileo": "PE",
            "BeiDou": "PC",
            "QZSS": "PJ",
            "IRNSS": "PI",
        }

        self._build_ui()

    # ==========================================================
    # UI  (UNCHANGED)
    # ==========================================================
    def _build_ui(self):
        frame = self.parent

        # LEFT PANEL
        self.left_panel = ttk.LabelFrame(frame, text="Operations", padding=5)
        self.left_panel.configure(width=350)
        self.left_panel.pack(side="left", fill="y")
        self.left_panel.pack_propagate(False)

        btn_row = tk.Frame(self.left_panel)
        btn_row.pack(pady=3, padx=3, fill="x")

        if self.mode == "orbit_day":
            day1_label = "Import Day-N SP3(s)"
            day2_label = "Import Day-N+1 SP3(s)"
        else:
            day1_label = "Import Day-N CLK(s)"
            day2_label = "Import Day-N+1 CLK(s)"

        ttk.Button(btn_row, text=day1_label, command=self.import_day1)\
            .pack(fill="x", pady=(0, 10))

        ttk.Button(btn_row, text=day2_label, command=self.import_day2)\
            .pack(fill="x", pady=(0, 10))

        ttk.Button(btn_row, text="Day-N <--> Day-N+1",
                   command=self.swap_day1_day2)\
            .pack(fill="x", pady=(0, 10))

        clear_row = tk.Frame(btn_row)
        clear_row.pack(fill="x", pady=(0, 5))

        ttk.Button(clear_row, text="Clear File(s)", command=self.clear_files)\
            .pack(side="left", expand=True, fill="x", padx=(0, 3))
        ttk.Button(clear_row, text="Clear All", command=self.clear_all)\
            .pack(side="left", expand=True, fill="x", padx=(3, 0))

        # SATELLITE SYSTEM
        self.chk_vars = {}
        sat_frame = ttk.LabelFrame(self.left_panel, text="Satellite System", padding=5)
        sat_frame.pack(padx=5, pady=10, fill="x")

        col1, col2 = tk.Frame(sat_frame), tk.Frame(sat_frame)
        col1.pack(side="left", padx=10)
        col2.pack(side="left", padx=10)

        for name in ["GPS", "GLONASS", "Galileo"]:
            var = tk.IntVar(value=1)
            tk.Checkbutton(col1, text=name, variable=var).pack(anchor="w", pady=2)
            self.chk_vars[name] = var

        for name in ["BeiDou", "QZSS", "IRNSS"]:
            var = tk.IntVar(value=1)
            tk.Checkbutton(col2, text=name, variable=var).pack(anchor="w", pady=2)
            self.chk_vars[name] = var
            
        # ---------------------------------------------------
        # RADIAL CORRECTED CLOCK (RCC)
        # ---------------------------------------------------
        if self.mode == 'clock_day':
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
                text="Import Day-N SP3(s)",
                command=self.import_rcc_day1_sp3
            )
            self.rcc_ref_sp3_btn.pack(side="left", expand=True, fill="x", padx=(0, 3))

            self.rcc_tgt_sp3_btn = ttk.Button(             # <-- self.
                rad_corr_clock_row,
                text="Import Day-N+1 SP3(s)",
                command=self.import_rcc_day2_sp3
            )
            self.rcc_tgt_sp3_btn.pack(side="left", expand=True, fill="x", padx=(3, 0))
            

        # OUTPUT
        out = ttk.LabelFrame(self.left_panel, text="Output", padding=5)
        out.pack(padx=5, pady=10, fill="x")

        self.save_stats_var = tk.IntVar(value=1)
        tk.Checkbutton(out, text="Save statistics",
                       variable=self.save_stats_var,
                       command=self._toggle_output_state)\
            .pack(anchor="w", pady=(2, 0))

        inner = tk.Frame(out)
        inner.pack(fill="x", padx=20, pady=5)

        self.output_folder_var = tk.StringVar(value=os.getcwd())
        self.output_entry = ttk.Entry(inner, textvariable=self.output_folder_var)
        self.output_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.output_browse = ttk.Button(
            inner, text="...", width=3, command=self.select_output_folder
        )
        self.output_browse.pack(side="left")

        btn_bottom = tk.Frame(self.left_panel)
        btn_bottom.pack(side="bottom", padx=5, pady=5, fill="x")

        # RUN tek buton olarak sağda kalsın
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

        self._toggle_output_state()
        self._toggle_rcc_import_buttons()

        # TREEVIEW (UNCHANGED)
        self.main_area = tk.Frame(frame)
        self.main_area.pack(side="left", fill="both", expand=True)

        cols = ("Day-N File", "Day-N+1 File", "Date", "Status")
        self.tree = ttk.Treeview(self.main_area, columns=cols, show="tree headings")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.tag_configure("odd", background="#f0f0f0")
        self.tree.tag_configure("even", background="#ffffff")
        self.tree.tag_configure("matched", foreground="black")
        self.tree.tag_configure("unmatched", foreground="red")

        scrollbar = ttk.Scrollbar(self.main_area, orient="vertical",
                                  command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.bind("<Button-1>", self._on_tree_click)

        self.tree.heading("#0", text="")
        self.tree.column("#0", width=25, stretch=False)

        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=180 if "File" in c else 120,
                             anchor="w" if "File" in c else "center")


    # ==========================================================
    # BACKEND — GOCC LOGIC, GOCA CORE
    # ==========================================================
    def get_selected_system_prefixes(self):
        return [
            self.sat_system_prefix[n]
            for n, v in self.chk_vars.items() if v.get() == 1
        ]

    def _toggle_output_state(self):
        st = "normal" if self.save_stats_var.get() == 1 else "disabled"
        self.output_entry.configure(state=st)
        self.output_browse.configure(state=st)

    def select_output_folder(self):
        p = filedialog.askdirectory(title="Select Output Folder")
        if p:
            self.output_folder_var.set(p)

    def _on_tree_click(self, e):
        if self.tree.identify_region(e.x, e.y) == "nothing":
            self.tree.selection_remove(*self.tree.selection())

    def _extract_dates(self, path, which):
        if self.mode == "orbit_day":
            dt, _, _ = read_sp3_headerline(path)
        else:
            #df = read_clk(path)
            #dt = df["epoch"].iloc[0].to_pydatetime()
            dt_str = read_clk_date(path)
            dt     = datetime.strptime(dt_str, "%Y-%m-%d")

        if which == "day1":
            d1, d2 = dt.date(), dt.date() + timedelta(days=1)
        else:
            d2, d1 = dt.date(), dt.date() - timedelta(days=1)

        return d1.strftime("%Y-%m-%d"), d2.strftime("%Y-%m-%d")



    def import_day1(self):

        if self.mode == "orbit_day":
            filetypes = [("Orbit files", ("*.sp3","*.SP3","*.eph","*.EPH")), ("All files", "*.*")]
        else:
            filetypes = [("Clock files", ("*.clk","*.CLK","*.CLK_05S","*.CLK_30S")), ("All files", "*.*")]

        files = filedialog.askopenfilenames(title="Select Day-N Files", filetypes=filetypes)

        if not files:
            return

        import_win, pb = self._open_import_dialog()

        try:
            for path in files:
                fname = os.path.basename(path)
                d1, d2 = self._extract_dates(path, "day1")
                date_str = f"{d1}_{d2[-2:]}"   # 2025-01-02/03 formatı

                self._insert_or_match_row(
                    day1_value=fname, day2_value="",
                    date_str=date_str,
                    path_day1=path, path_day2=None
                )
        finally:
            pb.stop()
            import_win.destroy()



    # ==========================================================
    # IMPORT DAY-2
    # ==========================================================
    def import_day2(self):

        if self.mode == "orbit_day":
            filetypes = [("Orbit files", ("*.sp3","*.SP3","*.eph","*.EPH")), ("All files", "*.*")]
        else:
            filetypes = [("Clock files", ("*.clk","*.CLK","*.CLK_05S","*.CLK_30S")), ("All files", "*.*")]

        files = filedialog.askopenfilenames(title="Select Day-2 Files", filetypes=filetypes)

        if not files:
            return

        import_win, pb = self._open_import_dialog()

        try:
            for path in files:
                fname = os.path.basename(path)
                d1, d2 = self._extract_dates(path, "day2")
                date_str = f"{d1}_{d2[-2:]}"   # 2025-01-02/03 formatı

                self._insert_or_match_row(
                    day1_value="", day2_value=fname,
                    date_str=date_str,
                    path_day1=None, path_day2=path
                )
        finally:
            pb.stop()
            import_win.destroy()


    @staticmethod
    def _dayboundary_worker(payload: dict, q: "mp.Queue"):
        try:
            import os
            from goca.core.day_boundary import compute_day_boundary_sp3, compute_day_boundary_clk, write_rac_day_boundary, write_clk_day_boundary
            from goca.io.file_utils import build_output_filename

            mode = payload["mode"]  # orbit_day / clock_day
            day1_path = payload["day1_path"]
            day2_path = payload["day2_path"]
            date_str = payload["date_str"]
            save_stats = payload["save_stats"]
            out_folder = payload["out_folder"]
            selected_systems = payload["selected_systems"]

            rcc_on = payload.get("rcc_on", 0)
            rcc_day1_sp3 = payload.get("rcc_day1_sp3")
            rcc_day2_sp3 = payload.get("rcc_day2_sp3")

            if mode == "orbit_day":
                df_rac = compute_day_boundary_sp3(day1_path, day2_path, sampling_option="common")
                if save_stats == 1:
                    os.makedirs(out_folder, exist_ok=True)
                    out_name = build_output_filename(day1_path, day2_path, date_str, mode="orbit", type="boundary")
                    out_file = os.path.join(out_folder, out_name)
                    write_rac_day_boundary(df_rac, out_file, day1_path, day2_path, system=selected_systems)
            else:
                df_clk_stats = compute_day_boundary_clk(day1_path, day2_path, sampling_option="common")

                if rcc_on == 1:
                    import numpy as np
                    from goca.core.alignment import align_reference_target
                    nanosec = 1e9
                    C = 299792458.0

                    df_day_rac_rcc = compute_day_boundary_sp3(rcc_day1_sp3, rcc_day2_sp3, sampling_option="common")

                    df_day_rcc_clk = df_clk_stats.rename(columns={"sat_delta": "clock"})
                    df_day_rcc_sp3 = df_day_rac_rcc[["epoch","sat","radial"]].copy()
                    df_day_rcc_sp3["clock"] = df_day_rcc_sp3["radial"] * (nanosec / C / 100)

                    df_align_day_last = align_reference_target(df_day_rcc_clk, df_day_rcc_sp3,
                                                              sampling_option="common",
                                                              interpolate_coordinate=False)

                    df_clock_rcc = df_align_day_last.rename(columns={"clock_ref":"sat_delta", "clock_tgt":"radial_ns"})
                    df_clock_rcc["Rclk"] = df_clock_rcc["sat_delta"] - df_clock_rcc["radial_ns"]
                    df_clock_rcc["Rclk_cm"] = df_clock_rcc["Rclk"] * (1e-9 * C) * 100
                    df_clk_stats = df_clock_rcc[["epoch","sat","sat_delta","sat_delta_cm","Rclk","Rclk_cm"]]

                if save_stats == 1:
                    os.makedirs(out_folder, exist_ok=True)
                    out_name = build_output_filename(day1_path, day2_path, date_str, mode="clock", type="boundary")
                    out_file = os.path.join(out_folder, out_name)
                    write_clk_day_boundary(df_clk_stats, out_file, day1_path, day2_path,
                                           day1_sp3_file=rcc_day1_sp3 if rcc_on==1 else None,
                                           day2_sp3_file=rcc_day2_sp3 if rcc_on==1 else None,
                                           system=selected_systems)

            q.put({"ok": True})
        except Exception:
            q.put({"ok": False, "err": traceback.format_exc()})


    # ==========================================================
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


    def _insert_or_match_row(self, day1_value, day2_value, date_str, path_day1, path_day2):
        matched_row = None

        # Var olan satırlar içinde aynı Date var mı?
        for item in self.tree.get_children():
            vals = self.tree.item(item, "values")
            row_date = vals[2]
            if row_date == date_str:
                matched_row = item
                break

        if matched_row:
            vals = list(self.tree.item(matched_row, "values"))

            if day1_value and not vals[0]:
                vals[0] = day1_value

            if day2_value and not vals[1]:
                vals[1] = day2_value

            entry = self.file_paths.get(matched_row, {"day1": None, "day2": None})
            if path_day1:
                entry["day1"] = path_day1
            if path_day2:
                entry["day2"] = path_day2
            self.file_paths[matched_row] = entry

            current_tags = list(self.tree.item(matched_row, "tags"))
            if "odd" in current_tags:
                zebra_tag = "odd"
            elif "even" in current_tags:
                zebra_tag = "even"
            else:
                zebra_tag = "even"

            for t in ("matched", "unmatched"):
                if t in current_tags:
                    current_tags.remove(t)

            if vals[0] and vals[1]:
                new_tags = (zebra_tag, "matched")
                vals[3] = "Matched"
            else:
                new_tags = (zebra_tag, "unmatched")
                vals[3] = "Imported"

            self.tree.item(matched_row, tags=new_tags)
            self.tree.item(matched_row, values=vals)

            return matched_row

        row_index = len(self.tree.get_children())
        zebra_tag = "even" if row_index % 2 == 0 else "odd"

        item = self.tree.insert(
            "",
            "end",
            values=(day1_value, day2_value, date_str, "Imported"),
            tags=(zebra_tag, "unmatched")
        )

        self.file_paths[item] = {"day1": path_day1, "day2": path_day2}
        return item

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
            self.file_paths.pop(item, None)
            self.tree.delete(item)

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
            self.tree.delete(it)
        self.file_paths.clear()

    def swap_day1_day2(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Info", "Please select at least one row to swap.")
            return

        for item in selected:
            vals = list(self.tree.item(item, "values"))
            day1_file = vals[0]
            day2_file = vals[1]

            if not day1_file and not day2_file:
                continue

            vals[0], vals[1] = day2_file, day1_file
            self.tree.item(item, values=vals)

            entry = self.file_paths.get(item, {"day1": None, "day2": None})
            entry["day1"], entry["day2"] = entry.get("day2"), entry.get("day1")
            self.file_paths[item] = entry

            tags = list(self.tree.item(item, "tags"))
            zebra = "odd" if "odd" in tags else "even"

            if vals[0] and vals[1]:
                new_tags = (zebra, "matched")
            else:
                new_tags = (zebra, "unmatched")

            self.tree.item(item, tags=new_tags)

        messagebox.showinfo("Info", "Day-N and Day-N+1 values swapped.")

    def _get_mode_for_naming(self):
        return "orbit" if self.mode == "orbit_day" else "clock"

    def run_process(self):
        items = list(self.tree.get_children())
        total_items = len(items)

        if total_items == 0:
            messagebox.showinfo("Info", "No files to process.")
            return

        self._cancel_requested = False
        self._active_proc = None
        self._active_q = None

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
                vals[3] = "Imported"
                self.tree.item(it, values=vals)

        tk.Button(btn_row, text="Kill Process", font=("Helvetica", 11),
                  padx=10, pady=6, cursor="hand2", command=_kill).pack(expand=True)
                  
        progress_win.protocol("WM_DELETE_WINDOW", lambda: None)
        progress_win.deiconify()
        progress_win.update_idletasks()

        selected_systems = self.get_selected_system_prefixes()

        def _start_one(idx: int):
            if self._cancel_requested:
                return
            if idx >= total_items:
                if progress_win.winfo_exists():
                    progress_win.destroy()
                messagebox.showinfo("Info", "Processing complete!")
                return

            item = items[idx]
            paths = self.file_paths.get(item, {})
            day1_path = paths.get("day1")
            day2_path = paths.get("day2")
            vals = list(self.tree.item(item, "values"))
            date_str = vals[2]

            status_label.config(text=f"{idx+1}/{total_items}: {date_str}")
            progress_win.update_idletasks()

            if not (day1_path and day2_path):
                pb["value"] = idx + 1
                percent_label.config(text=f"{int(((idx+1)/total_items)*100)}%")
                self.parent.after(10, lambda: _start_one(idx + 1))
                return

            payload = {
                "mode": self.mode,
                "day1_path": day1_path,
                "day2_path": day2_path,
                "date_str": date_str,
                "save_stats": int(self.save_stats_var.get()),
                "out_folder": self.output_folder_var.get().strip(),
                "selected_systems": selected_systems,

                "rcc_on": int(getattr(self, "radial_correct_check", tk.IntVar(value=0)).get()) if self.mode=="clock_day" else 0,
                "rcc_day1_sp3": (self.rcc_sp3_paths.get(item, {}) or {}).get("ref"),
                "rcc_day2_sp3": (self.rcc_sp3_paths.get(item, {}) or {}).get("tgt"),
            }

            self._active_q = mp.Queue()
            self._active_proc = mp.Process(
                target=DayBoundaryTab._dayboundary_worker,
                args=(payload, self._active_q),
                daemon=True
            )
            self._active_proc.start()

            def _poll():
                if self._cancel_requested or (not progress_win.winfo_exists()):
                    return

                if not self._active_q.empty():
                    msg = self._active_q.get()
                    ok = msg.get("ok", False)

                    vals = list(self.tree.item(item, "values"))
                    vals[3] = "Analyzed" if ok else "Error"
                    self.tree.item(item, values=vals)

                    if not ok:
                        print("Day-boundary worker error:\n", msg.get("err", ""))

                    try:
                        if self._active_proc.is_alive():
                            self._active_proc.join(timeout=0.1)
                    except Exception:
                        pass
                    self._active_proc = None

                    pb["value"] = idx + 1
                    percent_label.config(text=f"{int(((idx+1)/total_items)*100)}%")
                    progress_win.update_idletasks()

                    self.parent.after(10, lambda: _start_one(idx + 1))
                    return

                self.parent.after(100, _poll)

            _poll()

        self.parent.after(50, lambda: _start_one(0))
        
        
    # ------------------------------------------------------
    # RCC HELPERS
    # ------------------------------------------------------
    def _toggle_rcc_import_buttons(self):
        if self.mode != "clock_day":
            return

        rcc_on = (self.radial_correct_check.get() == 1)
        state = "normal" if rcc_on else "disabled"

        # RCC import buttons
        if getattr(self, "rcc_ref_sp3_btn", None) is not None:
            self.rcc_ref_sp3_btn.configure(state=state)
        if getattr(self, "rcc_tgt_sp3_btn", None) is not None:
            self.rcc_tgt_sp3_btn.configure(state=state)
            
    # ------------------------------------------------------
    # RCC IMPORT: SP3 files must be imported AFTER CLK rows exist
    # ------------------------------------------------------
    def import_rcc_day1_sp3(self):
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
                    #date_str = self._extract_date_sp3(path)
                    date_str = self._make_dayboundary_key_from_sp3(path, which="day1")
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


    def import_rcc_day2_sp3(self):
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
                    #date_str = self._extract_date_sp3(path)
                    date_str = self._make_dayboundary_key_from_sp3(path, which="day2")
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
            
    def _extract_prefix_from_filename(self, path_or_name: str) -> str:
        name = os.path.basename(path_or_name)
        # Example: IGS2R03FIN_20220010000_01D_30S_CLK.CLK -> IGS2R03FIN
        return name.split("_")[0] if "_" in name else ""


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
        
        
    def _make_dayboundary_key_from_sp3(self, path: str, which: str) -> str:
        """
        SP3 header tarihinden, TreeView'de kullanılan day-boundary anahtarını üretir.
        TreeView formatı: YYYY-MM-DD_DD  (DD = diğer günün ayın kaçıncı günü, 2 hane)

        which:
          - "day1" -> SP3 tarihi day-1 kabul edilir (d1 = dt, d2 = dt+1)
          - "day2" -> SP3 tarihi day-2 kabul edilir (d2 = dt, d1 = dt-1)
        """
        d, _, _ = read_sp3_headerline(path)
        dt = d.date()

        if which == "day1":
            d1 = dt
            d2 = dt + timedelta(days=1)
        else:  # "day2"
            d2 = dt
            d1 = dt - timedelta(days=1)

        return f"{d1.strftime('%Y-%m-%d')}_{d2.day:02d}"


