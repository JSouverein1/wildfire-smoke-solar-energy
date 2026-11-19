from datetime import date
from pathlib import Path
import math
import zipfile
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon
from settings import date_range, STATIONS
from hms import density_name, load_zip
from surfrad import COLUMNS, cos_zenith, summarize
from analysis import comparison, assemble
from extract_modis_cosp_cloud import acquisition_date, extract_file
from utils import save_record, get_record
import settings, analysis


def test_days_months_years():
    days=list(date_range(2005,2025))
    assert len(days)==21*153
    assert days[0]==date(2005,6,1)
    assert days[-1]==date(2025,10,31)
    assert all(6<=x.month<=10 for x in days)
    assert len(list(date_range(2020,2020,[9])))==30
    assert all(x.month!=11 for x in days)


def test_density_and_date():
    assert density_name('21')=='heavy'
    assert density_name('Unspecified')=='unknown'
    assert density_name('5')=='light'
    assert acquisition_date('MCD06COSP_D3_MODIS.A2020245.062.2022124005036.nc')==date(2020,9,1)


def test_hms_zip_polygon(tmp_path):
    df=gpd.GeoDataFrame({'Density':['Heavy']},geometry=[Polygon([(-106,40),(-104,40),(-104,41),(-106,41)])],crs='EPSG:4326')
    p=tmp_path/'hms_smoke20200901'
    p.mkdir()
    shp=p/'sample.shp'
    df.to_file(shp)
    z=tmp_path/'test.zip'
    with zipfile.ZipFile(z,'w') as f:
        for each in p.iterdir():f.write(each,arcname=each.name)
    frame=load_zip(z)
    from shapely.geometry import Point
    assert frame.geometry.intersects(Point(STATIONS['tbl']['lon'],STATIONS['tbl']['lat'])).any()
    assert not frame.geometry.intersects(Point(STATIONS['bon']['lon'],STATIONS['bon']['lat'])).any()


def write_surfrad_synthetic(file, day, station, cadence):
    m=np.arange(0,1440,cadence)
    cosine=cos_zenith(day,m,STATIONS[station]['lat'],STATIONS[station]['lon'])
    rows=[]
    for mm,cz in zip(m,cosine):
        data={c:0 for c in COLUMNS}
        data.update(year=day.year,jday=day.timetuple().tm_yday,month=day.month,day=day.day,
                    hour=mm//60,minute=mm%60,dt=(mm//60)+(mm%60)/60,
                    zen=float(np.rad2deg(np.arccos(np.clip(cz,-1,1)))))
        if cz>np.cos(np.deg2rad(85)):
            data['dw_solar']=650
            data['direct_n']=700
            data['diffuse']=120
        rows.append(' '.join(str(data[c]) for c in COLUMNS))
    file.write_text('Test Station\n40 -105 1600 1\n'+'\n'.join(rows),encoding='utf8')


def test_surfrad_one_and_three_minutes(tmp_path):
    for year,cadence in [(2005,3),(2020,1)]:
        day=date(year,9,1)
        path=tmp_path/f'synthetic_{year}.dat'
        write_surfrad_synthetic(path,day,'tbl',cadence)
        row=summarize(path,day,'tbl')
        assert row['surfrad_status']=='ok'
        assert row['ghi_coverage']>=0.98
        assert row['ghi_kwh_m2']>0
        assert 0<row['clearness_index']<1


def test_comparison_with_cloud_filter():
    df=pd.DataFrame([
        {'date':'2020-09-08','station':'tbl','year':2020,'month':9,'hms_status':'ok','surfrad_status':'ok','smoke_present':1,'cloud_fraction':0.03,'ghi_kwh_m2':4,'dni_kwh_m2':3,'dhi_kwh_m2':1,'clearness_index':0.6,'diffuse_fraction':0.25},
        {'date':'2020-09-09','station':'tbl','year':2020,'month':9,'hms_status':'ok','surfrad_status':'ok','smoke_present':0,'cloud_fraction':0.05,'ghi_kwh_m2':5,'dni_kwh_m2':5,'dhi_kwh_m2':1,'clearness_index':0.8,'diffuse_fraction':0.2},
        {'date':'2020-09-10','station':'tbl','year':2020,'month':9,'hms_status':'ok','surfrad_status':'ok','smoke_present':0,'cloud_fraction':0.50,'ghi_kwh_m2':2,'dni_kwh_m2':1,'dhi_kwh_m2':1,'clearness_index':0.3,'diffuse_fraction':0.5},
    ])
    screened,summary=comparison(df,0.10)
    assert len(screened)==2
    result=summary[summary['metric']=='ghi_kwh_m2'].iloc[0]
    assert math.isclose(result['percent_difference'],-20)


def test_merge_preserves_missing(tmp_path,monkeypatch):
    monkeypatch.setattr(analysis,'PROCESSED',tmp_path/'out')
    monkeypatch.setattr(settings,'CACHE',tmp_path/'cache')
    # cache_path is imported into analysis; point directly to temporary path
    def temp_cache(source,day,station=None):
        p=tmp_path/'cache'/source/str(day.year)
        if station:p=p/station
        return p/f'{day.isoformat()}.json'
    monkeypatch.setattr(analysis,'cache_path',temp_cache)
    day=date(2020,9,1)
    save_record(temp_cache('hms',day),{'stations':{'tbl':{'date':day.isoformat(),'station':'tbl','smoke_present':None,'hms_status':'http_404'}}})
    save_record(temp_cache('modis',day),{'stations':{'tbl':{'date':day.isoformat(),'station':'tbl','cloud_fraction':0.05,'modis_status':'ok'}}})
    out=assemble([day],['tbl'])
    assert pd.isna(out.loc[0,'smoke_present'])
    assert out.loc[0,'hms_status']=='http_404'
    assert out.loc[0,'cloud_fraction']==0.05


def test_real_uploaded_modis_file_if_available():
    path=Path('/mnt/data/MCD06COSP_D3_MODIS.A2020245.062.2022124005036.nc')
    if path.exists():
        rows=extract_file(path,list(STATIONS))
        found={r['station']:r for r in rows}
        assert abs(found['tbl']['cloud_fraction']-0.0518)<0.001
        assert found['tbl']['modis_pixel_count']>0
        assert found['bon']['cloud_fraction']==1.0
