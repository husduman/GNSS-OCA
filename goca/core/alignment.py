from __future__ import annotations
import numpy as np
import pandas as pd

def nev(xx, n, x, Q):
    x = np.asarray(x, dtype=float)
    Q = np.asarray(Q, dtype=float).copy()
    for i in range(n, 0, -1):
        for j in range(i):
            num = (xx - x[j]) * Q[j+1] - (xx - x[j + n + 1 - i]) * Q[j]
            den = (x[j + n + 1 - i] - x[j])
            Q[j] = num / den
    return Q[0]

def interpolate_satellite(df_sat: pd.DataFrame, df_aligned: pd.DataFrame, col: str, n_points: int = 8) -> pd.DataFrame:
    df_res = df_aligned.copy()
    valid = df_sat[col].notna()
    if valid.sum() < n_points:
        df_res[col] = np.nan
        return df_res

    t_src = df_sat.loc[valid, "epoch"].astype("int64").to_numpy() / 1e9
    v_src = df_sat.loc[valid, col].to_numpy(dtype=float)
    t_all = df_aligned["epoch"].astype("int64").to_numpy() / 1e9

    out = np.empty_like(t_all, dtype=float)
    for i, t_target in enumerate(t_all):
        idx = np.argsort(np.abs(t_src - t_target))[:n_points]
        try:
            out[i] = nev(t_target, n_points - 1, t_src[idx], v_src[idx])
        except Exception:
            out[i] = np.nan

    df_res[col] = out
    return df_res

def interpolate_clock_linear(df_sat: pd.DataFrame, df_aligned: pd.DataFrame) -> pd.DataFrame:
    df_res = df_aligned.copy()
    valid = df_sat["clock"].notna()
    if valid.sum() < 2:
        df_res["clock"] = np.nan
        return df_res

    t_src = df_sat.loc[valid, "epoch"].astype("int64").to_numpy() / 1e9
    v_src = df_sat.loc[valid, "clock"].to_numpy(dtype=float)

    order = np.argsort(t_src)
    t_src = t_src[order]
    v_src = v_src[order]

    t_all = df_aligned["epoch"].astype("int64").to_numpy() / 1e9
    v_all = np.interp(t_all, t_src, v_src)
    out_of_range = (t_all < t_src[0]) | (t_all > t_src[-1])
    v_all = v_all.astype(float)
    v_all[out_of_range] = np.nan

    df_res["clock"] = v_all
    return df_res

def align_reference_target(
    reference_df: pd.DataFrame,
    target_df: pd.DataFrame,
    sampling_option: str = "higher",
    interpolate_coordinate: bool = True,
    system=None
) -> pd.DataFrame:
    reference_df = reference_df.copy()
    target_df = target_df.copy()

    if system is None:
        selected = None
    else:
        if isinstance(system, str):
            selected = [system]
        elif isinstance(system, (list, tuple, set)):
            selected = list(system)
        else:
            raise ValueError("system must be None, str, list, tuple, or set.")
        if len(selected) == 0:
            return pd.DataFrame()

    if selected is not None:
        reference_df = reference_df[reference_df["sat"].str[:2].isin(selected)]
        target_df = target_df[target_df["sat"].str[:2].isin(selected)]

    reference_df["epoch"] = pd.to_datetime(reference_df["epoch"])
    target_df["epoch"] = pd.to_datetime(target_df["epoch"])

    common_sats = sorted(set(reference_df["sat"]) & set(target_df["sat"]))
    if not common_sats:
        return pd.DataFrame()

    is_sp3 = {"X", "Y", "Z"}.issubset(reference_df.columns)
    is_clk = "clock" in reference_df.columns

    if sampling_option == "common":
        chunks = []
        for sat in common_sats:
            ref_sat = reference_df[reference_df["sat"] == sat]
            tgt_sat = target_df[target_df["sat"] == sat]
            common_epochs = sorted(set(ref_sat["epoch"]) & set(tgt_sat["epoch"]))
            if not common_epochs:
                continue
            chunks.append(pd.merge(
                ref_sat[ref_sat["epoch"].isin(common_epochs)],
                tgt_sat[tgt_sat["epoch"].isin(common_epochs)],
                on=["epoch", "sat"],
                suffixes=("_ref", "_tgt")
            ))
        if not chunks:
            return pd.DataFrame()
        final = pd.concat(chunks, ignore_index=True)
        return final.sort_values(["sat", "epoch"]).reset_index(drop=True)

    # higher
    chunks = []
    for sat in common_sats:
        ref_sat = reference_df[reference_df["sat"] == sat].copy()
        tgt_sat = target_df[target_df["sat"] == sat].copy()

        ref_dt = ref_sat["epoch"].diff().dropna().median()
        tgt_dt = tgt_sat["epoch"].diff().dropna().median()

        common_times = np.sort(ref_sat["epoch"].unique()) if (pd.notna(ref_dt) and pd.notna(tgt_dt) and ref_dt < tgt_dt) else np.sort(tgt_sat["epoch"].unique())

        ref_al = ref_sat.set_index("epoch").reindex(common_times)
        ref_al["sat"] = sat
        ref_al = ref_al.reset_index().rename(columns={"index": "epoch"})

        tgt_al = tgt_sat.set_index("epoch").reindex(common_times)
        tgt_al["sat"] = sat
        tgt_al = tgt_al.reset_index().rename(columns={"index": "epoch"})

        if interpolate_coordinate and is_sp3:
            for col in ["X", "Y", "Z"]:
                ref_al = interpolate_satellite(ref_sat, ref_al, col)
                tgt_al = interpolate_satellite(tgt_sat, tgt_al, col)

        if is_clk:
            ref_al = interpolate_clock_linear(ref_sat, ref_al)
            tgt_al = interpolate_clock_linear(tgt_sat, tgt_al)

        chunks.append(pd.merge(ref_al, tgt_al, on=["epoch", "sat"], suffixes=("_ref", "_tgt")))

    final = pd.concat(chunks, ignore_index=True)

    if is_sp3 and is_clk:
        # unlikely
        pass
    elif is_sp3:
        keep = ["epoch","sat","X_ref","Y_ref","Z_ref","X_tgt","Y_tgt","Z_tgt"]
        final = final[keep]
    elif is_clk:
        keep = ["epoch","sat","clock_ref","clock_tgt"]
        final = final[keep]

    return final.sort_values(["sat", "epoch"]).reset_index(drop=True)
