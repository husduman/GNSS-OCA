import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline
from datetime import timedelta


def predict_velocity(df, k=10, dt=0.001, keep_pred_coord=False):

    df = df.copy()
    preds = []

    for sat, df_sat in df.groupby("sat"):

        df_sat = df_sat.sort_values("epoch").reset_index(drop=True)

        t0 = df_sat["epoch"].iloc[0]
        t = (df_sat["epoch"] - t0).dt.total_seconds().to_numpy()

        X = df_sat["X_ref"].to_numpy()
        Y = df_sat["Y_ref"].to_numpy()
        Z = df_sat["Z_ref"].to_numpy()

        fx = CubicSpline(t, X, extrapolate=True)
        fy = CubicSpline(t, Y, extrapolate=True)
        fz = CubicSpline(t, Z, extrapolate=True)

        t_target = t + dt

        Xp = fx(t_target)
        Yp = fy(t_target)
        Zp = fz(t_target)

        epochs = df_sat["epoch"].to_numpy()

        preds.append(
            pd.DataFrame({
                "epoch": epochs,
                "sat": sat,
                "X_pred": Xp,
                "Y_pred": Yp,
                "Z_pred": Zp
            })
        )

    df_pred = pd.concat(preds, ignore_index=True)

    # merge
    df_merged = df.merge(df_pred, on=["epoch", "sat"], how="inner")

    # velocity
    df_merged["Vx_ref"] = (df_merged["X_pred"] - df_merged["X_ref"]) / dt
    df_merged["Vy_ref"] = (df_merged["Y_pred"] - df_merged["Y_ref"]) / dt
    df_merged["Vz_ref"] = (df_merged["Z_pred"] - df_merged["Z_ref"]) / dt

    if not keep_pred_coord:
        df_merged.drop(columns=["X_pred", "Y_pred", "Z_pred"], inplace=True)

    return df_merged

