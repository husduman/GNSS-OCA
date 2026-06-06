from __future__ import annotations
import pandas as pd
from datetime import datetime
from goca.io.read_atx import read_default_atx, mask_sat_date
from goca.config import DEFAULT_ATX_FILE
from goca.core.sat_meta import SatMetaResolver
from goca.core.bds_classification import classify_bds_by_block

def write_hadamard_output(
    df_stats,
    outfile,
    clk_file,
    tau=None,        
    ro=None          
):

    """
    GOCC-format Hadamard ASCII writer.
    df_stats:
        single → sat, N, 3m, hdev
    """
    
    satmeta  = SatMetaResolver()
    epoch_dt = satmeta.file_epoch_datetime(clk_file)

    if df_stats is None or df_stats.empty:
        raise ValueError("df_stats is empty — nothing to write.")

    # Speed of light
    C = 299792458.0  # m/s

    # ----------------------------------------------
    # BDS SUBGROUPS
    # ----------------------------------------------
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
        clk_file
    )
    
    bds_groups = [
        ("BDS_2GEO",  BDS_2GEO),
        ("BDS_2IGSO", BDS_2IGSO),
        ("BDS_2MEO",  BDS_2MEO),
        ("BDS_3GEO",  BDS_3GEO),
        ("BDS_3IGSO", BDS_3IGSO),
        ("BDS_3MEO",  BDS_3MEO),
    ]
    
    # ---------------------------------------------------
    # SYSTEM LIST (PG, PR, PE, PC, PJ, PI)
    # ---------------------------------------------------
    systems = df_stats["sat"].str[:2].unique()

    # System name mapping (Day-boundary style)
    sys_names = {
        "PG": "GPS",
        "PR": "GLO",
        "PE": "GAL",
        "PC": "BDS",
        "PJ": "QZSS",
        "PI": "IRNSS"
    }

    # ----------------------------------------------
    # OPEN FILE
    # ----------------------------------------------
    fout = open(outfile, "w")

    # ----------------------------------------------
    # HEADER
    # ----------------------------------------------
    fout.write("# CLK File                 : {}\n".format(clk_file))
    fout.write("# ATX File                 : {}\n".format(DEFAULT_ATX_FILE))
    fout.write("#\n")
       
    
    # ---------------------------------------------------
    if tau is None:
        raise ValueError("tau must be provided for single mode.")

    m = int(tau / ro) if ro else None

    fout.write("# Smoothing time (r)       : {} second\n".format(int(tau)))
    fout.write("# Sampling interval (ro)   : {} second\n".format(ro))
    fout.write("# Hadamard factor (m=r/ro) : {}\n".format(m))
    fout.write("#\n")
    
    bool_flag = "flag" in df_stats.columns
    if bool_flag:
        fout.write("# PRN       SVN     BLOCK                     N            HDEV      Outlier(%)      FLAG\n")
        fout.write("# ------------------------------------------------------------------------------------------\n")
    else:
        fout.write("# PRN       SVN     BLOCK                     N            HDEV      Outlier(%)\n")
        fout.write("# -----------------------------------------------------------------------------\n")

    # ===================================================
    # WRITE SYSTEM BLOCKS
    # ===================================================
    for sys in systems:

        # ----------------------------
        # NON-BDS SYSTEMS
        # ----------------------------
        if sys != "PC":

            sys_label = sys_names.get(sys, "OTHER")
            fout.write("+{}\n".format(sys_label))

            tmp = df_stats[df_stats["sat"].str.startswith(sys)]

            for _, row in tmp.iterrows():
                hdev = row["hdev"]
                outperc = row["outlier"]
                N = int(row["N"]) if not pd.isna(row["N"]) else None
                prn, svn, block = satmeta.svn_block_for(row['sat'], epoch_dt)
                flag = row['flag'] if bool_flag else ""
                if pd.isna(hdev):
                    fout.write(" {:4s} {:>9s}     {:<16s} {:10d} {:>15} {:>15}      {:<7s}\n".format(prn, svn, block, N, "NA", "NA", flag))
                else:
                    fout.write(
                        " {:4s} {:>9s}     {:<16s} {:10d} {:15.4e} {:15.3f}      {:<7s}\n".format(
                            prn, svn, block, N, hdev * 1e-2, outperc, flag
                        )
                    )

            fout.write("-{}\n\n".format(sys_label))

        # ----------------------------
        # BDS SYSTEM (PC) — subgroups
        # ----------------------------
        else:

            tmp = df_stats[df_stats["sat"].str.startswith("PC")]
            if tmp.empty:
                continue

            # Loop through predefined BDS subgroups
            for label, sat_list in bds_groups:

                grp = tmp[tmp["sat"].isin(sat_list)]
                if grp.empty:
                    continue

                fout.write("+{}\n".format(label))
                
                for _, row in grp.iterrows():
                    hdev = row["hdev"]
                    outperc = row["outlier"]
                    N = int(row["N"]) if not pd.isna(row["N"]) else None
                    prn, svn, block = satmeta.svn_block_for(row['sat'], epoch_dt)
                    flag = row['flag'] if bool_flag else ""
                    if pd.isna(hdev):
                        fout.write(" {:4s} {:>9s}     {:<16s} {:10d} {:>15} {:>15}      {:<7s}\n".format(prn, svn, block, N, "NA", "NA", flag))
                    else:
                        fout.write(
                            " {:4s} {:>9s}     {:<16s} {:10d} {:15.4e} {:15.3f}      {:<7s}\n".format(
                                prn, svn, block, N, hdev * 1e-2, outperc, flag
                            )
                        )

                fout.write("-{}\n\n".format(label))

    fout.close()

