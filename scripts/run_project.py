"""One-command, resumable June–October wildfire-smoke/solar project.

Examples:
    python scripts/run_project.py --start-year 2020 --end-year 2020 --months 9
    python scripts/run_project.py --start-year 2005 --end-year 2025
    python scripts/run_project.py --steps hms surfrad merge analyze
    python scripts/run_project.py --steps modis merge analyze --start-year 2020 --end-year 2020

All data are grouped by UTC calendar day. Downloads require an internet
connection and an active NASA Earthdata authorization token for MODIS.
"""
from __future__ import annotations
import argparse
import getpass
import os
import re
from pathlib import Path
import pandas as pd
from settings import RAW, PROCESSED, FIGURES, STATIONS, DEFAULT_MONTHS, date_range, cache_path
from utils import get_record, save_record, session_with_retries
from hms import process_hms
from surfrad import process_surfrad
from analysis import assemble, analyze
from download_laads_cosp import fetch_day, PRODUCT
from extract_modis_cosp_cloud import extract_file

STEPS = ['hms','surfrad','modis','merge','analyze']


def process_modis(day, stations, session, token, *, method='auto', keep_raw=False, retry_errors=False,
                  min_pixels=1):
    """Download one MODIS global file, immediately extract station cells and optionally delete it."""
    cached_path = cache_path('modis', day)
    previous = get_record(cached_path)
    if previous and set(stations).issubset(previous.get('stations',{})):
        if (not retry_errors or previous.get('download_status') == 'ok'):
            return [previous['stations'][st] for st in stations]

    folder = RAW / 'modis_cosp'
    folder.mkdir(parents=True,exist_ok=True)
    files = sorted(folder.glob(f'{PRODUCT}.A{day.year}{day.timetuple().tm_yday:03d}.*.nc'))
    status = 'ok'
    if not files:
        try:
            found=fetch_day(session,day,folder,token,method)
            status='ok' if found else 'file_not_available'
        except Exception as exc:
            print(f'  MODIS warning {day}: {type(exc).__name__}: {exc}',flush=True)
            status='download_error'
        files=sorted(folder.glob(f'{PRODUCT}.A{day.year}{day.timetuple().tm_yday:03d}.*.nc'))
    if files:
        path=files[-1]
        try:
            rows=extract_file(path,stations,min_pixels=min_pixels)
            entries={r['station']:r for r in rows}
            status='ok'
        except (OSError,KeyError,ValueError) as exc:
            print(f'  MODIS extraction warning {day}: {exc}',flush=True)
            status='parse_error'
            entries={}
    else:
        entries={}
    if status!='ok':
        entries={station:{'date':day.isoformat(),'station':station,
                            'cloud_fraction':None,'modis_pixel_count':None,
                            'modis_status':status,'modis_product':PRODUCT}
                 for station in stations}
    # Only remove files after correctly extracting and atomically caching the values.
    save_record(cached_path,{'download_status':status,'stations':entries})
    if status=='ok' and not keep_raw:
        for nc in files:
            nc.unlink(missing_ok=True)
    return [entries[x] for x in stations]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--start-year',type=int,default=2005)
    parser.add_argument('--end-year',type=int,default=2025)
    parser.add_argument('--months',type=int,nargs='+',default=list(DEFAULT_MONTHS),
                        help='Month numbers, default: 6 7 8 9 10')
    parser.add_argument('--stations',nargs='+',choices=sorted(STATIONS),default=list(STATIONS))
    parser.add_argument('--steps',nargs='+',choices=STEPS,default=STEPS,
                        help='Subset of stages, default: hms surfrad modis merge analyze')
    parser.add_argument('--max-cloud',type=float,default=0.10)
    parser.add_argument('--min-modis-pixels',type=int,default=1)
    parser.add_argument('--keep-modis',action='store_true',help='Retain ~40-50MB daily NetCDF files')
    parser.add_argument('--retry-errors',action='store_true',
                        help='Recheck missing and failed downloads, not only uncached dates')
    parser.add_argument('--modis-method',choices=['auto','requests','curl'],default='auto')
    parser.add_argument('--dry-run',action='store_true',help='Print workload without requesting data')
    args=parser.parse_args(argv)
    if args.start_year<2005 or args.end_year>2026:
        parser.error('Year range must be between 2005 and 2026 for this project')
    if not (0<=args.max_cloud<=1):parser.error('--max-cloud must be between 0 and 1')
    if args.min_modis_pixels<1:parser.error('--min-modis-pixels must be >= 1')
    days=list(date_range(args.start_year,args.end_year,args.months))
    stations=list(dict.fromkeys(args.stations))
    print(f'Period {days[0]} to {days[-1]} (months {sorted(set(args.months))})')
    print(f'{len(days):,} UTC days x {len(stations)} stations = {len(days)*len(stations):,} station-days')
    print('Stages:',', '.join(args.steps),flush=True)
    if args.dry_run:return 0
    for d in (RAW,PROCESSED,FIGURES):d.mkdir(parents=True,exist_ok=True)
    session=session_with_retries()
    for stage in STEPS:
        if stage not in args.steps:continue
        print(f'\n=== {stage.upper()} ===',flush=True)
        if stage=='hms':
            for idx,day in enumerate(days,1):
                if idx==1 or idx%15==0 or idx==len(days):
                    print(f'HMS {idx}/{len(days)}: {day}',flush=True)
                process_hms(day,stations,session,retry_errors=args.retry_errors)
        elif stage=='surfrad':
            for idx,day in enumerate(days,1):
                if idx==1 or idx%15==0 or idx==len(days):
                    print(f'SURFRAD {idx}/{len(days)}: {day}',flush=True)
                for st in stations:
                    process_surfrad(day,st,session,retry_errors=args.retry_errors)
        elif stage=='modis':
            pending=[]
            for day in days:
                prior=get_record(cache_path('modis',day))
                if not prior or not set(stations).issubset(prior.get('stations',{})) or (
                    args.retry_errors and prior.get('download_status')!='ok'):
                    pending.append(day)
            print(f'MODIS: {len(pending)} dates need processing; {len(days)-len(pending)} dates cached',flush=True)
            if pending:
                token=(os.environ.get('EARTHDATA_TOKEN') or getpass.getpass('New Earthdata token: ')).strip()
                if not re.fullmatch(r'[A-Za-z0-9._-]+',token):
                    raise SystemExit('Invalid token characters. Never paste the token into a chat or GitHub.')
                session.headers.update({'Authorization':f'Bearer {token}'})
                fail_count=0
                for idx,day in enumerate(pending,1):
                    if idx==1 or idx%10==0 or idx==len(pending):
                        print(f'MODIS {idx}/{len(pending)}: {day}',flush=True)
                    record=process_modis(day,stations,session,token,method=args.modis_method,
                        keep_raw=args.keep_modis,retry_errors=args.retry_errors,
                        min_pixels=args.min_modis_pixels)
                    if all(x['modis_status'] in ('download_error','parse_error') for x in record):
                        fail_count+=1
                    else:fail_count=0
                    if fail_count>=3:
                        raise SystemExit('Three successive MODIS failures. Check NASA authorization/network; '
                                         'partial data are cached and future runs resume.')
                session.headers.pop('Authorization',None)
        elif stage=='merge':
            result=assemble(days,stations)
            print('Wrote data/processed/master_station_days.csv and three source CSVs',flush=True)
        elif stage=='analyze':
            if 'merge' in args.steps:
                master=result
            else:
                file=PROCESSED/'master_station_days.csv'
                if not file.exists():raise SystemExit('Missing master CSV. Run --steps merge analyze first.')
                master=pd.read_csv(file)
                master=master[master['date'].isin([d.isoformat() for d in days]) &
                              master['station'].isin(stations)]
            analyze(master,max_cloud=args.max_cloud)
            print('Figures saved to figures/; summaries to data/processed/',flush=True)
    print('\nFinished requested stages. Re-run the same command to resume/refresh outputs.',flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
