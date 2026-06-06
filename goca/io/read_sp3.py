import mmap
import re
import pandas as pd
import datetime
import numpy as np
from datetime import datetime

def read_sp3_headerline(file_sp3):
    with open(file_sp3, 'r') as fsp3:
        first_two_line_sp3 = fsp3.readlines()[:2]
    fsp3.close()
    dateofsp3 = datetime(
        year   = int(first_two_line_sp3[0][3:7]),
        month  = int(first_two_line_sp3[0][8:10]),
        day    = int(first_two_line_sp3[0][11:13]),
        hour   = int(first_two_line_sp3[0][14:16]),
        minute = int(first_two_line_sp3[0][17:19]),
        second = int(first_two_line_sp3[0][20:31].split('.')[0]))
            
    num_epochs     = int(first_two_line_sp3[0][32:39])
    epoch_interval = float(first_two_line_sp3[1][24:38])
    return dateofsp3, num_epochs, epoch_interval

    

def read_sp3(file_sp3):

    data = []
    current_epoch = None

    try:
        with open(file_sp3, "rb") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:

                for line in iter(mm.readline, b""):
                    line = line.rstrip(b'\r\n')

                    if line[0:1] == b'*':
                        parts = line.split()
                        current_epoch = datetime(
                            int(parts[1]),
                            int(parts[2]),
                            int(parts[3]),
                            int(parts[4]),
                            int(parts[5]),
                            int(float(parts[6]))
                        )

                    elif line[0:1] == b'P':
                        sat = line[1:4].decode()

                        x = float(line[4:18]) * 1000.0
                        y = float(line[18:32]) * 1000.0
                        z = float(line[32:46]) * 1000.0
                        clk = float(line[46:60])

                        if x == 0.0 or y == 0.0 or z == 0.0:
                            continue

                        if clk == 999999.999999:
                            clk = np.nan
                        else:
                            clk *= 1e-6

                        data.append((current_epoch, sat, x, y, z, clk))

        df = pd.DataFrame(data, columns=['epoch', 'sat', 'X', 'Y', 'Z', 'clk'])
        df['sat'] = 'P' + df['sat'].astype(str)

    except Exception as e:
        raise RuntimeError(f"Failed to open file '{file_sp3}': {e}")

    return df
