from __future__ import annotations
import numpy as np
import pandas as pd

C = 299792458.0  # m/s

def compute_hadamard_variance(df: pd.DataFrame, colname: str = "clock", ro: float = 30.0, r: float = 10200.0):
    if colname not in df.columns:
        raise KeyError(f"Column '{colname}' not found in DataFrame.")

    m = int(r / ro)
    if m <= 0:
        raise ValueError("Hadamard factor m must be >= 1 (check r and ro).")

    x = pd.to_numeric(df[colname], errors="coerce").to_numpy(dtype=float)
    x = x[np.isfinite(x)]
    N = x.size

    if N - 3 * m <= 30:
        raise ValueError(f"Insufficient data length for Hadamard variance: N-3*m={N - 3*m} <= 30.")

    v = x[3*m:] - 3.0 * x[2*m:-m] + 3.0 * x[m:-2*m] - x[:-3*m]
    hvar = np.sum(v * v) / ((6.0 * (m**2)) * (N - 3*m))
    hdev = np.sqrt(hvar)
    return hvar, hdev, m

def apply_hdev_toallsat(df: pd.DataFrame, colname: str = "clock", ro: float = 30.0, r: float = 10200.0) -> pd.DataFrame:
    rows = []
    has_outlier = "is_outlier" in df.columns

    for sat, d in df.groupby("sat", sort=True):
        N_all = len(d)
        outlier_perc = np.nan

        if has_outlier:
            d2 = d.loc[~d["is_outlier"]]
            outlier_perc = (1.0 - (len(d2) / max(1, N_all))) * 100.0
        else:
            d2 = d

        try:
            _, hdev, m = compute_hadamard_variance(d2, colname=colname, ro=ro, r=r)
            rows.append({"sat": sat, "N": N_all, "3m": 3*m, "hdev": hdev, "outlier": outlier_perc})
        except Exception:
            rows.append({"sat": sat, "N": N_all, "3m": np.nan, "hdev": np.nan, "outlier": np.nan})

    return pd.DataFrame(rows, columns=["sat", "N", "3m", "hdev", "outlier"])
