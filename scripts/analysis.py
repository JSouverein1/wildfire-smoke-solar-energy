"""Assemble source caches, apply cloud screening and create descriptive figures.

Daily quantities refer to UTC calendar days, not local clock days.
"""
from __future__ import annotations
import math
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from settings import PROCESSED, FIGURES, cache_path
from utils import get_record


def assemble(days, stations):
    """One row per requested UTC station/day, with explicit missing-status columns."""
    all_rows=[]
    for day in days:
        hms_rec = get_record(cache_path('hms',day))
        modis_rec = get_record(cache_path('modis',day))
        for station in stations:
            row={'date':day.isoformat(),'year':day.year,'month':day.month,'station':station,
                 'smoke_present':None,'smoke_density':'unknown','smoke_polygon_count':None,
                 'hms_status':'not_processed','surfrad_status':'not_processed',
                 'modis_status':'not_processed','cloud_fraction':None,
                 'modis_pixel_count':None}
            if hms_rec and station in hms_rec.get('stations',{}):
                row.update(hms_rec['stations'][station])
            rad = get_record(cache_path('surfrad',day,station))
            if rad:
                row.update(rad)
            if modis_rec and station in modis_rec.get('stations',{}):
                row.update(modis_rec['stations'][station])
            all_rows.append(row)
    frame=pd.DataFrame(all_rows).sort_values(['date','station']).reset_index(drop=True)
    if frame.duplicated(['date','station']).any():
        raise RuntimeError('Duplicate station/date keys in combined data')
    PROCESSED.mkdir(parents=True,exist_ok=True)
    frame.to_csv(PROCESSED/'master_station_days.csv',index=False)
    frame[['date','station','smoke_present','smoke_density','hms_status','smoke_polygon_count']].to_csv(
        PROCESSED/'smoke_days.csv', index=False)
    rad_cols=['date','station','surfrad_status']+[x for x in ['ghi_kwh_m2','dni_kwh_m2',
        'dhi_kwh_m2','ghi_coverage','dni_coverage','dhi_coverage','clearness_index',
        'diffuse_fraction'] if x in frame]
    frame[rad_cols].to_csv(PROCESSED/'surfrad_daily.csv',index=False)
    frame[['date','station','cloud_fraction','modis_pixel_count','modis_status']].to_csv(
        PROCESSED/'cloud_fraction.csv',index=False)
    return frame


def comparison(master, max_cloud=0.10):
    """Monthly-matched smoke-vs-nonsmoke descriptive comparison.
    No causal inference; coarse satellite cloud fraction does not rule out smoke/cloud confusion.
    """
    work=master.copy()
    for field in ['cloud_fraction','smoke_present','ghi_kwh_m2','dni_kwh_m2',
                  'dhi_kwh_m2','clearness_index','diffuse_fraction']:
        if field not in work.columns: work[field]=np.nan
        work[field]=pd.to_numeric(work[field],errors='coerce')
    work=work[work['cloud_fraction'].between(0,max_cloud, inclusive='both') &
              work['smoke_present'].isin([0,1]) &
              work['surfrad_status'].eq('ok')].copy()
    summary=[]
    for keys,g in work.groupby(['station','year','month']):
        for metric in ['ghi_kwh_m2','dni_kwh_m2','dhi_kwh_m2','clearness_index','diffuse_fraction']:
            smoke=g.loc[g['smoke_present']==1,metric].dropna()
            clear=g.loc[g['smoke_present']==0,metric].dropna()
            if len(smoke)==0 or len(clear)==0: continue
            m1=float(smoke.mean());m0=float(clear.mean())
            summary.append({'station':keys[0],'year':keys[1],'month':keys[2],
                            'metric':metric,'n_smoke':len(smoke),'n_no_smoke':len(clear),
                            'smoke_mean':m1,'no_smoke_mean':m0,
                            'percent_difference':100*(m1/m0-1) if m0>0 else np.nan})
    return work,pd.DataFrame(summary,columns=['station','year','month','metric','n_smoke','n_no_smoke',
                                            'smoke_mean','no_smoke_mean','percent_difference'])


def save_figure(fig, name):
    FIGURES.mkdir(parents=True,exist_ok=True)
    fig.tight_layout()
    fig.savefig(FIGURES/name,dpi=170,bbox_inches='tight')
    plt.close(fig)


def analyze(master, max_cloud=0.10):
    PROCESSED.mkdir(parents=True,exist_ok=True)
    FIGURES.mkdir(parents=True,exist_ok=True)
    master=master.copy()
    master['smoke_present']=pd.to_numeric(master['smoke_present'],errors='coerce')
    valid=master[(master['hms_status']=='ok') & master['smoke_present'].isin([0,1])]
    annual=valid.groupby(['station','year']).agg(n_detected_smoke_days=('smoke_present','sum'),
                                               n_valid_hms_days=('smoke_present','size')).reset_index()
    # Count requested calendar days from master rather than assuming 153 (partial date filters).
    total=master.groupby(['station','year']).size().rename('n_requested_days').reset_index()
    annual=total.merge(annual,on=['station','year'],how='left')
    annual['hms_coverage']=annual['n_valid_hms_days']/annual['n_requested_days']
    annual['smoke_day_fraction']=annual['n_detected_smoke_days']/annual['n_valid_hms_days']
    # 2005 has substantial missing HMS coverage before August 5; do not use it in main trend.
    annual['trend_eligible']=(annual['hms_coverage']>=0.90)&(annual['year']>2005)
    annual.to_csv(PROCESSED/'annual_smoke_frequency.csv',index=False)
    fig,ax=plt.subplots(figsize=(10,5))
    usable=annual[annual['trend_eligible']]
    for station,g in usable.groupby('station'):
        ax.plot(g['year'], 100*g['smoke_day_fraction'],marker='o',markersize=3,label=station.upper())
    ax.set(xlabel='Year',ylabel='Days with HMS-detected smoke (% of valid days)',
           title='June–October smoke frequency (only years with ≥90% HMS coverage)')
    if not usable.empty: ax.legend()
    save_figure(fig,'annual_smoke_frequency.png')

    screened, summary=comparison(master,max_cloud)
    screened.to_csv(PROCESSED/'cloud_filtered_station_days.csv',index=False)
    summary.to_csv(PROCESSED/'matched_smoke_comparison.csv',index=False)
    fig,axes=plt.subplots(1,2,figsize=(11,4.5))
    for ax,metric,label in zip(axes,['ghi_kwh_m2','dni_kwh_m2'],['GHI','DNI']):
        if metric not in screened: continue
        clean=screened[[metric,'smoke_present']].dropna()
        arr=[clean.loc[clean.smoke_present==k,metric].to_numpy() for k in (0,1)]
        if all(len(a)>0 for a in arr):
            ax.boxplot(arr, tick_labels=['No smoke detected','HMS smoke'],showfliers=False)
        ax.set(ylabel='Daily irradiation (kWh/m²)',title=f'{label}, cloud fraction ≤{max_cloud:.2f}')
    save_figure(fig,'cloud_filtered_irradiation_boxplots.png')

    fig,ax=plt.subplots(figsize=(10,4.5))
    selected=summary[(summary.metric=='clearness_index') & summary.percent_difference.notna()]
    for station,g in selected.groupby('station'):
        ax.scatter(g['year']+(g['month']-0.5)/12,g['percent_difference'],label=station.upper(),alpha=0.7,s=24)
    ax.axhline(0,color='black',linewidth=0.8)
    ax.set(xlabel='Year',ylabel='Monthly matched smoke vs non-smoke difference (%)',
           title='Clearness index difference in low-cloud station-months (descriptive)')
    if not selected.empty:ax.legend()
    save_figure(fig,'matched_clearness_index.png')

    # September 2020 physical validation: all available days, including cloudy days.
    for station in master['station'].unique():
        part=master[(master['station']==station)&(master['date'].between('2020-09-01','2020-09-30'))].copy()
        if part.empty: continue
        part['date']=pd.to_datetime(part['date'])
        fig,ax=plt.subplots(figsize=(10,4))
        for var,label in [('ghi_kwh_m2','GHI'),('dni_kwh_m2','DNI')]:
            if var in part:
                ax.plot(part['date'],pd.to_numeric(part[var],errors='coerce'),'-o',ms=3,label=label)
        for dt in part.loc[part.smoke_present==1,'date']:
            ax.axvspan(dt-pd.Timedelta(hours=12),dt+pd.Timedelta(hours=12),color='gray',alpha=0.15)
        ax.set(xlabel='UTC date',ylabel='Daily irradiation (kWh/m²)',
               title=f'{station.upper()}: September 2020 (gray = HMS smoke detected)')
        handles, labels = ax.get_legend_handles_labels()
        if handles: ax.legend()
        fig.autofmt_xdate()
        save_figure(fig,f'validation_sep2020_{station}.png')
    print(f'Merged {len(master):,} station-days; {len(screened):,} have low-cloud valid radiation; '
          f'{len(summary):,} matched station-month comparisons.',flush=True)
    return annual,summary
