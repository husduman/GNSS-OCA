import os
import datetime
import numpy as np
import tkinter as tk
import pandas as pd
import inspect
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from goca.io.read_sp3 import read_sp3, read_sp3_headerline
from goca.io.read_clk import read_clk, read_clk_first_epoch, read_clk_date
from goca.core.availability import Availability
from goca.io.read_atx import read_default_atx, mask_sat_date
from goca.config import DEFAULT_ATX_FILE
from goca.core.sat_meta import SatMetaResolver
from goca.core.bds_classification import classify_bds_by_block
from goca.version import SOFTWARE, VERSION

class AvailabilityTab:
    """
    Reusable availability panel used for both Orbit (sp3) and Clock (clk).
    mode: "orbit" or "clock"
    """
    def __init__(self, parent_frame, mode="orbit"):
        self.mode = mode  # "orbit" or "clock"
        self.parent = parent_frame

        # Data containers
        self.avail_data = {}       # full_path -> Availability instance
        self.tree_file_paths = {}  # tree item id -> full_path

        # Map used to display child labels -> Availability attrs
        self.sat_attr_map = {
            "GPS": "gps",
            "GLONASS": "glo",
            "Galileo": "gal",
            "BeiDou-2 GEO": "bds2_geo",
            "BeiDou-2 IGSO": "bds2_igso",
            "BeiDou-2 MEO": "bds2_meo",
            "BeiDou-3 GEO": "bds3_geo",
            "BeiDou-3 IGSO": "bds3_igso",
            "BeiDou-3 MEO": "bds3_meo",
            "QZSS": "qzss",
            "IRNSS": "irnss",
        }

        # Satellite checkboxes state (shared UI placed inside this tab)
        self.chk_vars = {}
        self.output_path_var = tk.StringVar()

        # Build UI
        self._build_ui()
        
        # ---- GNSS selection list ----
        self.selected_groups = [name for name, var in self.chk_vars.items() if var.get() == 1]

    # ---------------------------
    # UI BUILD
    # ---------------------------
    def _build_ui(self):
        frame = self.parent

        # LEFT PANEL
        self.left_panel = ttk.LabelFrame(frame, text="Operations", padding=5)
        self.left_panel.configure(width=350)
        self.left_panel.pack(side="left", fill="y")
        self.left_panel.pack_propagate(False)

        # Buttons row
        btn_row = tk.Frame(self.left_panel)
        btn_row.pack(pady=3, padx=3, fill="x")
        inner = tk.Frame(btn_row)
        inner.pack(anchor="center")

        if self.mode == "clock":
            import_label = "Import CLK(s)"
        elif self.mode == "orbit":
            import_label = "Import SP3(s)"

        import_btn = ttk.Button(inner, text=import_label, command=self.import_file)
        import_btn.pack(side="left", padx=5)

        clear_btn = ttk.Button(inner, text="Clear File(s)", command=self.clear_files)
        clear_btn.pack(side="left", padx=5)

        clear_all_btn = ttk.Button(inner, text="Clear All", command=self.clear_all_files)
        clear_all_btn.pack(side="left", padx=5)

        # Satellite System Group
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
            var.trace_add("write", self.update_satellite_selection)

        for name in ["BeiDou", "QZSS", "IRNSS"]:
            var = tk.IntVar(value=1)
            cb = tk.Checkbutton(col2, text=name, variable=var)
            cb.pack(anchor="w", pady=2)
            self.chk_vars[name] = var
            var.trace_add("write", self.update_satellite_selection)

        # ---------------------------------------
        # OUTPUT FRAME (NEW STYLE)
        # ---------------------------------------
        output_frame = ttk.LabelFrame(self.left_panel, text="Output", padding=5)
        output_frame.pack(padx=5, pady=10, fill="x")

        # Save results checkbox
        self.save_results_var = tk.IntVar(value=1)
        chk_save = tk.Checkbutton(
            output_frame,
            text="Save Availability Results",
            variable=self.save_results_var,
            command=self._toggle_output_state
        )
        chk_save.pack(anchor="w", pady=(2, 0))

        # Indent sub-frame
        inner = tk.Frame(output_frame)
        inner.pack(fill="x", padx=20, pady=5)

        path_frame = tk.Frame(inner)
        path_frame.pack(fill="x")

        self.output_folder_var = tk.StringVar()
        self.output_folder_var.set(os.getcwd())

        self.output_entry = ttk.Entry(path_frame, textvariable=self.output_folder_var)
        self.output_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.output_browse = ttk.Button(
            path_frame,
            text="...",
            width=3,
            command=self.select_output_folder
        )
        self.output_browse.pack(side="left")


        # RUN + RESET aynı satırda
        btn_bottom = tk.Frame(self.left_panel)
        btn_bottom.pack(side="bottom", padx=5, pady=5, fill="x")

        reset_button = tk.Button(
            btn_bottom,
            text="Reset",
            font=("Helvetica", 12, "bold"),
            #bg="#d9534f", fg="white",
            padx=5, pady=10,
            cursor="hand2",
            command=self.reset_all_values
        )
        reset_button.pack(side="left", expand=True, fill="x", padx=(0, 3))

        run_button = tk.Button(
            btn_bottom,
            text="RUN",
            font=("Helvetica", 12, "bold"),
            #bg="#5cb85c", fg="white",
            padx=5, pady=10,
            cursor="hand2",
            command=self.run_process
        )
        run_button.pack(side="left", expand=True, fill="x", padx=(3, 0))

        # MAIN AREA (tree)
        self.main_area = tk.Frame(self.parent)
        self.main_area.pack(side="left", fill="both", expand=True)

        style = ttk.Style()
        style.configure("Custom.Treeview", rowheight=25, borderwidth=1)
        style.configure("Custom.Treeview.Heading", font=("Arial", 10, "bold"))

        columns = ("File", "Date", "Interval", "Number of Epoch", "Status")
        self.tree = ttk.Treeview(self.main_area, columns=columns, show="tree headings")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Button-1>", self.on_tree_click)
        self.tree.bind("<<TreeviewOpen>>", self.on_tree_open)

        scrollbar = ttk.Scrollbar(self.main_area, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.heading("#0", text="")
        self.tree.column("#0", width=30)

        for col in columns:
            self.tree.heading(col, text=col, command=lambda _col=col: self.treeview_sort_column(self.tree, _col, False))
            if col == "File":
                self.tree.column(col, width=200)
            elif col == "Date":
                self.tree.column(col, width=120, anchor="center")
            else:
                self.tree.column(col, width=100, anchor="center")

        self.tree.tag_configure('odd',  background="#f0f0f0")
        self.tree.tag_configure('even', background="#ffffff")

    
    
    
    
    def _toggle_output_state(self):
        state = "normal" if self.save_results_var.get() == 1 else "disabled"
        self.output_entry.configure(state=state)
        self.output_browse.configure(state=state)


    def select_output_folder(self):
        folder = filedialog.askdirectory(
            title="Select Output Folder",
            initialdir=os.getcwd()
        )
        if folder:
            self.output_folder_var.set(folder)


    # ---------------------------
    # File selection / output
    # ---------------------------
    def select_output_file(self):
        default_name = "GOCC_STATS.json"
        file_path = filedialog.asksaveasfilename(
            title="Choose output JSON file",
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            initialfile=default_name
        )
        if file_path:
            self.output_path_var.set(file_path)

    # ---------------------------
    # Import files
    # ---------------------------
    def import_file(self):

        # ----------------------------------------------------
        if self.mode == "orbit":
            filetypes = [
                ("Orbit files", ("*.sp3", "*.SP3", "*.eph", "*.EPH", "*.EPH_M")),
                ("All files", "*.*")
            ]
            filenames = filedialog.askopenfilenames(
                title="Select Orbit Files", filetypes=filetypes
            )
        else:
            filetypes = [
                ("Clock files", ("*.clk", "*.CLK", "*.CLK_05S", "*.CLK_30S")),
                ("All files", "*.*")
            ]
            filenames = filedialog.askopenfilenames(
                title="Select Clock Files", filetypes=filetypes
            )

        if not filenames:
            return

        # ----------------------------------------------------
        import_win = tk.Toplevel(self.parent)
        import_win.title("Please wait...")
        import_win.resizable(False, False)
        import_win.transient(self.parent)
        import_win.grab_set()

        w, h = 300, 120
        root = self.parent.winfo_toplevel()
        rx, ry = root.winfo_x(), root.winfo_y()
        rw, rh = root.winfo_width(), root.winfo_height()
        posx = rx + (rw // 2) - (w // 2)
        posy = ry + (rh // 2) - (h // 2)
        import_win.geometry(f"{w}x{h}+{posx}+{posy}")

        tk.Label(import_win, text="File(s) are importing...", font=("Arial", 11)).pack(pady=20)
        pb_import = ttk.Progressbar(import_win, mode="indeterminate", length=250)
        pb_import.pack()
        pb_import.start()
        import_win.update_idletasks()

        # ----------------------------------------------------
        try:
            row_count = len(self.tree.get_children())
            existing_files = [self.tree.set(child, "File") for child in self.tree.get_children()]

            for i, file_path in enumerate(filenames):
                file_name = os.path.basename(file_path)

                if file_name in existing_files:
                    continue

                tag = 'even' if (row_count + i) % 2 == 0 else 'odd'

                if self.mode == "orbit":
                    try:
                        dateofsp3, num_epochs, epoch_interval = read_sp3_headerline(file_path)
                        date_str = dateofsp3.strftime("%Y-%m-%d")
                    except:
                        date_str = ""
                        num_epochs = ""
                        epoch_interval = ""
                else:
                    try:
                        date_str = read_clk_date(file_path)
                        num_epochs = "NaN"
                        epoch_interval = "NaN"
                    except:
                        num_epochs = ""
                        epoch_interval = ""
                        date_str = ""

                parent = self.tree.insert(
                    "", "end", values=(file_name, date_str, epoch_interval, num_epochs, "Imported"),
                    tags=(tag,)
                )

                self.tree_file_paths[parent] = file_path

                selected_gnss = [name for name, var in self.chk_vars.items() if var.get() == 1]
                satellites = {
                    "GPS": ["GPS"],
                    "GLONASS": ["GLONASS"],
                    "Galileo": ["Galileo"],
                    "BeiDou": [
                        "BeiDou-2 GEO","BeiDou-2 IGSO","BeiDou-2 MEO",
                        "BeiDou-3 GEO","BeiDou-3 IGSO","BeiDou-3 MEO"
                    ],
                    "QZSS": ["QZSS"],
                    "IRNSS": ["IRNSS"]
                }

                for sat in selected_gnss:
                    for sub in satellites.get(sat, []):
                        self.tree.insert(parent, "end", values=(sub, ""), tags=(tag,))

        finally:
            pb_import.stop()
            import_win.destroy()

    
    def _reset_to_initial_config_silent(self):
        self.avail_data.clear()

        for parent in self.tree.get_children():
            self.tree.set(parent, "Status", "Imported")
            self.tree.set(parent, "Number of Epoch", "")
            self.tree.set(parent, "Interval", "")

            for child in self.tree.get_children(parent):
                # child değer sütununu temizle
                self.tree.set(child, "Date", "")
                
    def run_process(self):
        parents = self.tree.get_children()
        total_files = len(parents)
        if total_files == 0:
            messagebox.showinfo("Info", "No files to process.")
            return

        self._cancel_requested = False

        progress_win = tk.Toplevel(self.parent)
        progress_win.withdraw()
        progress_win.title("Processing...")
        progress_win.resizable(False, False)
        progress_win.transient(self.parent)
        progress_win.grab_set()
        progress_win.focus_set()

        w, h = 430, 230
        root = self.parent.winfo_toplevel()
        rx, ry = root.winfo_x(), root.winfo_y()
        rw, rh = root.winfo_width(), root.winfo_height()
        posx = rx + (rw // 2) - (w // 2)
        posy = ry + (rh // 2) - (h // 2)
        progress_win.geometry(f"{w}x{h}+{posx}+{posy}")

        ttk.Label(progress_win, text="Processing, please wait...", font=("Arial", 11)).pack(pady=(10, 6))

        pb = ttk.Progressbar(progress_win, mode="determinate", length=340)
        pb.pack(pady=(0, 6))
        pb["value"] = 0
        pb["maximum"] = total_files

        percent_label = ttk.Label(progress_win, text="0%")
        percent_label.pack(pady=(0, 4))

        status_label = ttk.Label(progress_win, text="", font=("Arial", 10))
        status_label.pack(pady=(4, 2))

        def _kill():
            self._cancel_requested = True

            try:
                if progress_win.winfo_exists():
                    progress_win.destroy()
            except Exception:
                pass

            try:
                self._reset_to_initial_config_silent()
            except Exception:
                pass

        btn_frame = tk.Frame(progress_win)
        btn_frame.pack(fill="both", expand=True, padx=16, pady=(10, 15))

        kill_btn = tk.Button(
            btn_frame,
            text="Kill Process",
            font=("Helvetica", 11),
            padx=10,
            pady=6,
            cursor="hand2",
            command=_kill
        )
        kill_btn.pack(expand=True)

        progress_win.protocol("WM_DELETE_WINDOW", lambda: None)
        progress_win.deiconify()
        progress_win.update_idletasks()

        def process_file(idx=0):
            if self._cancel_requested:
                return
            if not pb.winfo_exists():
                return

            if idx >= total_files:
                for parent in parents:
                    self.fill_child_values(parent)

                if self.save_results_var.get() == 1:
                    folder = self.output_folder_var.get().strip()
                    if folder:
                        filename = f"availability_{self.mode}.out"
                        try:
                            self.write_availability(folder, filename)
                        except Exception as e:
                            print("Saving error:", e)
                            messagebox.showerror("Error", str(e))

                if progress_win.winfo_exists():
                    progress_win.destroy()
                messagebox.showinfo("Info", "Processing complete!")
                return

            parent = parents[idx]
            file_path = self.tree_file_paths.get(parent)

            status_label.config(text=f"{idx+1}/{total_files}: {os.path.basename(file_path) if file_path else ''}")
            progress_win.update_idletasks()

            if file_path:
                try:
                    selected_sat_groups = [name for name, var in self.chk_vars.items() if var.get() == 1]
                    avail_obj = Availability(selected_sat_groups)

                    avail_obj.fname = file_path

                    if self.mode == "orbit":
                        df_sp3 = read_sp3(file_path)
                        
                        if "epoch" in df_sp3.columns:
                            df_sp3["epoch"] = pd.to_datetime(df_sp3["epoch"], errors="coerce")

                        if "epoch" not in df_sp3.columns or df_sp3["epoch"].isna().any():
                            raise ValueError("SP3 'epoch' conversion failed (epoch contains non-datetime values).")

                        sig = inspect.signature(avail_obj.compute_from_df)
                        if len(sig.parameters) >= 2:
                            avail_obj = avail_obj.compute_from_df(df_sp3)
                        else:
                            setattr(avail_obj, "df", df_sp3)
                            avail_obj = avail_obj.compute_from_df()

                    else:
                        avail_obj = avail_obj.compute_from_df()

                    self.avail_data[file_path] = avail_obj

                    self.fill_child_values(parent)
                    self.tree.set(parent, "Status", "Analyzed")
                    self.tree.set(parent, "Number of Epoch", "{}".format(avail_obj.epoch))
                    self.tree.set(parent, "Interval", "{}".format(avail_obj.interval))

                except Exception as e:
                    print(f"Error processing {file_path}: {e}")
                    self.tree.set(parent, "Status", "Error")

            #pb["value"] = idx + 1
            #percent = int(((idx + 1) / total_files) * 100)
            #percent_label.config(text=f"{percent}%")
            
            save_will_run = (
                self.save_results_var.get() == 1
            )

            pb["value"] = idx + 1
            percent = int(((idx + 1) / total_files) * 100)

            if percent == 100 and save_will_run:
                percent_label.config(
                    text="Comparison process is completed.\n"
                         "Statistics are writing to file(s).\n" 
                         "Please wait..."
                )
            else:
                percent_label.config(text=f"{percent}%")
            progress_win.update_idletasks()

            self.parent.after(50, lambda: process_file(idx + 1))

        self.parent.after(100, lambda: process_file(0))

    
    def fill_child_values(self, parent_id):
        import numpy as _np

        full_path = self.tree_file_paths.get(parent_id)
        if not full_path:
            return

        avail_obj = self.avail_data.get(full_path)
        if not avail_obj:
            return

        selected_groups = {name for name, var in self.chk_vars.items() if var.get() == 1}

        for child in self.tree.get_children(parent_id):
            sat_label = self.tree.set(child, "File").strip()
            attr_name = self.sat_attr_map.get(sat_label)
            if not attr_name:
                self.tree.set(child, "Date", "")
                continue

            if sat_label.startswith("BeiDou"):
                group = "BeiDou"
            else:
                group = sat_label

            if group not in selected_groups:
                self.tree.set(child, "Date", "")
                continue

            try:
                value = getattr(avail_obj, attr_name, None)
            except Exception:
                value = None

            is_nan = False
            if value is None:
                is_nan = True
            else:
                try:
                    is_nan = bool(_np.isnan(value))
                except Exception:
                    is_nan = False

            disp = ""
            if not is_nan:
                try:
                    disp = f"{float(value):.2f}"
                except Exception:
                    disp = str(value)

            self.tree.set(child, "Date", disp)

    # ---------------------------
    # Checkbox change handling
    # ---------------------------
    def update_satellite_selection(self, *args):

        self.selected_groups = [name for name, var in self.chk_vars.items() if var.get() == 1]
        
        satellites = {
            "GPS": ["GPS"],
            "GLONASS": ["GLONASS"],
            "Galileo": ["Galileo"],
            "BeiDou": [
                "BeiDou-2 GEO", "BeiDou-2 IGSO", "BeiDou-2 MEO",
                "BeiDou-3 GEO", "BeiDou-3 IGSO", "BeiDou-3 MEO"
            ],
            "QZSS": ["QZSS"],
            "IRNSS": ["IRNSS"]
        }

        for parent in self.tree.get_children():

            for child in self.tree.get_children(parent):
                self.tree.delete(child)

            parent_tags = self.tree.item(parent, "tags")
            tag = parent_tags[0] if parent_tags else ""

            for sat in self.selected_groups:
                for sub in satellites.get(sat, []):
                    self.tree.insert(parent, "end", text="", values=(sub, ""), tags=(tag,))

            self.fill_child_values(parent)

    def on_tree_open(self, event):
        item = self.tree.focus()
        if item and self.tree.parent(item) == "":
            self.fill_child_values(item)

    def on_tree_click(self, event):
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            self.tree.selection_remove(self.tree.selection())

    def treeview_sort_column(self, tv, col, reverse):
        data_list = [(tv.set(k, col), k) for k in tv.get_children('')]
        try:
            data_list.sort(key=lambda t: float(t[0]), reverse=reverse)
        except Exception:
            data_list.sort(key=lambda t: t[0], reverse=reverse)
        for index, (val, k) in enumerate(data_list):
            tv.move(k, '', index)
        tv.heading(col, command=lambda: self.treeview_sort_column(tv, col, not reverse))

    def reset_all_values(self):
        """Reset all computed availability results but keep imported files."""
        
        self.avail_data.clear()

        for parent in self.tree.get_children():

            self.tree.set(parent, "Status", "Imported")

            for child in self.tree.get_children(parent):

                self.tree.set(child, "Date", "")
                self.tree.set(child, "File", self.tree.set(child, "File"))
                self.tree.set(child, "Date", "NaN")

        messagebox.showinfo("Info", "All computed availability values have been reset.")

    def clear_all_files(self):
        children = self.tree.get_children()
        if not children:
            messagebox.showinfo("Info", "No files to remove.")
            return
        answer = messagebox.askyesno("Confirm", "Are you sure you want to remove ALL files?")
        if not answer:
            return
        for item in children:
            full_path = self.tree_file_paths.pop(item, None)
            if full_path and full_path in self.avail_data:
                self.avail_data.pop(full_path, None)
            self.tree.delete(item)

    def clear_files(self):
        selected = list(self.tree.selection())
        if not selected:
            messagebox.showinfo("Info", "No file selected to remove.")
            return
        if not messagebox.askyesno("Confirm", "Are you sure you want to remove the selected file(s)?"):
            return

        items_to_delete = []
        for it in selected:
            parent = self.tree.parent(it)
            if parent:
                items_to_delete.append(parent)
            else:
                items_to_delete.append(it)

        items_to_delete = list(dict.fromkeys(items_to_delete))
        top_level = list(self.tree.get_children(""))

        def _key(it):
            try:
                return top_level.index(it)
            except ValueError:
                return -1

        items_to_delete.sort(key=_key, reverse=True)

        for it in items_to_delete:
            try:
                full_path = self.tree_file_paths.pop(it, None)
                if full_path and full_path in self.avail_data:
                    self.avail_data.pop(full_path, None)
                self.tree.delete(it)
            except Exception as e:
                print("Delete error:", e)

    def write_availability(self, folder_path, filename):
    
        satmeta = SatMetaResolver()

        folder = Path(folder_path)
        folder.mkdir(parents=True, exist_ok=True)
        out_file = folder / filename

        mode_str = "Availability (orbit)" if self.mode == "orbit" else "Availability (clock)"
        selected = set(self.selected_groups)

        all_fields = [
            ("gps",      "---G", "GPS"),
            ("glo",      "---R", "GLONASS"),
            ("gal",      "---E", "Galileo"),
            ("bds2_geo", "-C2G", "BeiDou"),
            ("bds2_igso","-C2I", "BeiDou"),
            ("bds2_meo", "-C2M", "BeiDou"),
            ("bds3_geo", "-C3G", "BeiDou"),
            ("bds3_igso","-C3I", "BeiDou"),
            ("bds3_meo", "-C3M", "BeiDou"),
            ("qzss",     "---Q", "QZSS"),
            ("irnss",    "---I", "IRNSS"),
        ]

        fields = [(attr, col) for (attr, col, sys) in all_fields if sys in selected]
        
        lines = []
        lines.append(f"# {mode_str}")
        lines.append(f"# Created  : {datetime.datetime.utcnow():%Y-%m-%dT%H:%M:%S UTC}")
        lines.append(f"# ATX File : {DEFAULT_ATX_FILE}")
        lines.append("#")

        header = "# File--------------------------------"
        for _, col in fields:
            header += f"{col:>6}  "
        lines.append(header.rstrip())

        for full_path, obj in self.avail_data.items():

            fname = Path(full_path).name
            row = f"{fname:<38}"

            for attr, _col in fields:
                val = getattr(obj, attr, None)
                if val is None or (isinstance(val, float) and np.isnan(val)):
                    cell = "NaN"
                else:
                    cell = f"{val:.1f}"
                row += f"{cell:>6}  "

            lines.append(row.rstrip())

            epoch_dt = satmeta.file_epoch_datetime(full_path)
            try:
                df_sat = obj.compute_satbased_avail()
            except Exception:
                df_sat = None

            if df_sat is not None and not df_sat.empty:

                selected = set(self.selected_groups)

                lines.append("# PRN       SVN     BLOCK            Percentage")

                #BDS_2GEO  = Availability.BDS._2GEO
                #BDS_2IGSO = Availability.BDS._2IGSO
                #BDS_2MEO  = Availability.BDS._2MEO
                #BDS_3GEO  = Availability.BDS._3GEO
                #BDS_3IGSO = Availability.BDS._3IGSO
                #BDS_3MEO  = Availability.BDS._3MEO
                
                BDS_2GEO, BDS_2IGSO, BDS_2MEO, \
                BDS_3GEO, BDS_3IGSO, BDS_3MEO = classify_bds_by_block(
                    df_sat,
                    full_path
                )


                systems = df_sat["sat"].str[:2].unique()

                for sys in systems:

                    if sys != "PC":

                        sys_label = {
                            "PG": "GPS",
                            "PR": "GLONASS",
                            "PE": "Galileo",
                            "PJ": "QZSS",
                            "PI": "IRNSS"
                        }.get(sys, None)

                        if sys_label not in selected:
                            continue

                        grp_df = df_sat[df_sat["sat"].str.startswith(sys)]
                        if grp_df.empty:
                            continue

                        lines.append(f"+{sys_label}")

                        for _, r in grp_df.sort_values("sat").iterrows():
                            prn = r["sat"]
                            prn, svn, block = satmeta.svn_block_for(prn, epoch_dt)
                            lines.append(
                                " {:4s} {:>9s}     {:<16s} {:>10.2f}".format(
                                    prn, svn, block[:16], r["availability_perc"]
                                )
                            )

                        lines.append(f"-{sys_label}")
                        lines.append("")

                    else:
                        if "BeiDou" not in selected:
                            continue

                        tmp_df = df_sat[df_sat["sat"].str.startswith("PC")]
                        if tmp_df.empty:
                            continue

                        bds_groups = [
                            ("BDS_2GEO",  BDS_2GEO),
                            ("BDS_2IGSO", BDS_2IGSO),
                            ("BDS_2MEO",  BDS_2MEO),
                            ("BDS_3GEO",  BDS_3GEO),
                            ("BDS_3IGSO", BDS_3IGSO),
                            ("BDS_3MEO",  BDS_3MEO),
                        ]

                        for label, sat_list in bds_groups:

                            grp_df = tmp_df[tmp_df["sat"].isin(sat_list)]
                            if grp_df.empty:
                                continue

                            lines.append(f"+{label}")

                            for _, r in grp_df.sort_values("sat").iterrows():
                                prn, svn, block = satmeta.svn_block_for(r["sat"], epoch_dt)
                                lines.append(
                                    " {:4s} {:>9s}     {:<16s} {:>10.2f}".format(
                                        prn, svn, block[:16], r["availability_perc"]
                                    )
                                )
                            lines.append(f"-{label}")
                            lines.append("")

        lines.append("# EOF")

        with open(out_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return out_file

