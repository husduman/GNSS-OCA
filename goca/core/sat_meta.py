# goca/core/sat_meta.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from goca.io.read_atx import read_default_atx, mask_sat_date, normalize_prn
from goca.io.read_sp3 import read_sp3_headerline
from goca.io.read_clk import read_clk


@lru_cache(maxsize=1)
def _get_default_atx_df():
    """
    Read default ATX only once per process.
    """
    return read_default_atx()


@lru_cache(maxsize=256)
def _epoch_from_file(full_path: str) -> Optional[datetime]:
    """
    Guess file epoch start time from file content.
    - SP3: header start epoch
    - CLK: minimum epoch in file
    """
    try:
        p = Path(full_path)
        ext = p.suffix.lower()
        # SP3 family
        if ext in [".sp3", ".eph", ".eph_m"]:
            start_dt, _, _ = read_sp3_headerline(str(p))
            return start_dt

        # Otherwise: treat as CLK (or similar with read_clk support)
        dfx = read_clk(str(p))
        t = pd.to_datetime(dfx["epoch"], errors="coerce")
        if t.notna().any():
            return t.min().to_pydatetime()

    except Exception:
        return None

    return None


@dataclass
class SatMetaResolver:
    """
    Universal helper to resolve SVN/BLOCK from ATX for a given PRN and epoch.

    - Uses default ATX (auto-latest from config) by default
    - Caches ATX read + file epoch extraction
    """
    use_default_atx: bool = True

    def __post_init__(self):
        # Load ATX dataframe once (or keep None if fails)
        self._atx_df = None
        if self.use_default_atx:
            try:
                self._atx_df = _get_default_atx_df()
            except Exception:
                self._atx_df = None

        # Optional lookup cache to speed repeated queries in same run
        self._lookup_cache: dict[tuple[str, datetime], tuple[str, str]] = {}

    def file_epoch_datetime(self, full_path: str) -> Optional[datetime]:
        """
        Public wrapper for epoch extraction (cached).
        """
        return _epoch_from_file(full_path)

    def svn_block_for(self, prn: str, epoch_dt: Optional[datetime]) -> Tuple[str, str, str]:
        """
        Returns (SVN, BLOCK) for given PRN and epoch_dt using ATX.
        If not found or any error, returns ("", "").
        """
        if self._atx_df is None or epoch_dt is None:
            return ("", "", "")

        try:
            prn_norm = normalize_prn(prn)  # accepts "G24" or "PG24"
            key = (prn_norm, epoch_dt)
            if key in self._lookup_cache:
                return self._lookup_cache[key]

            row = mask_sat_date(self._atx_df, prn_norm, epoch_dt)
            if row.empty:
                self._lookup_cache[key] = ("", "", "")
                return ("", "", "")

            r = row.iloc[0]
            #print(r)
            prn_  = "" if pd.isna(r.get("PRN")) else str(r["PRN"])
            svn   = "" if pd.isna(r.get("SVN")) else str(r["SVN"])
            block = "" if pd.isna(r.get("block")) else str(r["block"])

            self._lookup_cache[key] = (prn_, svn, block)
            return (prn_, svn, block)

        except Exception:
            return ("", "", "")


    def valid_until_for(self, prn: str, epoch_dt: Optional[datetime]) -> Optional[datetime]:
        """
        Returns valid_until datetime for given PRN and epoch_dt using ATX.
        If not found or any error, returns None.
        """
        if self._atx_df is None or epoch_dt is None:
            return None

        try:
            prn_norm = normalize_prn(prn)  # accepts "G24" or "PG24"
            row = mask_sat_date(self._atx_df, prn_norm, epoch_dt)

            if row.empty:
                return None

            r = row.iloc[0]
            vu = r.get("valid_until")

            if pd.isna(vu):
                return None

            return pd.to_datetime(vu).to_pydatetime()

        except Exception:
            return None

