from __future__ import annotations
import pandas as pd

def compute_clock_frequency(df: pd.DataFrame) -> pd.DataFrame:
    """Per-satellite freq = diff(clock)/diff(t) into column 'freq'."""
    df = df.copy()
    df["epoch"] = pd.to_datetime(df["epoch"], errors="coerce")
    df = df.sort_values(["sat", "epoch"]).reset_index(drop=True)

    dt = df.groupby("sat")["epoch"].diff().dt.total_seconds()
    dclk = df.groupby("sat")["clock"].diff()
    df["freq"] = dclk / dt
    return df
