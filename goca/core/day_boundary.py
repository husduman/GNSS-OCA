import pandas as pd
import numpy as np
from pathlib import Path
from datetime import timedelta

from goca.io.read_sp3 import read_sp3, read_sp3_headerline
from goca.core.alignment import align_reference_target
from goca.core.predict_velocity import predict_velocity
from goca.core.rac import compute_rac

from goca.io.read_clk import read_clk
from goca.core.statistics import compute_clock_stats

from goca.io.read_atx import read_default_atx, mask_sat_date
from goca.config import DEFAULT_ATX_FILE
from goca.core.sat_meta import SatMetaResolver
from goca.core.bds_classification import classify_bds_by_block

C = 299792458.0

def compute_day_boundary_sp3(
        sp3_prev: str,
        sp3_next: str,
        sampling_option: str = "common",
        velocity_k: int = 10,
        velocity_dt: float = 0.001
    ) -> pd.DataFrame:
    """
    Compute RAC corrections across a day boundary using two consecutive SP3 files.

    Parameters
    ----------
    sp3_prev : str
        SP3 file for day N.
    sp3_next : str
        SP3 file for day N+1.
    sampling_option : str
        'common' or 'higher'. Default 'common'.
    velocity_k : int
        Number of neighbors for cubic interpolation (predict_velocity).
    velocity_dt : float
        Time shift (sec) used for velocity estimation.

    Returns
    -------
    pd.DataFrame
        DataFrame containing RAC values (radial, along, cross).

    Raises
    ------
    ValueError
        If the two SP3 files are not consecutive days.
    """

    # ----------------------------------------------------------------------
    # 0) CHECK DAY SEQUENCE USING SP3 HEADER
    # ----------------------------------------------------------------------
    dt_prev, _, _ = read_sp3_headerline(sp3_prev)
    dt_next, _, _ = read_sp3_headerline(sp3_next)

    if (dt_next.date() - dt_prev.date()).days != 1:
        raise ValueError(
            f"SP3 files are not consecutive days:\n"
            f"  prev: {dt_prev.date()}   next: {dt_next.date()}"
        )

    # ----------------------------------------------------------------------
    # 1) READ PREVIOUS DAY SP3
    # ----------------------------------------------------------------------
    df_prev = read_sp3(sp3_prev)
    df_prev["epoch"] = pd.to_datetime(df_prev["epoch"])
    df_prev = df_prev.rename(columns={"X": "X_ref", "Y": "Y_ref", "Z": "Z_ref"})

    # last 2 hours of previous day
    t_end = df_prev["epoch"].max()
    t_start = t_end - pd.Timedelta(hours=2)
    df_prev_last2h = df_prev[(df_prev["epoch"] >= t_start) & (df_prev["epoch"] <= t_end)].copy()

    # ----------------------------------------------------------------------
    # 2) VELOCITY PREDICTION
    # ----------------------------------------------------------------------
    df_vel = predict_velocity(
        df_prev_last2h,
        k=velocity_k,
        dt=velocity_dt,
        keep_pred_coord=False
    )

    df_vel = df_vel.rename(columns={"X_ref": "X", "Y_ref": "Y", "Z_ref": "Z"})

    # ----------------------------------------------------------------------
    # 3) READ NEXT DAY SP3
    # ----------------------------------------------------------------------
    df_next = read_sp3(sp3_next)
    df_next["epoch"] = pd.to_datetime(df_next["epoch"])

    # ----------------------------------------------------------------------
    # 4) ALIGN FILES ACROSS THE DAY BOUNDARY
    # ----------------------------------------------------------------------
    df_align = align_reference_target(
        df_vel,
        df_next,
        sampling_option=sampling_option,
        interpolate_coordinate=False
    )

    # ----------------------------------------------------------------------
    # 5) COMPUTE RAC COMPONENTS
    # ----------------------------------------------------------------------
    df_rac = compute_rac(df_align)

    return df_rac



def compute_day_boundary_clk(
        clk_prev: str,
        clk_next: str,
        sampling_option: str = "common"
    ) -> pd.DataFrame:
    """
    Compute clock corrections across a day boundary using two consecutive CLK files.

    Parameters
    ----------
    clk_prev : str
        Clock file for day N.
    clk_next : str
        Clock file for day N+1.
    sampling_option : str
        'common' or 'higher'. Default 'common'.

    Returns
    -------
    pd.DataFrame
        df_clock_stats (per-satellite RMS/STD in ns and cm)
    """

    # ---------------------------------------------------------
    # 1) READ DAY-1 CLOCK
    # ---------------------------------------------------------
    nanosec = 1e9
    df_prev = read_clk(clk_prev)
    df_prev["clock"] = df_prev["clock"] * nanosec   # convert sec → ns

    # ---------------------------------------------------------
    # 2) READ DAY-2 CLOCK
    # ---------------------------------------------------------
    df_next = read_clk(clk_next)
    df_next["clock"] = df_next["clock"] * nanosec

    # ---------------------------------------------------------
    # 3) ALIGN TWO DAY CLOCK FILES
    # ---------------------------------------------------------
    df_align = align_reference_target(
        df_prev,
        df_next,
        sampling_option=sampling_option,
        interpolate_coordinate=False   # coordinates not used
    )

    if df_align.empty:
        raise RuntimeError("No common epochs between the two CLK files.")

    # ---------------------------------------------------------
    # 4) COMPUTE CLOCK STATISTICS
    # ---------------------------------------------------------
    _, df_clock_merged = compute_clock_stats(df_align)
    df_clock_merged["sat_delta_cm"] = df_clock_merged["sat_delta"] * (1e-9 * C) * 100
    df_clock = df_clock_merged[['epoch', 'sat', 'sat_delta', 'sat_delta_cm']]

    # Only statistics returned (requested)
    return df_clock


def write_rac_day_boundary(df, outfile, day1_file, day2_file, system=None):
    """
    df  : overall RAC statistics DataFrame
          columns: sat, radial_rms, radial_std, along_rms, along_std, cross_rms, cross_std
    outfile       : output filename
    system        : ['PG','PE','PR', ...] or 'PG' or None
    """
    satmeta  = SatMetaResolver()
    epoch_dt = satmeta.file_epoch_datetime(day2_file)
    # ---------------------------------------------------
    # normalize system parameters --> in list format
    # ---------------------------------------------------
    if system is None:
        selected_systems = None
    else:
        if isinstance(system, str):
            selected_systems = [system]
        elif isinstance(system, (list, tuple, set)):
            selected_systems = list(system)
        else:
            raise ValueError("system must be None, str, list, tuple, or set.")

        if len(selected_systems) == 0:
            print("[WARN] system=[] → no satellites selected")
            return

    # ---------------------------------------------------
    # Satellite systems filtering
    # ---------------------------------------------------
    if selected_systems is not None:
        mask = False
        for sys in selected_systems:
            mask = mask | df["sat"].str.startswith(sys)
        df = df[mask]

    if df.empty:
        print(f"[WARN] No satellites match system={selected_systems}")
        return

    # ---------------------------------------------------
    # write down
    # ---------------------------------------------------
    dt_next, _, _ = read_sp3_headerline(day2_file)
    with open(outfile, 'w') as fout:
        fout.write("# Day-1 File    : {}\n".format(day1_file))
        fout.write("# Day-2 File    : {}\n".format(day2_file))
        fout.write("# ATX File      : {}\n".format(DEFAULT_ATX_FILE))
        fout.write("# Boundary Date : {}\n".format(dt_next))
        fout.write("# Unit          : cm\n")
        fout.write("#\n")
        fout.write("# PRN       SVN     BLOCK                Radial          Along          Cross\n")

        # Uydu sistemleri (ilk iki karakter)
        unique_sys = df["sat"].str[:2].unique()

        # ---------------------------------------------------
        # write all GNSS systems using loop
        # ---------------------------------------------------
        numeric_cols = [
            "radial",
            "along",
            "cross",
        ]

        for sys in unique_sys:

            # PC değilse — GPS, GLO, GAL, QZSS, IRNSS
            if sys != "PC":
                sys_label = {
                    "PG": "GPS",
                    "PR": "GLO",
                    "PE": "GAL",
                    "PJ": "QZSS",
                    "PI": "IRNSS"
                }.get(sys, "Other")

                tmp_df = df[df["sat"].str.startswith(sys)]
                if tmp_df.empty:
                    continue

                fout.write(f"+{sys_label}\n")

                for _, row in tmp_df.sort_values("sat").iterrows():
                    prn, svn, block = satmeta.svn_block_for(row['sat'], epoch_dt)
                    fout.write(
                        " {:4s} {:>9s}     {:<16s} {:10.3f} {:14.3f} {:14.3f}\n".format(
                            row["sat"], svn, block,
                            row['radial'],
                            row['along'],
                            row['cross'],
                        )
                    )

                mean_vals = tmp_df[numeric_cols].mean()
                fout.write(
                    " mean                                {:10.3f} {:14.3f} {:14.3f}\n".format(
                        mean_vals['radial'],
                        mean_vals['along'],
                        mean_vals['cross'],
                    )
                )
                
                rmse_vals = np.sqrt((tmp_df[numeric_cols]**2).mean())
                fout.write(
                    " rmse                                {:10.3f} {:14.3f} {:14.3f}\n".format(
                        rmse_vals['radial'],
                        rmse_vals['along'],
                        rmse_vals['cross'],
                    )
                )
                fout.write(f"-{sys_label}\n\n")

            # ---------------------------------------------------
            # BDS (PC) sub-groups
            # ---------------------------------------------------
            else:
                tmp_df_pc = df[df["sat"].str.startswith("PC")]
                if tmp_df_pc.empty:
                    continue

                # Gruplar
                #BDS_2GEO  = ["PC01","PC02","PC03","PC04","PC05"]
                #BDS_2IGSO = ["PC06","PC07","PC08","PC09","PC10","PC13","PC16"]
                #BDS_2MEO  = ["PC11","PC12","PC14"]
                #BDS_3GEO  = ["PC59","PC60","PC61","PC62"]
                #BDS_3IGSO = ["PC31","PC38","PC39","PC40","PC56"]
                #BDS_3MEO  = [
                #    "PC19","PC20","PC21","PC22","PC23","PC24","PC25","PC26",
                #    "PC27","PC28","PC29","PC30","PC32","PC33","PC34","PC35",
                #    "PC36","PC37","PC41","PC42","PC43","PC44","PC45","PC46",
                #    "PC47","PC48","PC49","PC50","PC57"
                #]
                BDS_2GEO, BDS_2IGSO, BDS_2MEO, \
                BDS_3GEO, BDS_3IGSO, BDS_3MEO = classify_bds_by_block(
                    tmp_df_pc,
                    day2_file
                )

                bds_groups = [
                    ("BDS_2GEO",  BDS_2GEO),
                    ("BDS_2IGSO", BDS_2IGSO),
                    ("BDS_2MEO",  BDS_2MEO),
                    ("BDS_3GEO",  BDS_3GEO),
                    ("BDS_3IGSO", BDS_3IGSO),
                    ("BDS_3MEO",  BDS_3MEO),
                ]

                for sys_label, sat_list in bds_groups:
                    grp_df = tmp_df_pc[tmp_df_pc["sat"].isin(sat_list)]
                    if grp_df.empty:
                        continue

                    fout.write(f"+{sys_label}\n")

                    for _, row in grp_df.sort_values("sat").iterrows():
                        prn, svn, block = satmeta.svn_block_for(row['sat'], epoch_dt)
                        fout.write(
                            " {:4s} {:>9s}     {:<16s} {:10.3f} {:14.3f} {:14.3f}\n".format(
                                prn, svn, block,
                                row['radial'],
                                row['along'],
                                row['cross'],
                            )
                        )

                    mean_vals = grp_df[numeric_cols].mean()
                    fout.write(
                        " mean                                {:10.3f} {:14.3f} {:14.3f}\n".format(
                            mean_vals['radial'],
                            mean_vals['along'],
                            mean_vals['cross'],
                        )
                    )
                    
                    rmse_vals = np.sqrt((grp_df[numeric_cols]**2).mean())
                    fout.write(
                        " rmse                                {:10.3f} {:14.3f} {:14.3f}\n".format(
                            rmse_vals['radial'],
                            rmse_vals['along'],
                            rmse_vals['cross'],
                        )
                    )
                    fout.write(f"-{sys_label}\n\n")
                    

def write_clk_day_boundary(df_stats, outfile, day1_file, day2_file,
                            day1_sp3_file = None, day2_sp3_file = None,
                            system=None):
    """
    df_stats : sat, rms_ns, rms_cm
    system   : ['PG','PE','PR', ...] or 'PG' or None
    """
    satmeta  = SatMetaResolver()
    epoch_dt = satmeta.file_epoch_datetime(day2_file)
    # ---------------------------------------------------
    # normalize system parameters --> in list format
    # ---------------------------------------------------
    if system is None:
        selected_systems = None
    else:
        if isinstance(system, str):
            selected_systems = [system]     
        elif isinstance(system, (list, tuple, set)):
            selected_systems = list(system) 
        else:
            raise ValueError("system must be None, str, list, tuple, or set.")

        if len(selected_systems) == 0:
            print("[WARN] system=[] → no satellites selected")
            return

    # ---------------------------------------------------
    # Satellite systems filtering
    # ---------------------------------------------------
    if selected_systems is not None:
        mask = False
        for sys in selected_systems:
            mask = mask | df_stats["sat"].str.startswith(sys)
        df_stats = df_stats[mask]

    if df_stats.empty:
        print(f"[WARN] No satellites match system={selected_systems}")
        return

    #numeric_cols = ["sat_delta", "sat_delta_cm"]

    # ---------------------------------------------------
    # write down
    # ---------------------------------------------------
    with open(outfile, "w") as fout:
        fout.write(f"# Day-N   CLK File : {day1_file}\n")
        fout.write(f"# Day-N+1 CLK File : {day2_file}\n")
        
        fout.write(f"# Day-N   SP3 File : {day1_sp3_file}\n")
        fout.write(f"# Day-N+1 SP3 File : {day2_sp3_file}\n")
        
        fout.write("# ATX File         : {}\n".format(DEFAULT_ATX_FILE))
        fout.write("# Unit             : ns (1e-9 sec) and centimeter\n")
        fout.write("# Comment          : Rclk stands for Radial Corrected Clock\n")
        fout.write("#\n")
        fout.write("# PRN       SVN     BLOCK                 Clock      Clock       Rclk       Rclk\n")
        fout.write("#                                          [ns]       [cm]       [ns]       [cm]\n")

        # Uydu sistemleri (ör. PG, PR, PE, PC)
        systems = df_stats["sat"].str[:2].unique()

        for sys in systems:

            # ---------------------------------------------------
            # GPS, GLO, GAL, QZSS, IRNSS
            # ---------------------------------------------------
            if sys != "PC":
                sys_label = {
                    "PG": "GPS",
                    "PR": "GLO",
                    "PE": "GAL",
                    "PJ": "QZSS",
                    "PI": "IRNSS"
                }.get(sys, "Other")

                tmp_df = df_stats[df_stats["sat"].str.startswith(sys)]
                if tmp_df.empty:
                    continue

                fout.write(f"+{sys_label}\n")
                
                if any(col.startswith("Rclk") for col in df_stats.columns):
                    numeric_cols = ["sat_delta", "sat_delta_cm", "Rclk", "Rclk_cm"]
                    for _, row in tmp_df.sort_values("sat").iterrows():
                        prn, svn, block = satmeta.svn_block_for(row['sat'], epoch_dt)
                        fout.write(
                            " {:4s} {:>9s}     {:<16s} {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                                row["sat"], svn, block,
                                row["sat_delta"], row["sat_delta_cm"],
                                row["Rclk"], row["Rclk_cm"],
                            )
                        )

                    mean_vals = tmp_df[numeric_cols].mean()
                    fout.write(
                        " mean                                {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                            mean_vals["sat_delta"], mean_vals["sat_delta_cm"],
                            mean_vals["Rclk"], mean_vals["Rclk_cm"],
                        )
                    )
                    rmse_vals = np.sqrt((tmp_df[numeric_cols]**2).mean())
                    fout.write(
                        " rmse                                {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                            rmse_vals["sat_delta"], rmse_vals["sat_delta_cm"],
                            rmse_vals["Rclk"], rmse_vals["Rclk_cm"],
                        )
                    )
                
                else:
                    numeric_cols = ["sat_delta", "sat_delta_cm"]
                    for _, row in tmp_df.sort_values("sat").iterrows():
                        prn, svn, block = satmeta.svn_block_for(row['sat'], epoch_dt)
                        fout.write(
                            " {:4s} {:>9s}     {:<16s} {:10.3f} {:10.3f}\n".format(
                                row["sat"], svn, block,
                                row["sat_delta"], row["sat_delta_cm"],
                            )
                        )

                    mean_vals = tmp_df[numeric_cols].mean()
                    fout.write(
                        " mean                                {:10.3f} {:10.3f}\n".format(
                            mean_vals["sat_delta"], mean_vals["sat_delta_cm"],
                        )
                    )
                    rmse_vals = np.sqrt((tmp_df[numeric_cols]**2).mean())
                    fout.write(
                        " rmse                                {:10.3f} {:10.3f}\n".format(
                            rmse_vals["sat_delta"], rmse_vals["sat_delta_cm"],
                        )
                    )
            
                fout.write(f"-{sys_label}\n\n")

            else:
                tmp_df = df_stats[df_stats["sat"].str.startswith("PC")]
                if tmp_df.empty:
                    continue
                    
                #BDS_2GEO  = ["PC01","PC02","PC03","PC04","PC05"]
                #BDS_2IGSO = ["PC06","PC07","PC08","PC09","PC10","PC13","PC16"]
                #BDS_2MEO  = ["PC11","PC12","PC14"]

                #BDS_3GEO  = ["PC59","PC60","PC61","PC62"]
                #BDS_3IGSO = ["PC31","PC38","PC39","PC40","PC56"]
                #BDS_3MEO  = [
                #    "PC19","PC20","PC21","PC22","PC23","PC24","PC25","PC26",
                #    "PC27","PC28","PC29","PC30","PC32","PC33","PC34","PC35",
                #    "PC36","PC37","PC41","PC42","PC43","PC44","PC45","PC46",
                #    "PC47","PC48","PC49","PC50","PC57"
                #]
                BDS_2GEO, BDS_2IGSO, BDS_2MEO, \
                BDS_3GEO, BDS_3IGSO, BDS_3MEO = classify_bds_by_block(
                    tmp_df,
                    day2_file
                )

                bds_groups = [
                    ("BDS_2GEO",  BDS_2GEO),
                    ("BDS_2IGSO", BDS_2IGSO),
                    ("BDS_2MEO",  BDS_2MEO),
                    ("BDS_3GEO",  BDS_3GEO),
                    ("BDS_3IGSO", BDS_3IGSO),
                    ("BDS_3MEO",  BDS_3MEO),
                ]

                for sys_label, sat_list in bds_groups:
                    grp_df = tmp_df[tmp_df["sat"].isin(sat_list)]
                    if grp_df.empty:
                        continue

                    fout.write(f"+{sys_label}\n")
                
                    if any(col.startswith("Rclk") for col in df_stats.columns):
                        numeric_cols = ["sat_delta", "sat_delta_cm", "Rclk", "Rclk_cm"]
                        for _, row in grp_df.sort_values("sat").iterrows():
                            prn, svn, block = satmeta.svn_block_for(row['sat'], epoch_dt)
                            fout.write(
                                " {:4s} {:>9s}     {:<16s} {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                                    prn, svn, block,
                                    row["sat_delta"], row["sat_delta_cm"],
                                    row["Rclk"], row["Rclk_cm"],
                                )
                            )

                        mean_vals = grp_df[numeric_cols].mean()
                        fout.write(
                            " mean                                {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                                mean_vals["sat_delta"], mean_vals["sat_delta_cm"],
                                mean_vals["Rclk"], mean_vals["Rclk_cm"],
                            )
                        )
                        rmse_vals = np.sqrt((grp_df[numeric_cols]**2).mean())
                        fout.write(
                            " rmse                                {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                                rmse_vals["sat_delta"], rmse_vals["sat_delta_cm"],
                                rmse_vals["Rclk"], rmse_vals["Rclk_cm"],
                            )
                        )
                    
                    else:
                        numeric_cols = ["sat_delta", "sat_delta_cm"]
                        for _, row in grp_df.sort_values("sat").iterrows():
                            prn, svn, block = satmeta.svn_block_for(row['sat'], epoch_dt)
                            fout.write(
                                " {:4s} {:>9s}     {:<16s} {:10.3f} {:10.3f}\n".format(
                                    prn, svn, block,
                                    row["sat_delta"], row["sat_delta_cm"],
                                )
                            )

                        mean_vals = grp_df[numeric_cols].mean()
                        fout.write(
                            " mean                                {:10.3f} {:10.3f}\n".format(
                                mean_vals["sat_delta"], mean_vals["sat_delta_cm"],
                            )
                        )
                        rmse_vals = np.sqrt((grp_df[numeric_cols]**2).mean())
                        fout.write(
                            " rmse                                {:10.3f} {:10.3f}\n".format(
                                rmse_vals["sat_delta"], rmse_vals["sat_delta_cm"],
                            )
                        )

                    fout.write(f"-{sys_label}\n\n")
