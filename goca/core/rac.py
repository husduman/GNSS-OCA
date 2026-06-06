import numpy as np
import pandas as pd
from datetime import datetime
from goca.io.read_atx import read_default_atx, mask_sat_date
from goca.config import DEFAULT_ATX_FILE
from goca.core.sat_meta import SatMetaResolver
from goca.core.bds_classification import classify_bds_by_block

def compute_rac(df):

    df = df.copy()

    cols = ['X_ref','Y_ref','Z_ref',
            'X_tgt','Y_tgt','Z_tgt',
            'Vx_ref','Vy_ref','Vz_ref']
    df[cols] = df[cols].astype(float)

    r = df[['X_ref','Y_ref','Z_ref']].to_numpy().reshape(-1,3)
    v = df[['Vx_ref','Vy_ref','Vz_ref']].to_numpy().reshape(-1,3)

    # 2) ct = (r × v) / |r × v|
    cross_rv = np.cross(r, v)
    norm_cross = np.linalg.norm(cross_rv, axis=1).reshape(-1,1)
    ct = cross_rv / norm_cross

    # 3) rad = r / |r|
    norm_r = np.linalg.norm(r, axis=1).reshape(-1,1)
    rad = r / norm_r

    # 4) at = ct × rad
    at = np.cross(ct, rad)

    # 5) dcoor = r_ref - r_tgt
    dcoor = (df[['X_tgt','Y_tgt','Z_tgt']].to_numpy().reshape(-1,3)
           - df[['X_ref','Y_ref','Z_ref']].to_numpy().reshape(-1,3))

       
    # 6) components
    radial = np.sum(rad * dcoor, axis=1)
    along  = np.sum(at  * dcoor, axis=1)
    cross  = np.sum(ct  * dcoor, axis=1)

    df["radial"] = radial * 100
    df["along"]  = along * 100
    df["cross"]  = cross * 100
    
    return df


def compute_overall_rac_stats(df):
    """
    Input:
        df: DataFrame at epoch level
            must contain at least the following columns:
            - 'sat'
            - 'radial'
            - 'along'
            - 'cross'

    Output:
        A DataFrame with columns:
            sat, radial_rms, radial_std, along_rms, along_std, cross_rms, cross_std
        where the number of rows equals the number of unique satellites.
    """

    def rms(x):
        x = pd.to_numeric(x, errors='coerce')   # emin olmak için
        return np.sqrt(np.nanmean(x**2))

    grouped = df.groupby("sat")

    stats_df = grouped.agg(
        radial_rms=("radial", rms),
        radial_std=("radial", lambda x: pd.to_numeric(x, errors='coerce').std()),
        along_rms=("along", rms),
        along_std=("along", lambda x: pd.to_numeric(x, errors='coerce').std()),
        cross_rms=("cross", rms),
        cross_std=("cross", lambda x: pd.to_numeric(x, errors='coerce').std()),
    ).reset_index()

    return stats_df


def write_rac_output(df, outfile, reference_file, target_file, system=None, eclipse=False):
    """
    df      : DataFrame containing RAC columns
    outfile : name of the output file
    system  : ['PG','PE','PR', ...] or 'PG' or None
    eclipse : True  → include Eclipse column (P/U)
              False → do not include Eclipse column
    """

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

    if selected_systems is not None:
        mask = False
        for sys in selected_systems:
            mask = mask | df["sat"].str.startswith(sys)
        df = df[mask]

    if df.empty:
        print(f"[WARN] No satellites match system={selected_systems}")
        return

    file_date = df["epoch"].dt.strftime("%Y-%m-%d").unique()[0]
    start_date = datetime.strptime(file_date, "%Y-%m-%d")

    with open(outfile, 'w') as fout:

        fout.write(f"# Reference  File : {reference_file}\n")
        fout.write(f"# Target File     : {target_file}\n")
        fout.write(f"# Comparison Date : {file_date}\n")
        fout.write("# Unit            : cm\n")

        if eclipse:
            fout.write("# COMMENT         : Eclipse U and P stand for UMBRA and PENUMBRA, respectively\n")

        fout.write("#\n")

        if eclipse:
            fout.write("# PRN    Second       Radial    Along-Track  Cross-Track   Eclipse\n")
        else:
            fout.write("# PRN    Second       Radial    Along-Track  Cross-Track\n")

        for _, row in df.iterrows():

            sec = int((row['epoch'] - start_date).total_seconds())

            if eclipse:
                if row.get("eclipse", 0) == 1:
                    flag = 'P'
                elif row.get("eclipse", 0) == 2:
                    flag = 'U'
                else:
                    flag = ''
                fout.write(" {:4s} {:>9d} {:>12.3f} {:>12.3f} {:>12.3f} {:>5s}\n".format(
                    row['sat'], sec,
                    row['radial'], row['along'], row['cross'], flag
                ))
            else:
                fout.write(" {:4s} {:>9d} {:>12.3f} {:>12.3f} {:>12.3f}\n".format(
                    row['sat'], sec,
                    row['radial'], row['along'], row['cross']
                ))





def write_rac_output_overall(df, outfile, reference_file, target_file, system=None):
    """
    df      : DataFrame containing overall RAC statistics
              columns: sat, radial_rms, radial_std, along_rms, along_std, cross_rms, cross_std
    outfile : name of the output file
    system  : ['PG','PE','PR', ...] or 'PG' or None
              Note: Even if a single system is provided, it will be converted to a list.
    """

    satmeta  = SatMetaResolver()
    epoch_dt = satmeta.file_epoch_datetime(reference_file)
    
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

    if selected_systems is not None:
        mask = False
        for sys in selected_systems:
            mask = mask | df["sat"].str.startswith(sys)
        df = df[mask]

    if df.empty:
        print(f"[WARN] No satellites match system={selected_systems}")
        return

    with open(outfile, 'w') as fout:
        fout.write("# Reference  File : {}\n".format(reference_file))
        fout.write("# Target File     : {}\n".format(target_file))
        fout.write("# ATX File        : {}\n".format(DEFAULT_ATX_FILE))
        fout.write("# Unit            : cm\n")
        fout.write("#\n")
        fout.write("# PRN       SVN     BLOCK                           Radial           Along-Track           Cross-Track\n")
        fout.write("#                                           RMS        STD        RMS        STD        RMS        STD\n")

        unique_sys = df["sat"].str[:2].unique()

        numeric_cols = [
            "radial_rms", "radial_std",
            "along_rms",  "along_std",
            "cross_rms",  "cross_std"
        ]

        for sys in unique_sys:

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
                        " {:4s} {:>9s}     {:<16s} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                            row['sat'], svn, block,
                            row['radial_rms'], row['radial_std'],
                            row['along_rms'],  row['along_std'],
                            row['cross_rms'],  row['cross_std'],
                        )
                    )

                mean_vals = tmp_df[numeric_cols].mean()
                fout.write(
                    " mean                                {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                        mean_vals['radial_rms'], mean_vals['radial_std'],
                        mean_vals['along_rms'],  mean_vals['along_std'],
                        mean_vals['cross_rms'],  mean_vals['cross_std'],
                    )
                )
                rmse_vals = np.sqrt((tmp_df[numeric_cols]**2).mean())
                fout.write(
                    " rmse                                {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                        rmse_vals['radial_rms'], rmse_vals['radial_std'],
                        rmse_vals['along_rms'],  rmse_vals['along_std'],
                        rmse_vals['cross_rms'],  rmse_vals['cross_std'],
                    )
                )
                fout.write(f"-{sys_label}\n\n")

            else:
                tmp_df_pc = df[df["sat"].str.startswith("PC")]
                if tmp_df_pc.empty:
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
                    tmp_df_pc,
                    reference_file
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
                            " {:4s} {:>9s}     {:<16s} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                                prn, svn, block,
                                row['radial_rms'], row['radial_std'],
                                row['along_rms'],  row['along_std'],
                                row['cross_rms'],  row['cross_std'],
                            )
                        )

                    mean_vals = grp_df[numeric_cols].mean()
                    fout.write(
                        " mean                                {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                            mean_vals['radial_rms'], mean_vals['radial_std'],
                            mean_vals['along_rms'],  mean_vals['along_std'],
                            mean_vals['cross_rms'],  mean_vals['cross_std'],
                        )
                    )
                    rmse_vals = np.sqrt((grp_df[numeric_cols]**2).mean())
                    fout.write(
                        " rmse                                {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f} {:10.3f}\n".format(
                            rmse_vals['radial_rms'], rmse_vals['radial_std'],
                            rmse_vals['along_rms'],  rmse_vals['along_std'],
                            rmse_vals['cross_rms'],  rmse_vals['cross_std'],
                        )
                    )

                    fout.write(f"-{sys_label}\n\n")

