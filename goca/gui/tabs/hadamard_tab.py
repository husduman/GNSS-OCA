import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import re
import traceback
import multiprocessing as mp
import numpy as np

from goca.core.hadamard import apply_hdev_toallsat
from goca.core.hadamard_output import write_hadamard_output


# ============================================================
# Multiprocessing worker (TOP-LEVEL for Windows "spawn")
# ============================================================
def _hadamard_worker(payload: dict, q: "mp.Queue"):
    """
    Runs Hadamard analysis for a single CLK file in a subprocess.
    Writes output file inside subprocess (optional).
    Returns only small metadata via queue (status, ro, m, etc.).
    """
    try:
        # Local imports inside subprocess
        from goca.io.read_clk import read_clk
        from goca.core.clock_frequency import compute_clock_frequency
        from goca.core.clock_outliers import mad_remove_outliers
        from goca.core.hadamard import apply_hdev_toallsat
        from goca.core.hadamard_output import write_hadamard_output

        fpath = payload["fpath"]
        tau_seconds = float(payload["tau_seconds"])
        selected_prefixes = payload.get("selected_prefixes", [])
        remove_outliers = bool(payload.get("remove_outliers", True))
        mad_scale = float(payload.get("mad_scale", 5.0))

        save_output = bool(payload.get("save_output", True))
        outdir = payload.get("outdir", os.getcwd())
        
        flag_sat_missing_epoch = payload.get("flag_sat_missing_epoch", 0)
        
        def _safe_stem(s: str) -> str:
            s = os.path.splitext(os.path.basename(s))[0]
            s = re.sub(r"[^A-Za-z0-9_\-\.]+", "_", s)
            return s[:120] if len(s) > 120 else s

        # 1) read
        df = read_clk(fpath)

        # 2) sat filter
        if selected_prefixes:
            df = df[df["sat"].str[:2].isin(selected_prefixes)]

        if df.empty:
            q.put({"ok": False, "reason": "No data"})
            return

        # 3) outlier removal (optional)
        if remove_outliers:
            df = compute_clock_frequency(df)
            df = mad_remove_outliers(df, threshold=mad_scale)
            if df.empty:
                q.put({"ok": False, "reason": "All outliers"})
                return

        # 4) sampling interval ro
        epochs = df["epoch"].sort_values().unique()
        if len(epochs) < 2:
            q.put({"ok": False, "reason": "Insufficient epochs"})
            return

        ro = (epochs[1] - epochs[0]).total_seconds()

        # 5) hadamard
        df_stats = apply_hdev_toallsat(df, r=tau_seconds, ro=ro, colname="clock")
        if flag_sat_missing_epoch == 1:
            expected_epoch = int(86400 / ro)
            df_stats["flag"] = np.where(df_stats["N"] < expected_epoch, "DISCARD", "KEEP")

        # 6) save per file (optional)
        if save_output:
            os.makedirs(outdir, exist_ok=True)
            stem = _safe_stem(fpath)
            outfile = os.path.join(outdir, f"hadamard_hdev_{stem}_r{int(tau_seconds)}.out")
            write_hadamard_output(df_stats=df_stats, outfile=outfile, clk_file=fpath, tau=tau_seconds, ro=ro)

        # 7) metadata
        m = None
        try:
            m = int(tau_seconds / ro)
        except Exception:
            m = None

        q.put({"ok": True, "ro": ro, "m": m})

    except Exception:
        q.put({"ok": False, "reason": "Error", "err": traceback.format_exc()})



class HadamardTab:
    """
    Hadamard Variance Tab — LEFT PANEL + TREEVIEW
    New behavior:
      - No merging
      - No multi-r
      - No grouping
      - Each imported file is analyzed individually using the given Smooth time (single r)
    """

    def __init__(self, parent_frame):
        self.parent = parent_frame

        self.file_paths = {}
        self.chk_vars = {}

        # Output control
        self.save_hadamard_var = tk.BooleanVar(value=True)
        self.hadamard_output_var = tk.StringVar(value=os.getcwd())

        # Sampling info (last processed file)
        self.ro_str = tk.StringVar(value="N/A")
        self.unit_str = tk.StringVar(value="nanoseconds (ns)")
        self.m_str = tk.StringVar(value="N/A")

        self._build_ui()

    # -----------------------------------------------------------
    # UI
    # -----------------------------------------------------------
    def _build_ui(self):
        frame = self.parent

        # ============================
        # LEFT PANEL
        # ============================
        self.left_panel = ttk.LabelFrame(frame, text="Operations", padding=5)
        self.left_panel.configure(width=350)
        self.left_panel.pack(side="left", fill="y")
        self.left_panel.pack_propagate(False)

        # ---- Buttons Row ----
        btn_row = tk.Frame(self.left_panel)
        btn_row.pack(pady=3, padx=3, fill="x")
        inner = tk.Frame(btn_row)
        inner.pack(anchor="center")

        import_btn = ttk.Button(inner, text="Import CLK(s)", command=self.import_files)
        import_btn.pack(side="left", padx=5)

        clear_btn = ttk.Button(inner, text="Clear File(s)", command=self.clear_files)
        clear_btn.pack(side="left", padx=5)

        clear_all_btn = ttk.Button(inner, text="Clear All", command=self.clear_all_files)
        clear_all_btn.pack(side="left", padx=5)

        # ============================
        # Satellite System
        # ============================
        sat_frame = ttk.LabelFrame(self.left_panel, text="Satellite System", padding=5)
        sat_frame.pack(padx=5, pady=10, fill="x")

        col1 = tk.Frame(sat_frame)
        col1.pack(side="left", padx=10)

        col2 = tk.Frame(sat_frame)
        col2.pack(side="left", padx=10)

        for name in ["GPS", "GLONASS", "Galileo"]:
            var = tk.IntVar(value=1)
            cb = tk.Checkbutton(col1, text=name, variable=var)
            cb.pack(anchor="w", pady=2)
            self.chk_vars[name] = var

        for name in ["BeiDou", "QZSS", "IRNSS"]:
            var = tk.IntVar(value=1)
            cb = tk.Checkbutton(col2, text=name, variable=var)
            cb.pack(anchor="w", pady=2)
            self.chk_vars[name] = var

        # ============================
        # HADAMARD PARAMETERS
        # ============================
        param_frame = ttk.LabelFrame(self.left_panel, text="Hadamard Parameters", padding=5)
        param_frame.pack(padx=5, pady=10, fill="x")

        def block_typing(event):
            return "break"

        # ROW 0 — Smooth time (single r)
        tk.Label(param_frame, text="Smooth time").grid(row=0, column=0, sticky="w", pady=2)

        tk.Label(param_frame, text="Value:").grid(row=0, column=1, sticky="e", padx=(10, 2))

        self.single_value = tk.Entry(param_frame, width=10)
        self.single_value.grid(row=0, column=2, sticky="w")
        self.single_value.insert(0, "10000")

        tk.Label(param_frame, text="Unit:").grid(row=0, column=3, sticky="e", padx=(10, 2))

        self.single_unit = ttk.Combobox(
            param_frame,
            values=["seconds", "minute", "hour", "day"],
            width=7,
            state="readonly"
        )
        self.single_unit.grid(row=0, column=4, sticky="w")
        self.single_unit.current(0)
        self.single_unit.bind("<Key>", block_typing)

        # ===========================================
        # OUTLIER REMOVAL
        # ===========================================
        self.outlier_var = tk.IntVar(value=1)

        def switch_outlier():
            self.scale_value.configure(state="normal" if self.outlier_var.get() == 1 else "disabled")

        outlier_frame = tk.Frame(param_frame)
        outlier_frame.grid(row=1, column=0, columnspan=5, sticky="w", pady=(8, 2))

        chk_outlier = tk.Checkbutton(
            outlier_frame,
            text="Remove Outliers (MAD)",
            variable=self.outlier_var,
            command=switch_outlier
        )
        chk_outlier.pack(side="left")

        scale_frame = tk.Frame(param_frame)
        scale_frame.grid(row=2, column=0, columnspan=5, sticky="w", pady=(0, 2))

        tk.Label(scale_frame, text="MAD Scale:").pack(side="left", padx=(30, 2))

        self.scale_value = tk.Entry(scale_frame, width=8)
        self.scale_value.pack(side="left", ipady=2)
        self.scale_value.insert(0, "5.0")

        switch_outlier()

        # ===========================================
        # SAMPLING INFORMATION (last processed file)
        # ===========================================
        sampling_title = ttk.Label(param_frame, text="Sampling Information", font=("Arial", 10, "bold"))
        sampling_title.grid(row=3, column=0, columnspan=5, sticky="w", pady=(10, 2))

        sampling_info_frame = tk.Frame(param_frame)
        sampling_info_frame.grid(row=4, column=0, columnspan=5, sticky="w", pady=(0, 5))

        row1 = tk.Frame(sampling_info_frame)
        row1.pack(anchor="w", pady=1)
        tk.Label(row1, text="Sampling Interval (ro):", width=22, anchor="w").pack(side="left")
        tk.Label(row1, textvariable=self.ro_str, fg="gray").pack(side="left")

        row2 = tk.Frame(sampling_info_frame)
        row2.pack(anchor="w", pady=1)
        tk.Label(row2, text="Clock Unit:", width=22, anchor="w").pack(side="left")
        tk.Label(row2, textvariable=self.unit_str, fg="gray").pack(side="left")

        row3 = tk.Frame(sampling_info_frame)
        row3.pack(anchor="w", pady=1)
        tk.Label(row3, text="Hadamard Factor (m=r/ro):", width=22, anchor="w").pack(side="left")
        tk.Label(row3, textvariable=self.m_str, fg="gray").pack(side="left")

        # =========================
        # OUTPUT FRAME
        # =========================
        output_frame = ttk.LabelFrame(self.left_panel, text="Output", padding=5)
        output_frame.pack(padx=5, pady=10, fill="x")

        chk_save = tk.Checkbutton(
            output_frame,
            text="Save Hadamard Statistics",
            variable=self.save_hadamard_var,
            command=self.toggle_hadamard_output
        )
        chk_save.pack(anchor="w", pady=(2, 4))

        inner = tk.Frame(output_frame)
        inner.pack(fill="x", padx=20)

        self.entry_hadamard_out = ttk.Entry(
            inner,
            textvariable=self.hadamard_output_var,
            state="normal"
        )
        self.entry_hadamard_out.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.btn_hadamard_browse = ttk.Button(
            inner,
            text="...",
            width=3,
            command=self.browse_hadamard_output
        )
        self.btn_hadamard_browse.pack(side="left")

        self.flag_sat_missing_epoch = tk.IntVar(value=0)
        self.chk_flag_sat_missing_epoch = tk.Checkbutton(
            output_frame,  # <-- inner değil
            text="Flag satellite(s) with missing clock bias",
            variable=self.flag_sat_missing_epoch
        )
        self.chk_flag_sat_missing_epoch.pack(anchor="w", padx=20, pady=(4, 0))                              
        

        self.toggle_hadamard_output()

        # ---------------------------------------------------
        # BOTTOM RUN BUTTON
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

        # ============================
        # RIGHT SIDE (TREEVIEW)
        # ============================
        self.main_area = tk.Frame(frame)
        self.main_area.pack(side="left", fill="both", expand=True)

        columns = ("File", "Date", "Status")

        self.tree = ttk.Treeview(
            self.main_area,
            columns=columns,
            show="tree headings"
        )
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.tag_configure("odd", background="#f0f0f0")
        self.tree.tag_configure("even", background="#ffffff")
        self.tree.tag_configure("ok", foreground="black")
        self.tree.tag_configure("error", foreground="red")

        self.tree.bind("<Button-1>", self._on_tree_click)

        scrollbar = ttk.Scrollbar(self.main_area, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.heading("#0", text="")
        self.tree.column("#0", width=25, stretch=False)

        self.tree.heading("File", text="File")
        self.tree.heading("Date", text="Date")
        self.tree.heading("Status", text="Status")

        self.tree.column("File", width=220, anchor="w")
        self.tree.column("Date", width=110, anchor="center")
        self.tree.column("Status", width=100, anchor="center")

    # -----------------------------------------------------------
    # FILE OPERATIONS
    # -----------------------------------------------------------
    def import_files(self):
        filetypes = [
            ("Clock files", ("*.clk", "*.CLK", "*.CLK_05S", "*.CLK_30S")),
            ("All files", "*.*")
        ]

        files = filedialog.askopenfilenames(
            title="Select CLK Files",
            filetypes=filetypes
        )

        if not files:
            messagebox.showinfo("Info", "No files selected.")
            return

        import_win, pb = self._open_import_dialog()

        try:
            for path in files:
                fname = os.path.basename(path)
                date_str = self._extract_date_hadamard(path)

                self._insert_hadamard_row(
                    file_value=fname,
                    date_str=date_str,
                    full_path=path
                )

        except Exception as e:
            messagebox.showerror("Error", f"Unexpected error:\n{e}")

        finally:
            pb.stop()
            import_win.destroy()

    def clear_files(self):
        selected = list(self.tree.selection())
        if not selected:
            messagebox.showinfo("Info", "No file selected to remove.")
            return

        if not messagebox.askyesno("Confirm", "Are you sure you want to remove the selected file(s)?"):
            return

        for item in selected:
            try:
                self.file_paths.pop(item, None)
                self.tree.delete(item)
            except Exception as e:
                print("Delete error:", e)

    def clear_all_files(self):
        children = self.tree.get_children()
        if not children:
            messagebox.showinfo("Info", "No files to remove.")
            return

        answer = messagebox.askyesno("Confirm", "Are you sure you want to remove ALL files?")
        if not answer:
            return

        for item in children:
            self.file_paths.pop(item, None)
            self.tree.delete(item)

    def toggle_hadamard_output(self):
        state = "normal" if self.save_hadamard_var.get() else "disabled"
        self.entry_hadamard_out.configure(state=state)
        self.btn_hadamard_browse.configure(state=state)

    def browse_hadamard_output(self):
        folder = filedialog.askdirectory(title="Select output directory for Hadamard statistics")
        if folder:
            self.hadamard_output_var.set(folder)

    # --- Empty-space click removes selection ---
    def _on_tree_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region == "nothing":
            self.tree.selection_remove(*self.tree.selection())

    def _extract_date_hadamard(self, path):
        try:
            from goca.io.read_clk import read_clk_date
            return read_clk_date(path)
        except Exception:
            return "N/A"

    def _insert_hadamard_row(self, file_value, date_str, full_path):
        row_idx = len(self.tree.get_children())
        zebra_tag = "even" if row_idx % 2 == 0 else "odd"

        item = self.tree.insert(
            "",
            "end",
            values=(file_value, date_str, "Imported"),
            tags=(zebra_tag,)
        )

        self.file_paths[item] = full_path
        return item

    # -----------------------------------------------------------
    # DIALOGS
    # -----------------------------------------------------------
    def _open_import_dialog(self):
        root = self.parent.winfo_toplevel()

        win = tk.Toplevel(root)
        win.title("Please Wait...")
        win.resizable(False, False)
        win.transient(root)
        win.grab_set()

        w, h = 300, 120
        rx, ry = root.winfo_x(), root.winfo_y()
        rw, rh = root.winfo_width(), root.winfo_height()
        posx = rx + (rw // 2) - (w // 2)
        posy = ry + (rh // 2) - (h // 2)
        win.geometry(f"{w}x{h}+{posx}+{posy}")

        tk.Label(win, text="File(s) are importing...", font=("Arial", 11)).pack(pady=20)

        pb = ttk.Progressbar(win, mode="indeterminate", length=250)
        pb.pack()
        pb.start()

        win.lift()
        win.attributes("-topmost", True)
        win.update_idletasks()
        win.after(50, lambda: win.attributes("-topmost", False))

        return win, pb

    def _open_run_progress_dialog(self, total_items: int, kill_command):
        root = self.parent.winfo_toplevel()
        win = tk.Toplevel(root)
        win.withdraw()
        win.title("Processing...")
        win.resizable(False, False)
        win.transient(root)
        win.grab_set()

        w, h = 430, 230
        rx, ry = root.winfo_x(), root.winfo_y()
        rw, rh = root.winfo_width(), root.winfo_height()
        posx = rx + (rw // 2) - (w // 2)
        posy = ry + (rh // 2) - (h // 2)
        win.geometry(f"{w}x{h}+{posx}+{posy}")

        tk.Label(win, text="Processing file-by-file...", font=("Arial", 11)).pack(pady=(10, 6))

        pb = ttk.Progressbar(win, mode="determinate", length=340)
        pb.pack(pady=(0, 6))
        pb["value"] = 0
        pb["maximum"] = max(1, int(total_items))

        percent_label = tk.Label(win, text="0%", font=("Arial", 10))
        percent_label.pack()

        status_label = tk.Label(win, text="", font=("Arial", 10))
        status_label.pack(pady=(6, 2))

        # ---------------------------------------------------
        # CENTERED LARGE KILL BUTTON (same as DayBoundaryTab)
        # ---------------------------------------------------
        btn_frame = tk.Frame(win)
        btn_frame.pack(fill="both", expand=True, pady=(10, 15), padx=16)

        kill_btn = tk.Button(
            btn_frame,
            text="Kill Process",
            font=("Helvetica", 11),
            padx=10,
            pady=6,
            cursor="hand2",
            command=kill_command
        )
        kill_btn.pack(expand=True)

        win.protocol("WM_DELETE_WINDOW", lambda: None)

        win.deiconify()
        win.update_idletasks()
        return win, pb, percent_label, status_label

    # -----------------------------------------------------------
    # CORE COMPUTE
    # -----------------------------------------------------------
    def _smooth_time_seconds(self) -> float:
        """Reads Smooth time from UI and returns seconds."""
        tau = float(self.single_value.get())
        unit = self.single_unit.get()

        if unit == "minute":
            tau *= 60
        elif unit == "hour":
            tau *= 3600
        elif unit == "day":
            tau *= 86400

        return float(tau)

    def _run_hadamard_single(self, df_input, ro, tau_seconds):
        """Runs Hadamard analysis for a single file using the given tau_seconds."""
        # m = r/ro (for display)
        try:
            self.m_str.set(f"{int(tau_seconds / ro)}")
        except Exception:
            self.m_str.set("N/A")

        return apply_hdev_toallsat(
            df_input,
            r=tau_seconds,
            ro=ro,
            colname="clock"
        )

    def _safe_stem(self, s: str) -> str:
        """Make a safe file stem for output filenames."""
        s = os.path.splitext(os.path.basename(s))[0]
        s = re.sub(r"[^A-Za-z0-9_\-\.]+", "_", s)
        return s[:120] if len(s) > 120 else s

    def _save_hadamard_results_perfile(self, df_stats, source_file, ro, tau_seconds):
        outdir = self.hadamard_output_var.get()
        os.makedirs(outdir, exist_ok=True)

        stem = self._safe_stem(source_file)
        outfile = os.path.join(outdir, f"hadamard_hdev_{stem}_r{int(tau_seconds)}.out")

        write_hadamard_output(
            df_stats=df_stats,
            outfile=outfile,
            clk_file=source_file,
            tau=tau_seconds,
            ro=ro
        )

    # -----------------------------------------------------------
    # RUN
    # -----------------------------------------------------------
    def run_process(self):
        items = list(self.tree.get_children())
        if not items:
            messagebox.showinfo("Info", "No CLK files to process.")
            return

        file_list = [(it, self.file_paths[it]) for it in items if it in self.file_paths]
        if not file_list:
            messagebox.showinfo("Info", "No valid file paths found.")
            return

        total = len(file_list)

        # cancel state
        self._cancel_requested = False
        self._active_proc = None
        self._active_q = None

        # Satellite selection mapping
        mapping = {
            "GPS": "PG", "GLONASS": "PR", "Galileo": "PE",
            "BeiDou": "PC", "QZSS": "PJ", "IRNSS": "PI"
        }
        selected_prefixes = [mapping[n] for n, v in self.chk_vars.items() if v.get() == 1]

        # Tau (smooth time) once
        try:
            tau_seconds = self._smooth_time_seconds()
        except Exception as e:
            messagebox.showerror("Error", f"Invalid Smooth time:\n{e}")
            return

        # mp context (Windows-safe)
        ctx = mp.get_context("spawn" if os.name == "nt" else "fork")

        def _reset_to_initial_config():
            self.ro_str.set("N/A")
            self.m_str.set("N/A")
            for idx2, it in enumerate(self.tree.get_children()):
                vals = list(self.tree.item(it, "values"))
                if len(vals) >= 3:
                    vals[2] = "Imported"
                    zebra_tag = "even" if idx2 % 2 == 0 else "odd"
                    self.tree.item(it, values=tuple(vals), tags=(zebra_tag,))

        run_win = None

        def _kill():
            self._cancel_requested = True

            # terminate active subprocess now
            try:
                if self._active_proc is not None and self._active_proc.is_alive():
                    self._active_proc.terminate()
                    self._active_proc.join(timeout=0.2)
            except Exception:
                pass

            # close dialog
            try:
                if run_win is not None and run_win.winfo_exists():
                    run_win.destroy()
            except Exception:
                pass

            _reset_to_initial_config()

        run_win, pb, percent_label, status_label = self._open_run_progress_dialog(total_items=total, kill_command=_kill)

        def _set_progress(done: int):
            pb["value"] = done
            pct = int((done / total) * 100) if total > 0 else 0
            percent_label.config(text=f"{pct}%")
            run_win.update_idletasks()

        def _start_one(i: int):
            if self._cancel_requested:
                return

            if i >= total:
                try:
                    if run_win.winfo_exists():
                        run_win.destroy()
                except Exception:
                    pass
                messagebox.showinfo("Info", "Processing complete!")
                return

            item_id, fpath = file_list[i]
            fname = os.path.basename(fpath)
            status_label.config(text=f"Processing {i+1}/{total}: {fname}")
            run_win.update_idletasks()

            payload = {
                "fpath": fpath,
                "tau_seconds": tau_seconds,
                "selected_prefixes": selected_prefixes,
                "remove_outliers": (self.outlier_var.get() == 1),
                "mad_scale": float(self.scale_value.get() or 5.0),
                "save_output": bool(self.save_hadamard_var.get()),
                "outdir": self.hadamard_output_var.get(),
                "flag_sat_missing_epoch": self.flag_sat_missing_epoch.get(),
            }

            self._active_q = ctx.Queue()
            self._active_proc = ctx.Process(target=_hadamard_worker, args=(payload, self._active_q), daemon=True)
            self._active_proc.start()
            

            def _poll():
                if self._cancel_requested:
                    return
                if not run_win.winfo_exists():
                    return

                if not self._active_q.empty():
                    msg = self._active_q.get()
                    ok = bool(msg.get("ok", False))

                    vals = list(self.tree.item(item_id, "values"))
                    if ok:
                        vals[2] = "Analyzed"
                        self.tree.item(item_id, values=tuple(vals), tags=("ok",))

                        ro = msg.get("ro", None)
                        mval = msg.get("m", None)

                        if ro is not None:
                            try:
                                self.ro_str.set(f"{float(ro):.1f} sec")
                            except Exception:
                                self.ro_str.set("N/A")
                        else:
                            self.ro_str.set("N/A")

                        self.m_str.set(str(mval) if mval is not None else "N/A")
                    else:
                        reason = msg.get("reason", "Error")
                        vals[2] = reason
                        self.tree.item(item_id, values=tuple(vals), tags=("error",))
                        if "err" in msg:
                            print(f"[Hadamard worker error] {fname}\n{msg['err']}")

                    try:
                        if self._active_proc is not None and self._active_proc.is_alive():
                            self._active_proc.join(timeout=0.1)
                    except Exception:
                        pass
                    self._active_proc = None

                    _set_progress(i + 1)
                    self.parent.after(10, lambda: _start_one(i + 1))
                    return

                self.parent.after(100, _poll)

            _poll()

        # init
        pb["maximum"] = total
        _set_progress(0)
        self.parent.after(50, lambda: _start_one(0))
