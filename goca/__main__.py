#!/usr/bin/env python3
from __future__ import annotations
import tkinter as tk
from goca.gui.main_window import GOCAMain

def main():
    root = tk.Tk()
    app = GOCAMain(root)
    root.mainloop()

if __name__ == "__main__":
    main()
