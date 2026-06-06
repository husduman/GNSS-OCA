import pandas as pd
import numpy as np
from datetime import datetime
from goca.io.read_atx import read_default_atx, mask_sat_date
from goca.config import DEFAULT_ATX_FILE
from goca.core.sat_meta import SatMetaResolver
from goca.core.bds_classification import classify_bds_by_block

# Speed of light
C = 299792458.0  # m/s


def compute_clock_stats(df_align):
    """
    df_align dataframe:
        epoch, sat, clock_ref, clock_tgt
        
    Returns:
        df_stats with columns:
        sat, rms_ns, std_ns, rms_cm, std_cm
    """

    df_align = df_align.copy()

    # ---------------------------------------------
    # 1) Satellite system (PG, PE, PR ...)
    # ---------------------------------------------
    df_align["sys"] = df_align["sat"].str[:2]

    # ---------------------------------------------
    # 2) Group by epoch + system → compute delta
    # ---------------------------------------------
    df_sum = (
        df_align.groupby(["epoch", "sys"])
        .agg(
            clock_ref_sum=("clock_ref", "sum"),
            clock_tgt_sum=("clock_tgt", "sum"),
            sat_count=("sat", "count")
        )
        .reset_index()
    )

    df_sum["delta"] = (
        (df_sum["clock_ref_sum"] - df_sum["clock_tgt_sum"]) / df_sum["sat_count"]
    )

    # ---------------------------------------------
    # 3) Merge df_align with df_sum to assign delta
    # ---------------------------------------------
    df_merged = df_align.merge(
        df_sum[["epoch", "sys", "delta"]],
        on=["epoch", "sys"],
        how="left"
    )

    # per-satellite clock correction
    df_merged["sat_delta"] = (
        (df_merged["clock_ref"] - df_merged["clock_tgt"]) - df_merged["delta"]
    )

    # ---------------------------------------------
    # 4) Satellite-based RMS / STD statistics
    # ---------------------------------------------
    df_stats = (
        df_merged.groupby("sat")
        .agg(
            rms_ns=("sat_delta", lambda x: np.sqrt(np.mean(x**2))),
            std_ns=("sat_delta", lambda x: np.std(x)),
        )
        .reset_index()
    )

    # ---------------------------------------------
    # 5) Convert ns → cm
    # ---------------------------------------------
    df_stats["rms_cm"] = df_stats["rms_ns"] * (1e-9 * C) * 100
    df_stats["std_cm"] = df_stats["std_ns"] * (1e-9 * C) * 100

    return df_stats, df_merged

def write_clock_output(df, outfile, reference_file, target_file,
                       reference_sp3_file = None, target_sp3_file = None,
                       system=None):
    """
    df      : dataframe including sat_delta
    outfile : output filename
    reference_file : reference CLK filename 
    target_file    : target CLK filename
    system         : ['PG','PE','PR', ...] or 'PG' or None
    """

    # ---------------------------------------------------
    # system parametresini normalize → listeye zorla
    # ---------------------------------------------------
    if system is None:
        selected_systems = None
    else:
        if isinstance(system, str):
            selected_systems = [system]      # tek string → liste
        elif isinstance(system, (list, tuple, set)):
            selected_systems = list(system)  # iterable → liste
        else:
            raise ValueError("system must be None, str, list, tuple, or set.")

        if len(selected_systems) == 0:
            print("[WARN] system=[] → no satellites selected")
            return

    # ---------------------------------------------------
    # Satellite filter
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
    # Date
    # ---------------------------------------------------
    file_date = df["epoch"].dt.strftime("%Y-%m-%d").unique()[0]
    start_date = datetime.strptime(file_date, "%Y-%m-%d")

    # ---------------------------------------------------
    # write down
    # ---------------------------------------------------
    with open(outfile, 'w') as fout:
        fout.write(f"# Reference CLK File : {reference_file}\n")
        fout.write(f"# Target CLK File    : {target_file}\n")
        
        fout.write(f"# Reference SP3 File : {reference_sp3_file}\n")
        fout.write(f"# Target SP3 File    : {target_sp3_file}\n")
        
        fout.write(f"# Comparison Date    : {file_date}\n")
        fout.write("# Unit               : ns (1e-9 sec) and centimeter\n")
        fout.write("# Comment            : Rclk stands for Radial Corrected Clock\n")
        fout.write("#\n")
        if 'eclipse' in df.columns:
            fout.write("# PRN    Second   Clock [ns]   Clock [cm]    Rclk [ns]    Rclk [cm]   Eclipse\n")
        else:
            fout.write("# PRN    Second   Clock [ns]   Clock [cm]    Rclk [ns]    Rclk [cm]\n")

        has_rclk = "Rclk" in df.columns
        has_eclipse = "eclipse" in df.columns  # sadece Rclk varsa anlamlı

        for _, row in df.iterrows():
            sec = int((row["epoch"] - start_date).total_seconds())

            sat = row["sat"]
            sat_delta = row["sat_delta"]
            sat_cm = sat_delta * (1e-9 * C) * 100

            # --------------------------------------------------
            # Not Rclk → only 4 columns
            # --------------------------------------------------
            if not has_rclk:
                fout.write(
                    " {:4s} {:>9d} {:>12.3f} {:>12.3f}\n".format(
                        sat, sec, sat_delta, sat_cm
                    )
                )
                continue

            # --------------------------------------------------
            # Rclk → 6 columns (+ eclipse flag optionally)
            # --------------------------------------------------
            rclk = row["Rclk"]
            rclk_cm = rclk * (1e-9 * C) * 100

            flag = ""
            if has_eclipse:
                e = row.get("eclipse", 0)
                if e == 1:
                    flag = "P"
                elif e == 2:
                    flag = "U"

            if flag:
                fout.write(
                    " {:4s} {:>9d} {:>12.3f} {:>12.3f} {:>12.3f} {:>12.3f} {:>8s}\n".format(
                        sat, sec,
                        sat_delta, sat_cm,
                        rclk, rclk_cm,
                        flag
                    )
                )
            else:
                fout.write(
                    " {:4s} {:>9d} {:>12.3f} {:>12.3f} {:>12.3f} {:>12.3f}\n".format(
                        sat, sec,
                        sat_delta, sat_cm,
                        rclk, rclk_cm
                    )
                )




def write_clock_stats_overall(df_stats, outfile, reference_file, target_file,
                              reference_sp3_file = None, target_sp3_file = None,
                              system=None):
    """
    df_stats : sat, rms_ns, std_ns, rms_cm, std_cm
    system   : ['PG','PE','PR', ...] or 'PG' or None
    """
    satmeta  = SatMetaResolver()
    epoch_dt = satmeta.file_epoch_datetime(reference_file)

    # ---------------------------------------------------
    # normalize system parameters --> in list format
    # ---------------------------------------------------
    if system is None:
        selected_systems = None
    else:
        if isinstance(system, str):
            selected_systems = [system]      # tek string → liste
        elif isinstance(system, (list, tuple, set)):
            selected_systems = list(system)  # iterable → liste
        else:
            raise ValueError("system must be None, str, list, tuple, or set.")

        if len(selected_systems) == 0:
            print("[WARN] system=[] → no satellites selected")
            return

    # ---------------------------------------------------
    # Satellite System filtering
    # ---------------------------------------------------
    if selected_systems is not None:
        mask = False
        for sys in selected_systems:
            mask = mask | df_stats["sat"].str.startswith(sys)
        df_stats = df_stats[mask]

    if df_stats.empty:
        print(f"[WARN] No satellites match system={selected_systems}")
        return


    # ---------------------------------------------------
    # BDS lists
    # ---------------------------------------------------
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
        df_stats,
        reference_file
    )

    #numeric_cols = ["rms_ns", "std_ns", "rms_cm", "std_cm", "Rclk_rms_ns", "Rclk_std_ns", "Rclk_rms_cm", "Rclk_std_cm"]

    # ---------------------------------------------------
    # write down
    # ---------------------------------------------------
    with open(outfile, "w") as fout:
        fout.write(f"# Reference CLK File : {reference_file}\n")
        fout.write(f"# Target CLK File    : {target_file}\n")
        
        fout.write(f"# Reference SP3 File : {reference_sp3_file}\n")
        fout.write(f"# Target SP3 File    : {target_sp3_file}\n")
        
        fout.write("# ATX File           : {}\n".format(DEFAULT_ATX_FILE))
        fout.write("# Unit               : ns (1e-9 sec) and centimeter\n")
        fout.write("# Comment            : Rclk stands for Radial Corrected Clock\n")
        fout.write("#\n")
        fout.write("# PRN       SVN     BLOCK                       Clock [ns]            Clock [cm]             Rclk [ns]             Rclk [cm]\n")
        fout.write("#                                           RMS        STD        RMS        STD        RMS        STD        RMS        STD\n")

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
                    numeric_cols = ["rms_ns", "std_ns", "rms_cm", "std_cm", "Rclk_rms_ns", "Rclk_std_ns", "Rclk_rms_cm", "Rclk_std_cm"]
                    for _, row in tmp_df.sort_values("sat").iterrows():
                        prn, svn, block = satmeta.svn_block_for(row['sat'], epoch_dt)
                        fout.write(
                            " {:4s} {:>9s}     {:<16s} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                                row["sat"], svn, block,
                                row["rms_ns"], row["std_ns"],
                                row["rms_cm"], row["std_cm"],
                                row["Rclk_rms_ns"], row["Rclk_std_ns"],
                                row["Rclk_rms_cm"], row["Rclk_std_cm"],
                            )
                        )

                    mean_vals = tmp_df[numeric_cols].mean()
                    fout.write(
                        " mean                                {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                            mean_vals["rms_ns"], mean_vals["std_ns"],
                            mean_vals["rms_cm"], mean_vals["std_cm"],
                            mean_vals["Rclk_rms_ns"], mean_vals["Rclk_std_ns"],
                            mean_vals["Rclk_rms_cm"], mean_vals["Rclk_std_cm"],
                        )
                    )
                    
                    rmse_vals = np.sqrt((tmp_df[numeric_cols]**2).mean())
                    fout.write(
                        " rmse                                {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                            rmse_vals["rms_ns"], rmse_vals["std_ns"],
                            rmse_vals["rms_cm"], rmse_vals["std_cm"],
                            rmse_vals["Rclk_rms_ns"], rmse_vals["Rclk_std_ns"],
                            rmse_vals["Rclk_rms_cm"], rmse_vals["Rclk_std_cm"],
                        )
                    )
                    #fout.write(f"-{sys_label}\n\n")
                    
                else:
                    numeric_cols = ["rms_ns", "std_ns", "rms_cm", "std_cm"]
                    for _, row in tmp_df.sort_values("sat").iterrows():
                        prn, svn, block = satmeta.svn_block_for(row['sat'], epoch_dt)
                        fout.write(
                            " {:4s} {:>9s}     {:<16s} {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                                row["sat"], svn, block,
                                row["rms_ns"], row["std_ns"],
                                row["rms_cm"], row["std_cm"],
                            )
                        )

                    mean_vals = tmp_df[numeric_cols].mean()
                    fout.write(
                        " mean                                {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                            mean_vals["rms_ns"], mean_vals["std_ns"],
                            mean_vals["rms_cm"], mean_vals["std_cm"],
                        )
                    )
                    
                    rmse_vals = np.sqrt((tmp_df[numeric_cols]**2).mean())
                    fout.write(
                        " rmse                                {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                            rmse_vals["rms_ns"], rmse_vals["std_ns"],
                            rmse_vals["rms_cm"], rmse_vals["std_cm"],
                        )
                    )
                fout.write(f"-{sys_label}\n\n")

            else:
                # ---------------------------------------------------
                # BEIDOU (PC) sub-groups
                # ---------------------------------------------------
                tmp_df = df_stats[df_stats["sat"].str.startswith("PC")]
                if tmp_df.empty:
                    continue

                bds_groups = [
                    ("BDS_2GEO",  BDS_2GEO),
                    ("BDS_2IGSO", BDS_2IGSO),
                    ("BDS_2MEO",  BDS_2MEO),
                    ("BDS_3GEO",  BDS_3GEO),
                    ("BDS_3IGSO", BDS_3IGSO),
                    ("BDS_3MEO",  BDS_3MEO),
                ]

                for label, sat_list in bds_groups:
                    grp_df = tmp_df[tmp_df["sat"].isin(sat_list)]
                    if grp_df.empty:
                        continue

                    fout.write(f"+{label}\n")
                
                    if any(col.startswith("Rclk") for col in df_stats.columns):
                        numeric_cols = ["rms_ns", "std_ns", "rms_cm", "std_cm", "Rclk_rms_ns", "Rclk_std_ns", "Rclk_rms_cm", "Rclk_std_cm"]
                        for _, row in grp_df.sort_values("sat").iterrows():
                            prn, svn, block = satmeta.svn_block_for(row['sat'], epoch_dt)
                            fout.write(
                                " {:4s} {:>9s}     {:<16s} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                                    prn, svn, block,
                                    row["rms_ns"], row["std_ns"],
                                    row["rms_cm"], row["std_cm"],
                                    row["Rclk_rms_ns"], row["Rclk_std_ns"],
                                    row["Rclk_rms_cm"], row["Rclk_std_cm"],
                                )
                            )

                        mean_vals = grp_df[numeric_cols].mean()
                        fout.write(
                            " mean                                {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                                mean_vals["rms_ns"], mean_vals["std_ns"],
                                mean_vals["rms_cm"], mean_vals["std_cm"],
                                mean_vals["Rclk_rms_ns"], mean_vals["Rclk_std_ns"],
                                mean_vals["Rclk_rms_cm"], mean_vals["Rclk_std_cm"],
                            )
                        )
                        rmse_vals = np.sqrt((grp_df[numeric_cols]**2).mean())
                        fout.write(
                            " rmse                                {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                                rmse_vals["rms_ns"], rmse_vals["std_ns"],
                                rmse_vals["rms_cm"], rmse_vals["std_cm"],
                                rmse_vals["Rclk_rms_ns"], rmse_vals["Rclk_std_ns"],
                                rmse_vals["Rclk_rms_cm"], rmse_vals["Rclk_std_cm"],
                            )
                        )
                        #fout.write(f"-{sys_label}\n\n")
                        
                    else:
                        numeric_cols = ["rms_ns", "std_ns", "rms_cm", "std_cm"]
                        for _, row in grp_df.sort_values("sat").iterrows():
                            prn, svn, block = satmeta.svn_block_for(row['sat'], epoch_dt)
                            fout.write(
                                " {:4s} {:>9s}     {:<16s} {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                                    prn, svn, block,
                                    row["rms_ns"], row["std_ns"],
                                    row["rms_cm"], row["std_cm"],
                                )
                            )

                        mean_vals = grp_df[numeric_cols].mean()
                        fout.write(
                            " mean                                {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                                mean_vals["rms_ns"], mean_vals["std_ns"],
                                mean_vals["rms_cm"], mean_vals["std_cm"],
                            )
                        )
                        
                        rmse_vals = np.sqrt((grp_df[numeric_cols]**2).mean())
                        fout.write(
                            " rmse                                {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                                rmse_vals["rms_ns"], rmse_vals["std_ns"],
                                rmse_vals["rms_cm"], rmse_vals["std_cm"],
                            )
                        )
                    fout.write(f"-{label}\n\n")
