from goca.io.read_sp3 import read_sp3, read_sp3_headerline
from goca.io.read_clk import read_clk
from pathlib import Path
import numpy as np
import pandas as pd


class Availability:
    """
    Stores availability information for one SP3/CLK file.

    selected_groups : list
        Marked GNSS systems in GUI
        (["GPS","GLONASS","Galileo","BeiDou","QZSS","IRNSS"])

    mode : str
        "orbit" or "clock"
    """

    # =====================================================
    # BeiDou PRN GROUPS
    # =====================================================
    class BDS:
        _2GEO  = ["PC01","PC02","PC03","PC04","PC05"]
        _2IGSO = ["PC06","PC07","PC08","PC09","PC10","PC13","PC16"]
        _2MEO  = ["PC11","PC12","PC14"]
        _3GEO  = ["PC59","PC60","PC61","PC62"]
        _3IGSO = ["PC31","PC38","PC39","PC40","PC56"]
        _3MEO  = [
            "PC19","PC20","PC21","PC22","PC23","PC24","PC25","PC26","PC27",
            "PC28","PC29","PC30","PC32","PC33","PC34","PC35","PC36","PC37",
            "PC41","PC42","PC43","PC44","PC45","PC46","PC47","PC48","PC49",
            "PC50","PC57"
        ]

    # =====================================================
    # CONSTRUCTOR
    # =====================================================
    def __init__(self, selected_groups=None, mode="orbit"):

        self.selected_groups = selected_groups or []
        self.mode = mode                    # "orbit" / "clock"

        self.fname = None                  # input file
        self.epoch = None                  # number of epochs
        self.interval = 0
        
        # -------------------------
        # System-based availability
        # -------------------------
        self.gps = None
        self.glo = None
        self.gal = None
        self.bds2_geo = None
        self.bds2_igso = None
        self.bds2_meo = None
        self.bds3_geo = None
        self.bds3_igso = None
        self.bds3_meo = None
        self.qzss = None
        self.irnss = None

        # -------------------------
        # Satellite-based availability (NEW)
        # -------------------------
        self.sat_availability = None   # pandas DataFrame

    # =====================================================
    def clear(self):
        """Reset object but keep selected_groups & mode"""
        self.__init__(self.selected_groups, self.mode)

    # =====================================================
    # MAIN SYSTEM-BASED AVAILABILITY
    # =====================================================
    def compute_from_df(self):
        """
        Computes GNSS-system based availability
        (GPS, GAL, BDS sub-groups, etc.)
        """

        if self.fname is None:
            raise RuntimeError("fname is not set.")

        extension = Path(self.fname).suffix.lower()

        # -------------------------
        # READ FILE
        # -------------------------
        if extension in [".sp3", ".eph", ".eph_m"]:
            df = read_sp3(self.fname)
        else:
            df = read_clk(self.fname)

        self.epoch = len(df["epoch"].unique())
        epochs     = df['epoch'].sort_values().unique()
        epochs     = pd.to_datetime(epochs)
        if self.epoch >= 2:
            self.interval = (epochs[1] - epochs[0]).total_seconds()

        USE = set(self.selected_groups)

        def ratio_or_nan(count):
            if self.epoch == 0 or count == 0:
                return np.nan
            return count / self.epoch


        # -------------------------
        # GPS
        # -------------------------
        if "GPS" in USE:
            self.gps = ratio_or_nan(df["sat"].str.startswith("PG").sum())

        # -------------------------
        # GLONASS
        # -------------------------
        if "GLONASS" in USE:
            self.glo = ratio_or_nan(df["sat"].str.startswith("PR").sum())

        # -------------------------
        # GALILEO
        # -------------------------
        if "Galileo" in USE:
            self.gal = ratio_or_nan(df["sat"].str.startswith("PE").sum())

        # -------------------------
        # QZSS
        # -------------------------
        if "QZSS" in USE:
            self.qzss = ratio_or_nan(df["sat"].str.startswith("PJ").sum())

        # -------------------------
        # IRNSS
        # -------------------------
        if "IRNSS" in USE:
            self.irnss = ratio_or_nan(df["sat"].str.startswith("PI").sum())

        # -------------------------
        # BEIDOU
        # -------------------------
        if "BeiDou" in USE:
            self.bds2_geo  = ratio_or_nan(df["sat"].isin(Availability.BDS._2GEO).sum())
            self.bds2_igso = ratio_or_nan(df["sat"].isin(Availability.BDS._2IGSO).sum())
            self.bds2_meo  = ratio_or_nan(df["sat"].isin(Availability.BDS._2MEO).sum())
            self.bds3_geo  = ratio_or_nan(df["sat"].isin(Availability.BDS._3GEO).sum())
            self.bds3_igso = ratio_or_nan(df["sat"].isin(Availability.BDS._3IGSO).sum())
            self.bds3_meo  = ratio_or_nan(df["sat"].isin(Availability.BDS._3MEO).sum())

        return self

    # =====================================================
    # SATELLITE-BASED AVAILABILITY (NEW)
    # =====================================================
    def compute_satbased_avail(self):
        """
        Computes satellite-based availability (% per satellite).

        Returns
        -------
        pandas.DataFrame
            Columns:
              sat
              available_epochs
              availability_perc
        """

        if self.fname is None:
            raise RuntimeError("fname is not set.")

        ext = Path(self.fname).suffix.lower()

        # -------------------------
        # READ FILE + TOTAL EPOCHS
        # -------------------------
        if ext in [".sp3", ".eph", ".eph_m"]:
            df = read_sp3(self.fname)
            _, total_epochs, _ = read_sp3_headerline(self.fname)
        else:
            df = read_clk(self.fname)
            total_epochs = df["epoch"].nunique()

        if total_epochs == 0:
            raise RuntimeError("Total epoch count is zero.")

        # -------------------------
        # SAT-BASED COUNTS
        # -------------------------
        sat_epoch_counts = (
            df.groupby("sat")["epoch"]
              .nunique()
              .reset_index(name="available_epochs")
        )

        sat_epoch_counts["availability_perc"] = (
            sat_epoch_counts["available_epochs"] / total_epochs * 100
        )

        sat_epoch_counts = sat_epoch_counts.sort_values("sat").reset_index(drop=True)

        # store internally
        self.sat_availability = sat_epoch_counts

        return sat_epoch_counts

