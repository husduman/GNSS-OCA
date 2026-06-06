from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from goca.version import SOFTWARE, VERSION
from goca.config import GEOMETRY, ICON_PATH

from goca.gui.styles import apply_styles
from goca.gui.tabs.availability_tab import AvailabilityTab
from goca.gui.tabs.comparison_tab import ComparisonTab
from goca.gui.tabs.day_boundary_tab import DayBoundaryTab
from goca.gui.tabs.hadamard_tab import HadamardTab
from goca.gui.tabs.download_tab import DownloadTab

class NotebookTab:
    def __init__(self, notebook: ttk.Notebook, title: str):
        self.frame = ttk.Frame(notebook)
        notebook.add(self.frame, text=title)
    def widget(self):
        return self.frame

class GOCAMain:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{SOFTWARE} {VERSION}")
        self.root.geometry(GEOMETRY)


        try:
            icon = tk.PhotoImage(file=ICON_PATH)
            self.root.iconphoto(True, icon)
        except Exception:
            pass

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True)

        t1 = NotebookTab(nb, "Download Products")
        self.download_products = DownloadTab(t1.widget())

        t2 = NotebookTab(nb, "Availability (Orbit)")
        self.orbit_tab = AvailabilityTab(t2.widget(), mode="orbit")

        t3 = NotebookTab(nb, "Availability (Clock)")
        self.clock_tab = AvailabilityTab(t3.widget(), mode="clock")

        t4 = NotebookTab(nb, "Comparison (Orbit)")
        self.orbit_cmp = ComparisonTab(t4.widget(), mode="orbit_compare")

        t5 = NotebookTab(nb, "Comparison (Clock)")
        self.clock_cmp = ComparisonTab(t5.widget(), mode="clock_compare")

        t6 = NotebookTab(nb, "Day-Boundary Discontinuities (Orbit)")
        self.day_orbit = DayBoundaryTab(t6.widget(), mode="orbit_day")

        t7 = NotebookTab(nb, "Day-Boundary Discontinuities (Clock)")
        self.day_clock = DayBoundaryTab(t7.widget(), mode="clock_day")

        t8 = NotebookTab(nb, "Overlapping Hadamard Variance (Sub-daily stability)")
        self.hadamard = HadamardTab(t8.widget())
