"""NOAA HMS daily smoke-polygon station classification."""
from __future__ import annotations
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile, BadZipFile
import geopandas as gpd
from shapely.geometry import Point
from settings import RAW, HMS_URL, HMS_FIRST_DATE, STATIONS, cache_path
from utils import download, get_record, save_record

DENSITY_SCORE = {'none':0, 'light':1, 'medium':2, 'heavy':3, 'unknown':-1}

def density_name(x):
    s = str(x).strip().lower()
    return {'5':'light','16':'medium','21':'heavy','l':'light','m':'medium','h':'heavy',
            'unspecified':'unknown','nan':'unknown','none':'unknown'}.get(s, s if s in DENSITY_SCORE else 'unknown')


def load_zip(path):
    """Read NOAA HMS zip; safe local extraction of the original shapefile."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        with ZipFile(path) as z:
            shp_files = [name for name in z.namelist() if name.lower().endswith('.shp')]
            if not shp_files:
                raise ValueError('No .shp in archive')
            for member in z.infolist():
                target = (root / member.filename).resolve()
                if not target.is_relative_to(root.resolve()):
                    raise ValueError('Unsafe path inside ZIP')
            z.extractall(root)
        frame = gpd.read_file(root / shp_files[0])
    if frame.crs is None:
        raise ValueError('Smoke shape file has no CRS; no coordinate assumptions made')
    return frame.to_crs('EPSG:4326')


def process_hms(day, stations, session, *, retry_errors=False):
    cache = cache_path('hms', day)
    prior = get_record(cache)
    if prior is not None and (not retry_errors or prior.get('download_status') in ('ok','not_started')):
        if set(stations).issubset(prior.get('stations', {})):
            return [prior['stations'][code] for code in stations]

    raw = RAW / 'hms' / str(day.year) / f'hms_smoke{day:%Y%m%d}.zip'
    if day < HMS_FIRST_DATE:
        status = 'not_started'
        polygons = None
    else:
        url = f'{HMS_URL}/{day:%Y}/{day:%m}/hms_smoke{day:%Y%m%d}.zip'
        status = download(session, url, raw, kind='zip')
        polygons = None
        if status == 'ok':
            try:
                polygons = load_zip(raw)
                polygons.columns = [str(x).lower() for x in polygons.columns]
            except Exception as exc:
                print(f'  HMS parse warning {day}: {exc}', flush=True)
                status = 'parse_error'
    output = {}
    for code in stations:
        row = {'date':day.isoformat(), 'station':code, 'hms_status':status,
               'smoke_present':None, 'smoke_density':'unknown', 'smoke_polygon_count':None}
        if status == 'ok':
            pt = Point(STATIONS[code]['lon'], STATIONS[code]['lat'])
            hits = polygons.loc[polygons.geometry.intersects(pt)]
            row['smoke_polygon_count'] = len(hits)
            row['smoke_present'] = int(len(hits)>0)
            classes = [density_name(v) for v in hits['density']] if 'density' in hits else []
            row['smoke_density'] = (max(classes, key=lambda x:DENSITY_SCORE.get(x,-1))
                                    if classes else ('unknown' if len(hits) else 'none'))
        output[code] = row
    save_record(cache, {'download_status':status, 'stations':output})
    return [output[code] for code in stations]
