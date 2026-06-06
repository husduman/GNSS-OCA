# goca/core/densify_sp3_epoch.py
import pandas as pd

def densify_sp3_epoch(df: pd.DataFrame, interval):
    """
    Densify SP3 epochs to a regular time grid with given interval (seconds).
    If interval is invalid/zero, returns df unchanged.
    """
    if df is None or len(df) == 0:
        return df

    # ---- normalize interval ----
    if interval is None:
        return df

    # allow interval to be str/int/float
    try:
        interval_sec = int(float(interval))
    except Exception:
        return df

    # critical guard: avoid zero/negative interval
    if interval_sec <= 0:
        return df

    dt = pd.Timedelta(seconds=interval_sec)

    out = []
    for sat, g in df.groupby("sat"):
        g = g.sort_values("epoch").copy()

        # If only 1 epoch, nothing to densify
        if g["epoch"].nunique() < 2:
            out.append(g)
            continue

        start = g["epoch"].min()
        end = g["epoch"].max()

        # Another guard: if start==end, skip
        if start == end:
            out.append(g)
            continue

        new_epochs = pd.date_range(start=start, end=end, freq=dt)

        # Reindex on epoch
        g2 = g.set_index("epoch").reindex(new_epochs)

        # Keep sat column
        g2["sat"] = sat

        # Interpolate numeric columns by time
        num_cols = g2.select_dtypes(include="number").columns
        if len(num_cols) > 0:
            g2[num_cols] = g2[num_cols].interpolate(method="time", limit_direction="both")

        g2 = g2.reset_index().rename(columns={"index": "epoch"})
        out.append(g2)

    return pd.concat(out, ignore_index=True) if out else df
