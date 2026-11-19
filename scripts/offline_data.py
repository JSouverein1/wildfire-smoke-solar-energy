"""Read already-produced daily CSVs/JSON caches only; deliberately no HTTP code.

Shared utilities for scripts/plot_offline_scatter.py and scripts/verify_september_tbl.py.
A local cache record takes precedence over a master CSV value if both exist,
so a later short test run cannot hide previously cached study years.
"""
from __future__ import annotations
from calendar import monthrange
from datetime import date
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STATION_NAMES = {
    'tbl': 'Table Mountain, Colorado',
    'fpk': 'Fort Peck, Montana',
    'dra': 'Desert Rock, Nevada',
    'bon': 'Bondville, Illinois',
}
METRICS = {'ghi_kwh_m2': 'GHI', 'dni_kwh_m2': 'DNI', 'dhi_kwh_m2': 'DHI'}
NUMERIC = [
    'smoke_present', 'cloud_fraction', 'modis_pixel_count',
    'ghi_kwh_m2', 'dni_kwh_m2', 'dhi_kwh_m2',
    'ghi_coverage', 'dni_coverage', 'dhi_coverage',
    'solar_extraterrestrial_kwh_m2', 'clearness_index',
]


def _dates(start_year: int, end_year: int, months: list[int]):
    if not (2005 <= start_year <= end_year <= 2026):
        raise ValueError('Years must be in the range 2005 through 2026, start <= end')
    for m in months:
        if m < 1 or m > 12:
            raise ValueError(f'Invalid month: {m}')
    for yr in range(start_year, end_year+1):
        for mon in sorted(set(months)):
            for d in range(1, monthrange(yr, mon)[1]+1):
                yield date(yr, mon, d)


def _json(path):
    if not path.is_file():
        return None
    try:
        with path.open(encoding='utf-8') as fh:
            return json.load(fh)
    except (ValueError, OSError):
        return None


def _local_cache_records(root: Path, start_year: int, end_year: int,
                         months: list[int], stations: list[str]) -> pd.DataFrame:
    """Use local cache only; absent records are unspecified, never zero values."""
    cache = root / 'data' / 'cache'
    rows = []
    for d in _dates(start_year, end_year, months):
        day = d.isoformat()
        hms = _json(cache / 'hms' / str(d.year) / f'{day}.json') or {}
        modis = _json(cache / 'modis' / str(d.year) / f'{day}.json') or {}
        for station in stations:
            item = {'date': day, 'station': station}
            for parent in (hms, modis):
                station_item = parent.get('stations', {}).get(station)
                if isinstance(station_item, dict):
                    item.update(station_item)
            surfrad = _json(cache / 'surfrad' / str(d.year) / station / f'{day}.json')
            if isinstance(surfrad, dict):
                item.update(surfrad)
            item['date'] = day
            item['station'] = station
            rows.append(item)
    return pd.DataFrame(rows)


def read_local_study(*, root: Path = ROOT, start_year: int = 2005,
                     end_year: int = 2025, months=(6, 7, 8, 9, 10),
                     stations=('tbl', 'fpk', 'dra', 'bon'), source: str = 'auto') -> pd.DataFrame:
    """Load local station-days without downloading or modifying source data.

    source='auto' overlays JSON caches onto the existing master CSV and uses
    whichever is present. source='cache' and source='master' restrict inputs.
    """
    root = Path(root)
    stations = list(dict.fromkeys(s.lower() for s in stations))
    invalid = set(stations) - set(STATION_NAMES)
    if invalid:
        raise ValueError(f'Unknown station(s): {sorted(invalid)}')
    valid_dates = pd.DatetimeIndex(pd.to_datetime(list(_dates(start_year, end_year, list(months)))))
    master_file = root / 'data' / 'processed' / 'master_station_days.csv'
    cache_dir = root / 'data' / 'cache'
    if source not in ('auto', 'master', 'cache'):
        raise ValueError('--source must be auto, master, or cache')
    has_cache = cache_dir.exists() and any((cache_dir / kind).exists() for kind in ('hms', 'modis', 'surfrad'))
    has_master = master_file.is_file()
    if not ((has_master and source != 'cache') or (has_cache and source != 'master')):
        raise FileNotFoundError(
            f'No local study data found at {master_file} or {cache_dir}. '
            'Run from the original downloaded-data project directory, not a newly extracted empty copy.'
        )
    frames = []
    if has_master and source in ('auto', 'master'):
        master = pd.read_csv(master_file, low_memory=False)
        necessary = {'date', 'station'}
        if not necessary.issubset(master.columns):
            raise ValueError(f'{master_file} needs date and station columns')
        master['date'] = pd.to_datetime(master['date'], errors='coerce')
        master['station'] = master['station'].astype(str).str.lower().str.strip()
        master = master[master['date'].isin(valid_dates) & master['station'].isin(stations)].copy()
        master['date'] = master['date'].dt.strftime('%Y-%m-%d')
        if master.duplicated(['date', 'station']).any():
            raise ValueError('Duplicate date/station rows in master_station_days.csv')
        frames.append(master.set_index(['date', 'station']))
    if has_cache and source in ('auto', 'cache'):
        cache_frame = _local_cache_records(root, start_year, end_year, list(months), stations)
        cache_frame = cache_frame.set_index(['date', 'station'])
        if source == 'cache' and not any(x in cache_frame.columns for x in ('ghi_kwh_m2', 'cloud_fraction')):
            raise ValueError('Cache folders exist, but no cached measurements were found for selected dates')
        # JSON cache is primary; master supplies columns/records missing from cache.
        frames.insert(0, cache_frame)
    if not frames:
        raise ValueError('No local records for selected dates')
    combined = frames[0]
    for frame in frames[1:]:
        combined = combined.combine_first(frame)
    combined = combined.reset_index()
    combined['date'] = pd.to_datetime(combined['date'])
    combined['station'] = combined['station'].astype(str)
    for col in NUMERIC:
        if col not in combined:
            combined[col] = np.nan
        combined[col] = pd.to_numeric(combined[col], errors='coerce')
    for col in ('hms_status', 'surfrad_status', 'modis_status'):
        if col not in combined:
            combined[col] = 'not_processed'
        combined[col] = combined[col].fillna('not_processed').astype(str)
    combined['year'] = combined['date'].dt.year
    combined['month'] = combined['date'].dt.month
    combined['day'] = combined['date'].dt.day
    return combined.sort_values(['station', 'date']).reset_index(drop=True)


def quality_flags(df: pd.DataFrame, *, max_cloud: float = 0.10,
                  min_coverage: float = 0.98, min_pixels: int = 1) -> pd.DataFrame:
    """Add auditable QC and cloud-screening flags, without deleting rows.

    This cloud screen is independent of irradiance. Thick smoke can still be
    confused with cloud by MODIS; screen is observational, not causal.
    """
    if not 0 <= max_cloud <= 1:
        raise ValueError('max_cloud must be 0..1')
    if not 0 <= min_coverage <= 1:
        raise ValueError('min_coverage must be 0..1')
    if min_pixels < 1:
        raise ValueError('min_pixels must be >= 1')
    df = df.copy()
    values = list(METRICS)
    available = df[values].notna().all(axis=1) & df[values].ge(0).all(axis=1)
    coverage = df[['ghi_coverage', 'dni_coverage', 'dhi_coverage']].ge(min_coverage).all(axis=1)
    df['radiation_ok'] = df['surfrad_status'].eq('ok') & available & coverage
    df['cloud_ok'] = (
        df['modis_status'].eq('ok') &
        df['cloud_fraction'].between(0, max_cloud, inclusive='both') &
        df['modis_pixel_count'].ge(min_pixels)
    )
    df['smoke_known'] = df['hms_status'].eq('ok') & df['smoke_present'].isin([0, 1])
    # Loose physical QC screens for daily totals; flag rather than modifying data.
    ghi, dhi = df['ghi_kwh_m2'], df['dhi_kwh_m2']
    toa = df['solar_extraterrestrial_kwh_m2']
    df['flag_diffuse_gt_global'] = ghi.notna() & dhi.notna() & (dhi > ghi + 0.10)
    df['flag_global_gt_toa'] = ghi.notna() & toa.gt(0) & (ghi > 1.10 * toa)
    df['flag_review'] = df['flag_diffuse_gt_global'] | df['flag_global_gt_toa']
    df['use_for_scatter'] = df['radiation_ok'] & df['cloud_ok'] & df['smoke_known'] & ~df['flag_review']

    def reason(row):
        failed = []
        if not row['radiation_ok']:
            failed.append('radiation_missing_or_low_quality')
        if not row['cloud_ok']:
            failed.append('cloudy_or_cloud_data_missing')
        if not row['smoke_known']:
            failed.append('smoke_status_unknown')
        if row['flag_review']:
            failed.append('radiation_physical_check')
        return ';'.join(failed) if failed else ''

    df['exclusion_reason'] = df.apply(reason, axis=1)
    return df
