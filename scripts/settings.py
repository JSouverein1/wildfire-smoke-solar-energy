"""Single source of truth for location, date and archive settings."""
from pathlib import Path
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
CACHE = ROOT / 'data' / 'cache'
PROCESSED = ROOT / 'data' / 'processed'
FIGURES = ROOT / 'figures'
DEFAULT_MONTHS = (6, 7, 8, 9, 10)
HMS_FIRST_DATE = date(2005, 8, 5)  # first date in historical NOAA HMS smoke polygon collection
HMS_URL = 'https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Smoke_Polygons/Shapefile'
SURFRAD_URL = 'https://gml.noaa.gov/aftp/data/radiation/surfrad'
STATIONS = {
    'tbl': {'name':'Table Mountain, CO', 'lat':40.12498, 'lon':-105.23680, 'elevation_m':1689},
    'fpk': {'name':'Fort Peck, MT',     'lat':48.30783, 'lon':-105.10170, 'elevation_m':634},
    'dra': {'name':'Desert Rock, NV',  'lat':36.62373, 'lon':-116.01947, 'elevation_m':1007},
    'bon': {'name':'Bondville, IL',    'lat':40.05192, 'lon':-88.37309, 'elevation_m':213},
}

def date_range(start_year, end_year, months=DEFAULT_MONTHS):
    """Ordered inclusive dates, June–October by default, from each requested year."""
    if start_year > end_year: raise ValueError('Start year must not exceed end year')
    from calendar import monthrange
    for year in range(start_year, end_year + 1):
        for month in sorted(set(months)):
            if not 1 <= month <= 12: raise ValueError(f'Invalid month: {month}')
            for dd in range(1, monthrange(year, month)[1] + 1):
                yield date(year, month, dd)


def cache_path(source, day, station=None):
    base = CACHE / source / str(day.year)
    if station is not None:
        base = base / station
    return base / f'{day.isoformat()}.json'
