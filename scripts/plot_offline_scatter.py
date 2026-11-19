"""Offline scatter plots of daily SURFRAD irradiance, colored by HMS smoke status.

NO downloading, no NASA login, no server requests.
Default: June-October 2005-2025, four stations, cloud fraction <=0.10.

  python scripts/plot_offline_scatter.py
  python scripts/plot_offline_scatter.py --max-cloud 0.01
  python scripts/plot_offline_scatter.py --start-year 2015 --end-year 2025 --stations tbl dra
  python scripts/plot_offline_scatter.py --years 2005 2010 2020 2025
"""
from __future__ import annotations
import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import pandas as pd
from offline_data import ROOT, STATION_NAMES, METRICS, read_local_study, quality_flags

COLORS = {0: '#587a91', 1: '#c3532b'}
LABELS = {0: 'No HMS smoke detected', 1: 'HMS smoke detected'}


def plot_one_station(frame, station, start_year, end_year, path, max_cloud):
    data = frame[(frame['station'] == station) & frame['use_for_scatter']].copy()
    fig, axes = plt.subplots(3, 1, figsize=(15, 10), sharex=True, constrained_layout=True)
    for ax, (col, label) in zip(axes, METRICS.items()):
        for smoke in (0, 1):
            subset = data[(data['smoke_present'] == smoke) & data[col].notna()]
            ax.scatter(subset['date'], subset[col], s=10 if smoke == 0 else 21,
                       c=COLORS[smoke], marker='o', alpha=.55 if smoke == 0 else .9,
                       edgecolors='none', rasterized=True, label=LABELS[smoke])
        ax.set_ylabel(f'Daily {label}\n(kWh/m²)')
        ax.set_ylim(bottom=0)
        ax.grid(True, alpha=.2)
    fig.suptitle(f'{STATION_NAMES[station]} | Daily measured irradiation, June–October {start_year}–{end_year}\n'
                 f'MODIS cloud fraction ≤ {max_cloud:.2f} | retained n={len(data):,} station-days', fontsize=14)
    axes[0].legend(loc='upper right', frameon=False)
    axes[-1].xaxis.set_major_locator(mdates.YearLocator(base=2))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    axes[-1].set_xlabel('UTC date')
    for ax in axes:
        ax.set_xlim(pd.Timestamp(f'{start_year}-01-01'), pd.Timestamp(f'{end_year}-12-31'))
    fig.savefig(path, dpi=165)
    plt.close(fig)


def plot_all_stations_ghi(frame, stations, start_year, end_year, output, max_cloud):
    fig, axes = plt.subplots(len(stations), 1, figsize=(15, 3.0*len(stations)+1.2),
                             sharex=True, squeeze=False, constrained_layout=True)
    for ax, st in zip(axes[:,0], stations):
        sub = frame[(frame['station'] == st) & frame['use_for_scatter']]
        for smoke in (0, 1):
            d = sub[sub['smoke_present'] == smoke]
            ax.scatter(d['date'], d['ghi_kwh_m2'], c=COLORS[smoke],
                       s=10 if smoke == 0 else 20, alpha=.55 if smoke == 0 else .88,
                       edgecolors='none', rasterized=True, label=LABELS[smoke])
        ax.set_title(f'{STATION_NAMES[st]} (n={len(sub):,})', loc='left')
        ax.set_ylabel('Daily GHI\n(kWh/m²)')
        ax.set_ylim(bottom=0)
        ax.grid(alpha=.2)
    axes[0,0].legend(loc='upper right', frameon=False)
    axes[-1,0].xaxis.set_major_locator(mdates.YearLocator(base=2))
    axes[-1,0].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    axes[-1,0].set_xlim(pd.Timestamp(f'{start_year}-01-01'),pd.Timestamp(f'{end_year}-12-31'))
    axes[-1,0].set_xlabel('UTC date')
    fig.suptitle(f'Cloud-screened daily GHI, June–October {start_year}–{end_year} (MODIS ≤{max_cloud:.2f})',fontsize=14)
    fig.savefig(output,dpi=165)
    plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--start-year', type=int, default=2005)
    p.add_argument('--end-year', type=int, default=2025)
    p.add_argument('--years', nargs='+', type=int, help='Optional subset of years, e.g. 2005 2020 2025')
    p.add_argument('--months', nargs='+', type=int, default=[6,7,8,9,10])
    p.add_argument('--stations', nargs='+', default=list(STATION_NAMES), choices=list(STATION_NAMES))
    p.add_argument('--max-cloud', type=float, default=0.10)
    p.add_argument('--min-coverage', type=float, default=0.98)
    p.add_argument('--min-pixels', type=int, default=1)
    p.add_argument('--source', choices=['auto','master','cache'],default='auto')
    p.add_argument('--project-dir', type=Path, default=ROOT,
                   help='Folder with your existing data/processed and data/cache folders')
    p.add_argument('--output-dir', type=Path, help='Default: PROJECT/figures/offline')
    args = p.parse_args(argv)
    if args.years:
        if any(y<2005 or y>2026 for y in args.years):p.error('--years must be 2005..2026')
        args.start_year=min(args.years)
        args.end_year=max(args.years)
    try:
        df=read_local_study(root=args.project_dir,start_year=args.start_year,end_year=args.end_year,
                            months=args.months,stations=args.stations,source=args.source)
        if args.years:df=df[df['year'].isin(args.years)].copy()
        df=quality_flags(df,max_cloud=args.max_cloud,min_coverage=args.min_coverage,
                         min_pixels=args.min_pixels)
    except (ValueError,FileNotFoundError) as exc:
        p.error(str(exc))
    out=args.output_dir or args.project_dir/'figures'/'offline'
    csv_out=args.project_dir/'data'/'processed'/'offline'
    out.mkdir(parents=True,exist_ok=True)
    csv_out.mkdir(parents=True,exist_ok=True)
    suffix=f'{args.start_year}_{args.end_year}' + ('_selected' if args.years else '')
    audit=csv_out/f'scatter_audit_{suffix}.csv'
    df.to_csv(audit,index=False)
    included=df[df['use_for_scatter']].copy()
    included.to_csv(csv_out/f'cloud_filtered_scatter_days_{suffix}.csv',index=False)
    summary=(df.groupby('station',sort=True)
             .agg(total_days=('date','size'),radiation_ok=('radiation_ok','sum'),
                  cloud_ok=('cloud_ok','sum'),smoke_known=('smoke_known','sum'),
                  used_in_scatter=('use_for_scatter','sum'))
             .reset_index())
    summary.to_csv(csv_out/f'scatter_counts_{suffix}.csv',index=False)
    for station in args.stations:
        target=out/f'irradiance_scatter_{station}_{suffix}.png'
        plot_one_station(df,station,args.start_year,args.end_year,target,args.max_cloud)
        print('Saved:',target)
    target=out/f'all_stations_ghi_scatter_{suffix}.png'
    plot_all_stations_ghi(df,args.stations,args.start_year,args.end_year,target,args.max_cloud)
    print('Saved:',target,'\nSaved audit:',audit)
    print(summary.to_string(index=False))
    if included.empty:
        print('WARNING: No days passed all checks. Inspect audit CSV and ensure local HMS, SURFRAD, MODIS records exist.')
    print('Offline analysis finished; no files were downloaded or overwritten in data/raw or data/cache.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
