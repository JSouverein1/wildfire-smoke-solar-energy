"""NOAA SURFRAD file acquisition, QC and daily irradiation calculations.

Uses source columns as documented by NOAA and pvlib. No pvlib dependency:
solar geometry for expected sample coverage uses an approximate NOAA formula.
"""
from __future__ import annotations
from datetime import date
import math
import numpy as np
import pandas as pd
from settings import RAW, SURFRAD_URL, STATIONS, cache_path
from utils import download, get_record, save_record

COLUMNS = [
 'year','jday','month','day','hour','minute','dt','zen',
 'dw_solar','dw_solar_flag','uw_solar','uw_solar_flag','direct_n',
 'direct_n_flag','diffuse','diffuse_flag','dw_ir','dw_ir_flag',
 'dw_casetemp','dw_casetemp_flag','dw_dometemp','dw_dometemp_flag',
 'uw_ir','uw_ir_flag','uw_casetemp','uw_casetemp_flag','uw_dometemp',
 'uw_dometemp_flag','uvb','uvb_flag','par','par_flag','netsolar',
 'netsolar_flag','netir','netir_flag','totalnet','totalnet_flag',
 'temp','temp_flag','rh','rh_flag','windspd','windspd_flag',
 'winddir','winddir_flag','pressure','pressure_flag'
]


def cos_zenith(day, minutes, latitude, longitude):
    """NOAA approximate solar geometry at UTC minute coordinates; used only for
    screening station coverage and extraterrestrial normalization, not as an
    observed cloud variable or a high-precision clear-sky model.
    """
    m = np.asarray(minutes, dtype=float)
    gamma = 2 * np.pi / 365 * (day.timetuple().tm_yday - 1 + (m/60 - 12)/24)
    eqtime = 229.18 * (0.000075 + 0.001868*np.cos(gamma)
             - 0.032077*np.sin(gamma) - 0.014615*np.cos(2*gamma)
             - 0.040849*np.sin(2*gamma))
    decl = (0.006918 - 0.399912*np.cos(gamma) + 0.070257*np.sin(gamma)
          - 0.006758*np.cos(2*gamma) + 0.000907*np.sin(2*gamma)
          - 0.002697*np.cos(3*gamma) + 0.00148*np.sin(3*gamma))
    hour_angle = np.deg2rad((m + eqtime + 4*longitude)/4 - 180)
    lat = np.deg2rad(latitude)
    return np.sin(lat)*np.sin(decl) + np.cos(lat)*np.cos(decl)*np.cos(hour_angle)


def read_surfrad(path):
    data = pd.read_csv(path, sep=r'\s+', skiprows=2, header=None,
                       names=COLUMNS, na_values=[-9999.9,-9999,-99999])
    if data.empty or len(data.columns) != len(COLUMNS):
        raise ValueError('Empty or unexpected SURFRAD file')
    for col in ('year','jday','month','day','hour','minute','zen','dw_solar','direct_n','diffuse'):
        data[col] = pd.to_numeric(data[col], errors='coerce')
    return data


def summarize(path, day, station, minimum_coverage=0.98):
    d = read_surfrad(path)
    sampling = 3 if day.year < 2009 else 1
    # NOAA changed to one-minute observations on January 1, 2009.
    # Estimate cadence from source if possible, overriding calendar default.
    t = pd.to_numeric(d['hour'],errors='coerce')*60 + pd.to_numeric(d['minute'],errors='coerce')
    dt = t.diff().dropna()
    dt = dt[(dt>0)&(dt<=10)]
    if len(dt):
        candidate = float(dt.median())
        if candidate in (1.,3.): sampling = int(candidate)
    # Use only actual calendar-day records with valid source times.
    d = d[(d['year']==day.year)&(d['month']==day.month)&(d['day']==day.day)].copy()
    if d.empty: raise ValueError('No entries for requested date')
    d['_minute'] = d['hour']*60+d['minute']
    d = d[d['_minute'].between(0, 1439)]
    d = d.drop_duplicates('_minute').sort_values('_minute')
    station_meta = STATIONS[station]
    minutes = np.arange(0,1440,sampling)
    cosine = cos_zenith(day, minutes, station_meta['lat'], station_meta['lon'])
    valid_day = cosine > np.cos(np.deg2rad(85))
    expected = max(int(valid_day.sum()),1)
    measured_zen = pd.to_numeric(d['zen'], errors='coerce')
    measured_sun = measured_zen.between(0,85)
    result = {
        'date':day.isoformat(), 'station':station, 'surfrad_status':'ok',
        'sampling_minutes':sampling,'valid_radiation_fraction':None,
        'ghi_coverage':None,'dni_coverage':None,'dhi_coverage':None,
        'ghi_kwh_m2':None,'dni_kwh_m2':None,'dhi_kwh_m2':None,
        'diffuse_fraction':None,'clearness_index':None,
        'solar_extraterrestrial_kwh_m2':None,
    }
    for old, new in [('dw_solar','ghi'), ('direct_n','dni'), ('diffuse','dhi')]:
        values = pd.to_numeric(d[old],errors='coerce')
        qc = pd.to_numeric(d[f'{old}_flag'],errors='coerce')
        # NOAA flags >0 indicate questionable data; ignore those samples.
        good = measured_sun & values.between(-10, 1500) & (qc==0)
        coverage = min(1.0, float(good.sum())/expected)
        result[f'{new}_coverage'] = round(coverage,4)
        # Use no extrapolation for missing observations; reject low coverage days.
        if coverage >= minimum_coverage:
            result[f'{new}_kwh_m2'] = float(values[good].clip(lower=0).sum()
                                                 * sampling / 60000)
    result['valid_radiation_fraction'] = min(result[f'{key}_coverage'] for key in ['ghi','dni','dhi'])
    ghi,dhi = result['ghi_kwh_m2'], result['dhi_kwh_m2']
    if ghi is not None and dhi is not None and ghi>0:
        result['diffuse_fraction'] = dhi/ghi
    # Extraterrestrial horizontal insolation = I0 * positive cos zenith.
    doy = day.timetuple().tm_yday
    e0 = 1361*(1+0.033*np.cos(2*np.pi*doy/365))
    ghi0 = float(np.clip(cosine,0,None).sum()*e0*sampling/60000)
    result['solar_extraterrestrial_kwh_m2'] = ghi0
    if ghi is not None and ghi0>0:
        result['clearness_index'] = ghi/ghi0
    if any(result[f'{key}_kwh_m2'] is None for key in ['ghi','dni','dhi']):
        result['surfrad_status']='low_coverage'
    return result


def process_surfrad(day, station, session, *, retry_errors=False, minimum_coverage=0.98):
    cpath = cache_path('surfrad', day, station)
    prior = get_record(cpath)
    if prior is not None and (not retry_errors or prior.get('surfrad_status') in ('ok','low_coverage')):
        return prior
    filename = f'{station}{day.year%100:02d}{day.timetuple().tm_yday:03d}.dat'
    url = f'{SURFRAD_URL}/{station}/{day.year}/{filename}'
    raw = RAW / 'surfrad' / station / str(day.year) / filename
    status = download(session, url, raw, kind='text')
    if status == 'ok':
        try:
            result = summarize(raw, day, station, minimum_coverage)
        except Exception as exc:
            print(f'  SURFRAD parse warning {station} {day}: {exc}',flush=True)
            status='parse_error'
    if status != 'ok':
        result = {'date':day.isoformat(),'station':station,'surfrad_status':status}
    save_record(cpath, result)
    return result
