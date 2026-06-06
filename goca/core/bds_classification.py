from collections import defaultdict
from goca.core.sat_meta import SatMetaResolver


def classify_bds_by_block(df, reference_file):

    satmeta = SatMetaResolver()
    epoch_dt = satmeta.file_epoch_datetime(reference_file)

    bds_groups = defaultdict(list)

    block_map = {
        "BEIDOU-2G": "BDS_2GEO",
        "BEIDOU-2I": "BDS_2IGSO",
        "BEIDOU-2M": "BDS_2MEO",
        "BEIDOU-3G": "BDS_3GEO",
        "BEIDOU-3I": "BDS_3IGSO",
        "BEIDOU-3M": "BDS_3MEO",
    }

    for sat in df["sat"]:

        if not str(sat).startswith("PC"):
            continue

        prn, svn, block = satmeta.svn_block_for(sat, epoch_dt)

        for key, group_name in block_map.items():

            if key in block:
                bds_groups[group_name].append(prn)
                break

    return (
        bds_groups["BDS_2GEO"],
        bds_groups["BDS_2IGSO"],
        bds_groups["BDS_2MEO"],
        bds_groups["BDS_3GEO"],
        bds_groups["BDS_3IGSO"],
        bds_groups["BDS_3MEO"],
    )
