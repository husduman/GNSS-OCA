from __future__ import annotations
import mmap
import re
import pandas as pd
import os
from datetime import datetime, timedelta, date

GPS_EPOCH = date(1980, 1, 6)

_AS_LINE_RE = re.compile(br"^AS\s+.*$", re.MULTILINE)

_AS_FIELDS_RE = re.compile(
    r'^AS\s+([A-Z]\d{2,3})\s+'
    r'(\d{4})\s+(\d{1,2})\s+(\d{1,2})\s+'
    r'(\d{1,2})\s+(\d{1,2})\s+(\d{1,2}\.\d+)\s+'
    r'\d+\s+([+-]?\d\.\d+[EDed][+-]\d+)'
)

def read_clk(file_clk: str) -> pd.DataFrame:
    """Return DataFrame with columns: epoch, sat, clock (seconds)."""
    try:
        with open(file_clk, "rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            matches = _AS_LINE_RE.findall(mm)
    except Exception as e:
        raise RuntimeError(f"Failed to open file '{file_clk}': {e}")

    if not matches:
        raise RuntimeError(f"CLK parse failed! 'AS' records not found in: {file_clk}")

    s = pd.Series([m.decode("ascii", errors="ignore") for m in matches])
    df = s.str.extract(_AS_FIELDS_RE)
    df.columns = ["sat", "year", "month", "day", "hour", "minute", "second", "clock"]
    df = df.dropna()
    if df.empty:
        raise RuntimeError(f"CLK parse failed! Regex matched zero rows in: {file_clk}")

    df["sat"] = "P" + df["sat"].astype(str)

    df[["year", "month", "day", "hour", "minute"]] = df[["year", "month", "day", "hour", "minute"]].astype(int)
    df["second"] = df["second"].astype(float)

    clock_str = df["clock"].astype(str).str.replace("D", "E").str.replace("d", "E")
    df["clock"] = clock_str.astype(float)

    df["epoch"] = pd.to_datetime(df[["year", "month", "day", "hour", "minute"]]) + pd.to_timedelta(df["second"], unit="s")
    return df[["epoch", "sat", "clock"]]

def read_clk_first_epoch(file_clk: str):
    """Fast helper: return first epoch as python datetime, or None."""
    try:
        with open(file_clk, "rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            m = _AS_LINE_RE.search(mm)
            if not m:
                return None
            line = m.group(0).decode("ascii", errors="ignore")
    except Exception:
        return None

    parts = line.split()
    if len(parts) < 8:
        return None

    try:
        y, mo, d = int(parts[2]), int(parts[3]), int(parts[4])
        hh, mi = int(parts[5]), int(parts[6])
        sec = float(parts[7])
        base = pd.Timestamp(year=y, month=mo, day=d, hour=hh, minute=mi)
        return (base + pd.to_timedelta(sec, unit="s")).to_pydatetime()
    except Exception:
        return None
    

def read_clk_date(fname: str) -> str:
    """
    1) COD0R03FIN_20020620000_01D_30S_CLK.CLK.gz
       -> YYYY=2002, DOY=062

    2) cod11560.clk.Z
       -> GPS week=1156, DOW=0
    """

    name = os.path.basename(fname)

    # -------------------------------------------------
    # FORMAT 1 → YYYY + DOY
    # -------------------------------------------------
    m1 = re.search(r'(\d{4})(\d{3})\d*', name)
    if m1:
        year = int(m1.group(1))
        doy = int(m1.group(2))

        if 1 <= doy <= 366:
            dt = datetime(year, 1, 1) + timedelta(days=doy - 1)
            return dt.strftime("%Y-%m-%d")

    # -------------------------------------------------
    # FORMAT 2 → GPS week + DOW
    # -------------------------------------------------
    m2 = re.search(r'(\d{4})(\d)\.clk', name, re.IGNORECASE)
    if m2:
        week = int(m2.group(1))
        dow = int(m2.group(2))

        if not (0 <= dow <= 6):
            raise ValueError(f"Invalid GPS day-of-week: {dow}")

        dt = GPS_EPOCH + timedelta(days=week * 7 + dow)
        return dt.strftime("%Y-%m-%d")

    raise ValueError(f"Unrecognized CLK filename format: '{name}'")
