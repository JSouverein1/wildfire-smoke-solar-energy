"""Extract daily MODIS COSP cloud fraction for NOAA SURFRAD station grid cells.

Input: MCD06COSP_D3_MODIS*.nc (NASA LAADS, combined Terra/Aqua).
Reads the 1-degree Cloud_Mask_Fraction/Mean from the grid cell containing
(or nearest to) each station. IMPORTANT: the NetCDF array is [longitude, latitude],
NOT [latitude, longitude]. Missing/fill values are never interpreted as zero.

Run from the repository root:
    python scripts/extract_modis_cosp_cloud.py
    python scripts/extract_modis_cosp_cloud.py --start 2020-09-01 --end 2020-09-30
    python scripts/extract_modis_cosp_cloud.py --input path/to/one_file.nc
    python scripts/extract_modis_cosp_cloud.py --merge-master data/processed/master_station_days.csv

Output CSV contains date, station, cloud_fraction, cloud_percent, MODIS
pixel count, grid-cell coordinates, data status, and source filename.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
import re

import h5py
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/raw/modis_cosp"
DEFAULT_OUTPUT = ROOT / "data/processed/cloud_fraction.csv"

# EXACT stations used by scripts/pipeline.py
STATIONS = {
    "tbl": {"name": "Table Mountain", "lat": 40.12498, "lon": -105.23680},
    "fpk": {"name": "Fort Peck", "lat": 48.30783, "lon": -105.10170},
    "dra": {"name": "Desert Rock", "lat": 36.62373, "lon": -116.01947},
    "bon": {"name": "Bondville", "lat": 40.05192, "lon": -88.37309},
}
PRODUCT = "MCD06COSP_D3_MODIS"
FILENAME_RE = re.compile(
    r"^MCD06COSP_D3_MODIS\.A(\d{4})(\d{3})\.(\d{3})\.(\d{13})\.nc$"
)


def acquisition_date(filename: str) -> date:
    """Parse acquisition YYYY+day-of-year; processing timestamp is NOT acquisition date."""
    match = FILENAME_RE.fullmatch(filename)
    if match is None:
        raise ValueError(f"Not an {PRODUCT} daily NetCDF filename: {filename}")
    year, doy = map(int, match.group(1, 2))
    day = date(year, 1, 1) + timedelta(days=doy - 1)
    if doy < 1 or day.year != year:
        raise ValueError(f"Invalid acquisition day of year: {filename}")
    return day


def files_to_process(input_path: Path, start: date | None, end: date | None):
    if input_path.is_file():
        paths = [input_path]
    elif input_path.is_dir():
        paths = list(input_path.rglob(f"{PRODUCT}.A*.nc"))
    else:
        raise FileNotFoundError(f"Input file/folder does not exist: {input_path}")

    # If files for the same acquisition day have been reprocessed, take the
    # lexicographically greatest (collection version + production timestamp).
    by_date = {}
    for path in paths:
        try:
            day = acquisition_date(path.name)
        except ValueError:
            continue
        if (start and day < start) or (end and day > end):
            continue
        if day not in by_date or path.name > by_date[day].name:
            by_date[day] = path
    return sorted(by_date.items())


def _normalize_lon(lon: float) -> float:
    """Match MODIS [-180,180) coordinates, if longitudes are supplied as 0..360."""
    return (lon + 180) % 360 - 180


def extract_file(path: Path, stations: list[str], min_pixels: int = 1) -> list[dict]:
    """Read 4 scalar cells without loading the entire 43MB file into memory."""
    day = acquisition_date(path.name)
    rows = []
    with h5py.File(path, "r") as nc:
        latitudes = np.asarray(nc["latitude"][:], dtype=float)
        longitudes = np.asarray(nc["longitude"][:], dtype=float)
        mean = nc["Cloud_Mask_Fraction/Mean"]
        counts = nc["Cloud_Mask_Fraction/Pixel_Counts"]
        expected = (len(longitudes), len(latitudes))
        if mean.shape != expected or counts.shape != expected:
            raise ValueError(
                f"Unexpected MODIS dimensions {mean.shape}; expected {expected} "
                "(longitude, latitude)"
            )
        if not np.isfinite(latitudes).all() or not np.isfinite(longitudes).all():
            raise ValueError(f"Bad lat/lon coordinates in {path.name}")
        for station in stations:
            st = STATIONS[station]
            lat_idx = int(np.abs(latitudes - st["lat"]).argmin())
            lon_idx = int(np.abs(longitudes - _normalize_lon(st["lon"])).argmin())
            # The actual order is [longitude, latitude] in this product.
            value = float(mean[lon_idx, lat_idx])
            pixel_count = int(counts[lon_idx, lat_idx])
            if pixel_count < min_pixels:
                status = "insufficient_pixels"
            elif not np.isfinite(value) or value == -999:
                status = "missing_value"
            elif not 0 <= value <= 1:
                status = "invalid_fraction"
            else:
                status = "ok"
            fraction = value if status == "ok" else float("nan")
            rows.append({
                "date": day.isoformat(),
                "station": station,
                "cloud_fraction": fraction,
                "cloud_percent": fraction * 100,
                "modis_pixel_count": pixel_count if pixel_count >= 0 else np.nan,
                "modis_status": status,
                "grid_lat": float(latitudes[lat_idx]),
                "grid_lon": float(longitudes[lon_idx]),
                "station_lat": st["lat"],
                "station_lon": st["lon"],
                "modis_product": PRODUCT,
                "source_file": path.name,
            })
    return rows


def merge_master(master_path: Path, cloud: pd.DataFrame, output_path: Path) -> None:
    master = pd.read_csv(master_path, dtype={"station": "string"})
    required = {"date", "station"}
    if not required.issubset(master.columns):
        raise ValueError(f"Master CSV needs columns: {sorted(required)}")
    master["date"] = pd.to_datetime(master["date"]).dt.strftime("%Y-%m-%d")
    subset = cloud[["date", "station", "cloud_fraction", "modis_pixel_count", "modis_status"]]
    merged = master.merge(subset, on=["date", "station"], how="left", validate="one_to_one")
    # Values absent from MODIS remain missing, not zero or "clear".
    merged["modis_status"] = merged["modis_status"].fillna("file_not_available")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output_path, index=False)
    print(f"Merged dataset: {output_path} ({len(merged)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Single .nc file OR downloaded .nc directory")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Station-day cloud CSV")
    parser.add_argument("--stations", nargs="+", choices=STATIONS.keys(), default=list(STATIONS), help="SURFRAD station IDs")
    parser.add_argument("--start", help="Optional inclusive YYYY-MM-DD filter")
    parser.add_argument("--end", help="Optional inclusive YYYY-MM-DD filter")
    parser.add_argument("--min-pixels", type=int, default=1, help="Minimum valid contributing MODIS observations (default: 1)")
    parser.add_argument("--merge-master", type=Path, help="Optional path to NOAA master_station_days.csv")
    parser.add_argument("--merge-output", type=Path, default=ROOT / "data/processed/master_station_days_with_cloud.csv")
    args = parser.parse_args()
    if args.min_pixels < 1:
        parser.error("--min-pixels must be at least 1")
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None
    if start and end and start > end:
        parser.error("--start must be <= --end")

    files = files_to_process(args.input, start, end)
    if not files:
        raise SystemExit(f"No {PRODUCT} .nc files found for the requested range in {args.input}")
    print(f"Found {len(files)} day files in {args.input}")
    all_rows = []
    bad_files = []
    for i, (day, path) in enumerate(files, start=1):
        try:
            all_rows.extend(extract_file(path, args.stations, min_pixels=args.min_pixels))
        except (OSError, KeyError, ValueError) as exc:
            bad_files.append((path.name, str(exc)))
            print(f"WARNING: Could not read {path.name}: {exc}")
        if i == 1 or i % 50 == 0 or i == len(files):
            print(f"Processed {i}/{len(files)} daily files")
    if not all_rows:
        raise SystemExit("No usable MODIS files were processed. Check the errors above.")

    data = pd.DataFrame(all_rows).sort_values(["date", "station"])
    if data.duplicated(["date", "station"]).any():
        raise RuntimeError("Duplicate date/station keys; check NASA filenames")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(args.output, index=False)
    print(f"Saved {len(data)} station-days to {args.output}")
    print(f"Valid fractions: {data['cloud_fraction'].notna().sum()} / {len(data)}")
    print(data[["date", "station", "cloud_fraction", "modis_pixel_count", "modis_status"]].head(12).to_string(index=False))
    if start is not None and end is not None:
        expected = set(pd.date_range(start, end).strftime("%Y-%m-%d"))
        received = set(data["date"])
        missing = sorted(expected - received)
        if missing:
            print(f"WARNING: Missing files for {len(missing)} requested dates: {', '.join(missing[:12])}" + (" ..." if len(missing) > 12 else ""))
    if bad_files:
        print(f"WARNING: {len(bad_files)} downloaded files could not be processed. Output is partial.")
    if args.merge_master:
        merge_master(args.merge_master, data, args.merge_output)


if __name__ == "__main__":
    main()
