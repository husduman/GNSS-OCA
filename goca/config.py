from __future__ import annotations

from pathlib import Path
import re
import os


# GUI defaults
GEOMETRY = "1400x800"

# GOCA root directory (…/GOCAv1.0)
GOCA_ROOT = Path(__file__).resolve().parent.parent


# Icon directory
ICON_DIR = GOCA_ROOT / "icon"

# Tkinter için her işletim sisteminde PNG kullan
ICON_PATH = ICON_DIR / "icon.png"


# Analysis defaults
DEFAULT_SAMPLING_OPTION = "common"  # 'higher' or 'common'
DEFAULT_RO = 30.0
DEFAULT_R = 10200.0
NANOSEC = 1e9


# Data directories
DATA_DIR = GOCA_ROOT / "data"
ATX_DIR = DATA_DIR / "atx"


_ATX_RE = re.compile(r"^(.+?)_(\d{4})\.atx$", re.IGNORECASE)


def find_latest_atx(atx_dir: Path = ATX_DIR) -> tuple[int, Path]:
    """
    Scan atx_dir and return (gps_week, filepath) for the newest *_####.atx.
    """
    if not atx_dir.exists():
        raise FileNotFoundError(f"ATX directory not found: {atx_dir}")

    best_week: int | None = None
    best_path: Path | None = None

    for p in atx_dir.iterdir():
        if not p.is_file():
            continue

        m = _ATX_RE.match(p.name)
        if not m:
            continue

        week = int(m.group(2))

        if best_week is None or week > best_week:
            best_week = week
            best_path = p

    if best_week is None or best_path is None:
        raise FileNotFoundError(
            f"No ATX files found in {atx_dir}. Expected pattern: '*_####.atx'"
        )

    return best_week, best_path


def find_atx_by_week(atx_dir: Path, week: int) -> Path:
    """
    Find an ATX file in atx_dir whose filename ends with _WWWW.atx.
    """
    if not atx_dir.exists():
        raise FileNotFoundError(f"ATX directory not found: {atx_dir}")

    for p in atx_dir.iterdir():
        if not p.is_file():
            continue

        m = _ATX_RE.match(p.name)
        if not m:
            continue

        if int(m.group(2)) == int(week):
            return p

    raise FileNotFoundError(f"No ATX file for GPS week {week} found in {atx_dir}")


_env_atx = os.getenv("GOCA_ATX")
_env_week = os.getenv("GOCA_ATX_WEEK")


if _env_atx:
    DEFAULT_ATX_FILE = Path(_env_atx).expanduser().resolve()

    if not DEFAULT_ATX_FILE.exists():
        raise FileNotFoundError(f"GOCA_ATX points to missing file: {DEFAULT_ATX_FILE}")

    m = _ATX_RE.match(DEFAULT_ATX_FILE.name)
    DEFAULT_ATX_GPS_WEEK = int(m.group(2)) if m else -1

elif _env_week:
    wk = int(_env_week)
    DEFAULT_ATX_GPS_WEEK = wk
    DEFAULT_ATX_FILE = find_atx_by_week(ATX_DIR, wk)

else:
    DEFAULT_ATX_GPS_WEEK, DEFAULT_ATX_FILE = find_latest_atx()