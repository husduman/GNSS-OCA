from __future__ import annotations
import numpy as np
import pandas as pd

def mad_remove_outliers(df: pd.DataFrame, threshold: float = 3.5, max_iter: int = 50) -> pd.DataFrame:
    """Iterative MAD outlier detection on 'freq' per satellite. Adds 'is_outlier'."""
    df = df.copy()
    if "freq" not in df.columns:
        raise KeyError("freq column not found. Call compute_clock_frequency() first.")

    df["is_outlier"] = False

    for sat, idx in df.groupby("sat").groups.items():
        freq = df.loc[idx, "freq"]
        active = freq.dropna().index
        if len(active) < 3:
            continue

        out_all = set()
        for _ in range(max_iter):
            clean = freq.loc[active].dropna()
            if len(clean) < 3:
                break

            med = np.median(clean.values)
            mad = np.median(np.abs(clean.values - med))
            if mad == 0:
                break

            z = 0.6745 * (clean.values - med) / mad
            new_out = clean.index[np.abs(z) > threshold]
            if len(new_out) == 0:
                break

            out_all.update(new_out.tolist())
            active = active.difference(new_out)

        if out_all:
            df.loc[list(out_all), "is_outlier"] = True

    return df
