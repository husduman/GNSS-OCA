from __future__ import annotations
import tkinter as tk
from tkinter import ttk

def apply_styles(root: tk.Tk):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    # Make combobox white even readonly
    style.map("TCombobox",
              fieldbackground=[("readonly", "white"), ("!disabled", "white")],
              background=[("readonly", "white"), ("!disabled", "white")])

    style.configure("Treeview.Heading", font=("TkDefaultFont", 9, "bold"))
    style.configure("TButton", padding=(6, 4))
    style.configure("TLabelFrame", padding=(8, 6))
