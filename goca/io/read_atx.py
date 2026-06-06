# goca/io/read_atx.py
from __future__ import annotations
import mmap
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import pandas as pd

# ATX satellite PRN field pattern (without leading 'P'): G01, R05, E12, C19, J02, I03, Sxx
_PRN_RE = re.compile(r"^[GREJCIS]\d{2}$")

def atx2datetime(line: str):
    parts = line.strip().split()
    if len(parts) < 6:
        raise ValueError(f"Invalid datetime line: {line!r}")

    year   = int(parts[0])
    month  = int(parts[1])
    day    = int(parts[2])
    hour   = int(parts[3])
    minute = int(parts[4])
    sec    = float(parts[5])

    # Handle "0 0 0 0 0 0.0" like placeholders if ever encountered
    if year == 0 or month == 0 or day == 0:
        return None

    sec_int = int(sec)
    frac = sec - sec_int
    micro = int(round(frac * 1e6))

    if micro == 1_000_000:
        micro = 0
        sec_int += 1

    if sec_int == 60:
        sec_int = 0
        return datetime(year, month, day, hour, minute, 0) + timedelta(minutes=1)

    return datetime(year, month, day, hour, minute, sec_int, micro)


def read_atx(file_atx: str, only_satellites: bool = True,
             default_valid_until: datetime = datetime(2100, 1, 1)) -> pd.DataFrame:
    rows = []

    with open(file_atx, "r", errors="replace") as f:
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:

            inside = False
            type_line = vfrom_line = vuntil_line = None

            for raw in iter(mm.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip("\n")

                if "START OF ANTENNA" in line:
                    inside = True
                    type_line = vfrom_line = vuntil_line = None
                    continue

                if inside:
                    if "TYPE / SERIAL NO" in line:
                        type_line = line
                    elif "VALID FROM" in line:
                        vfrom_line = line
                    elif "VALID UNTIL" in line:
                        vuntil_line = line

                if inside and "END OF ANTENNA" in line:
                    inside = False

                    # Must have at least TYPE and VALID FROM for useful record
                    if not type_line or not vfrom_line:
                        continue

                    block = type_line[:20].strip()
                    prn_field = type_line[20:40].strip()   # e.g. "G01"
                    svn = type_line[40:50].strip()         # e.g. "G032"

                    # Filter: satellites only
                    if only_satellites:
                        if not _PRN_RE.match(prn_field):
                            continue

                    vfrom = atx2datetime(vfrom_line)
                    if vfrom is None:
                        continue

                    if vuntil_line:
                        vuntil = atx2datetime(vuntil_line)
                        if vuntil is None:
                            vuntil = default_valid_until
                    else:
                        vuntil = default_valid_until

                    # Output PRN convention: "PG01" etc (your existing convention)
                    prn = "P" + prn_field if prn_field else pd.NA

                    rows.append((prn, svn if svn else pd.NA, block if block else pd.NA, vfrom, vuntil))

    df = pd.DataFrame(rows, columns=["PRN", "SVN", "block", "valid_from", "valid_until"])
    df = df.sort_values(["PRN", "valid_from"], kind="mergesort").reset_index(drop=True)
    return df


def normalize_prn(sat: str) -> str:
    sat = sat.strip().upper()
    if len(sat) == 3 and _PRN_RE.match(sat):   # "G24"
        return "P" + sat                       # "PG24"
    return sat                                 # assume already "PG24"


def mask_sat_date(df: pd.DataFrame, sat: str, date: datetime) -> pd.DataFrame:
    sat = normalize_prn(sat)
    mask = (
        (df["PRN"] == sat) &
        (df["valid_from"] <= date) &
        (date < df["valid_until"])
    )
    return df.loc[mask]


def read_default_atx() -> pd.DataFrame:
    """
    Read the default ATX chosen by goca.config (latest found, unless overridden by env vars).
    """
    from goca.config import DEFAULT_ATX_FILE
    return read_atx(DEFAULT_ATX_FILE)
