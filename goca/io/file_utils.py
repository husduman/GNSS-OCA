# lib/file_naming.py
import os
import re

def extract_file_part(filepath):

    name = os.path.basename(filepath)
    name_up = name.upper()

    # Ör: COD0MGXFIN_20210870000_01D_05M_ORB.SP3
    m = re.match(r"([A-Z0-9]+?)_\d{7,}", name_up)
    if m:
        return m.group(1)

    # Ör: emr21510.sp3 → EMR
    m = re.match(r"([A-Z]{3})\d{4,5}", name_up)
    if m:
        return m.group(1)

    # Ör: COD0MGXFIN.SP3 → COD0MGXFIN
    m = re.match(r"([A-Z]+)\.", name_up)
    if m:
        return m.group(1)

    return re.sub(r"[^A-Z]", "", name_up)


def build_output_filename(ref_path, tgt_path, date_str, mode="orbit", type="epoch_wise"):
    """
    mode : 'orbit' or 'clock'
    type : 'epoch' or 'overall'
    date_str : TreeView YYYY-MM-DD date
    """

    ref_part = extract_file_part(ref_path)
    tgt_part = extract_file_part(tgt_path)
    if type == "boundary":
        if mode == "orbit":
            prefix = "dayboundary_orbit"
        else:
            prefix = "dayboundary_clock"
        filename = f"{prefix}_{ref_part}_{tgt_part}_{date_str}.out"
    else:        
        if mode == "orbit":
            prefix = "comparison_orbit"
        else:
            prefix = "comparison_clock"

        filename = f"{prefix}_{ref_part}_{tgt_part}_{date_str}_{type}.out"
    return filename
