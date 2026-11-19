"""Offline visual and numerical QA of Table Mountain September irradiance, 2005–2025.

Reads ONLY existing master_station_days.csv and/or data/cache/ JSON files.
Exports all September days (including cloudy or missing days), validation flags,
annual QC counts, two heatmaps, and optionally all 21 individual September plots.

  python scripts/verify_september_tbl.py
  python scripts/verify_september_tbl.py --max-cloud 0.01
  python scripts/verify_september_tbl.py --no-yearly-plots
"""
from __future__ import annotations
import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from offline_data import ROOT, METRICS, read_local_study, quality_flags

COLORS = {'ghi_kwh_m2':'#237a9b','dni_kwh_m2':'#e2a024','dhi_kwh_m2':'#5e8a65'}


def September_heatmap(df, metric: str, years, screened: bool):
    """Shape: one row/year, one column/day of September. Nan = missing or excluded."""
    matrix = np.full((len(years),30),np.nan,dtype=float)
    smoky = np.zeros((len(years),30),dtype=bool)
    for i,year in enumerate(years):
        this=df[df['year']==year]
        valid=this['use_for_scatter'] if screened else this['radiation_ok'] & ~this['flag_review']
        for rec in this[valid].itertuples(index=False):
            idx=int(rec.day)-1
            if idx < 0 or idx >= 30:
                continue
            value=getattr(rec,metric)
            if pd.notna(value):
                matrix[i,idx]=float(value)
                smoky[i,idx]=(rec.smoke_present==1 and rec.hms_status=='ok')
    return matrix,smoky


def draw_heatmaps(df, years, out_path, *, screened, max_cloud):
    fig,axes=plt.subplots(3,1,figsize=(16,12),sharex=True,constrained_layout=True)
    for ax,(metric,label) in zip(axes,METRICS.items()):
        matrix,smoky=September_heatmap(df,metric,years,screened)
        masked=np.ma.masked_invalid(matrix)
        cmap=plt.get_cmap('viridis').copy()
        cmap.set_bad('#eeeeee')
        plot=ax.imshow(masked,aspect='auto',origin='lower',extent=(0.5,30.5,-.5,len(years)-.5),
                       cmap=cmap,interpolation='nearest',vmin=0)
        iy,ix=np.where(smoky)
        if len(ix):
            ax.scatter(ix+1,iy,facecolors='none',edgecolors='tomato',s=22,lw=1.1,
                       label='HMS smoke (retained)')
        ax.set_yticks(range(len(years)))
        ax.set_yticklabels(years,fontsize=8)
        ax.set_ylabel(f'Year\n{label}')
        fig.colorbar(plot,ax=ax,fraction=0.019,pad=.012,label=f'{label} (kWh/m²)')
    axes[-1].set_xlabel('September day (UTC)')
    axes[-1].set_xticks([1,5,10,15,20,25,30])
    desc=(f'MODIS cloud fraction ≤{max_cloud:.2f}; all three radiation measurements pass QC'
          if screened else 'All valid radiation measurements, including cloudy days')
    fig.suptitle('Table Mountain | September 2005–2025 daily irradiation\n'
                 f'{desc} | orange rings = HMS smoke when known | gray = missing/excluded',fontsize=13)
    fig.savefig(out_path,dpi=175)
    plt.close(fig)


def draw_year(df, year, target, max_cloud):
    sub=df[df['year']==year].sort_values('day').copy()
    fig,axes=plt.subplots(2,1,figsize=(12,8),sharex=True,
                           gridspec_kw={'height_ratios':[3,1]},constrained_layout=True)
    ax,cloudax=axes
    # Plot all instrument-qualified daily readings; cloudy points remain visible
    # for verification, but the included low-cloud days have bold filled circles.
    for metric,label in METRICS.items():
        qualified=sub[sub['radiation_ok'] & ~sub['flag_review']]
        ax.plot(qualified['day'],qualified[metric],color=COLORS[metric],
                lw=1.3,alpha=.65,label=label)
        subset=qualified[qualified['use_for_scatter']]
        ax.scatter(subset['day'],subset[metric],color=COLORS[metric],s=28,zorder=3)
        excluded=qualified[~qualified['use_for_scatter']]
        ax.scatter(excluded['day'],excluded[metric],color=COLORS[metric],s=19,
                   facecolors='none',linewidths=1,zorder=3)
    smoked=sub[sub['hms_status'].eq('ok') & sub['smoke_present'].eq(1)]
    for day in smoked['day']:
        ax.axvspan(day-.43,day+.43,color='#c3532b',alpha=.14)
    ax.set_ylabel('Daily irradiation (kWh/m²)')
    ax.set_title(f'Table Mountain, September {year} | smoke shading = HMS detection\n'
                 'Filled points pass cloud and QC screens; hollow points are excluded',fontsize=11)
    ax.legend(ncol=3,loc='upper right')
    ax.grid(alpha=.2)
    ax.set_ylim(bottom=0)
    ax.set_xlim(.5,30.5)
    cloudax.scatter(sub['day'],sub['cloud_fraction'],color='#647b85',s=20)
    cloudax.axhline(max_cloud,color='#bf4c45',lw=1.4,linestyle='--',label=f'MODIS threshold {max_cloud:.2f}')
    cloudax.set_ylim(-.03,1.05)
    cloudax.set_xlabel('September day (UTC)')
    cloudax.set_ylabel('MODIS cloud\nfraction')
    cloudax.set_xticks([1,5,10,15,20,25,30])
    cloudax.grid(alpha=.2)
    cloudax.legend(loc='upper right',frameon=False)
    fig.savefig(target,dpi=150)
    plt.close(fig)


def yearly_stats(df):
    summaries=[]
    for year, group in df.groupby('year',sort=True):
        qualified = group[group['radiation_ok'] & ~group['flag_review']]
        lowcloud = group[group['use_for_scatter']]
        summaries.append({
            'year':int(year), 'september_days':int(len(group)),
            'valid_radiation_days':int((group['radiation_ok'] & ~group['flag_review']).sum()),
            'low_cloud_days':int(group['cloud_ok'].sum()),
            'known_hms_days':int(group['smoke_known'].sum()),
            'hms_smoke_days_all':int((group['smoke_present'].eq(1)&group['smoke_known']).sum()),
            'days_passing_all_filters':int(group['use_for_scatter'].sum()),
            'smoky_days_passing_all_filters':int((lowcloud['smoke_present']==1).sum()),
            'days_flagged_physical_review':int(group['flag_review'].sum()),
            'mean_ghi_all_valid_kwh_m2':qualified['ghi_kwh_m2'].mean(),
            'mean_ghi_low_cloud_kwh_m2':lowcloud['ghi_kwh_m2'].mean(),
            'mean_dni_low_cloud_kwh_m2':lowcloud['dni_kwh_m2'].mean(),
            'mean_dhi_low_cloud_kwh_m2':lowcloud['dhi_kwh_m2'].mean(),
        })
    return pd.DataFrame(summaries)


def plot_yearly_irradiance_smoke(summary, output_file, max_cloud):
    years = summary['year']

    fig, ax1 = plt.subplots(figsize=(14, 6))

    # Left axis: Average daily irradiation on low-cloud days
    ax1.plot(years, summary['mean_ghi_low_cloud_kwh_m2'],
             'o-', color='blue', label='GHI', linewidth=2)

    ax1.plot(years, summary['mean_dni_low_cloud_kwh_m2'],
             'o-', color='green', label='DNI', linewidth=2)

    ax1.plot(years, summary['mean_dhi_low_cloud_kwh_m2'],
             'o-', color='purple', label='DHI', linewidth=2)

    ax1.set_xlabel('Year')
    ax1.set_ylabel('Average Daily Irradiation (kWh/m²)')
    ax1.set_xticks(years)
    ax1.tick_params(axis='x', rotation=45)
    ax1.set_ylim(bottom=0)
    ax1.grid(True, alpha=0.3)

    # Right axis: Number of smoky days in September
    ax2 = ax1.twinx()

    ax2.bar(years, summary['hms_smoke_days_all'],
            color='orange', alpha=0.30, width=0.7,
            label='Smoke Days')

    ax2.set_ylabel('Number of Smoke Days in September',
                   color='darkorange')
    ax2.tick_params(axis='y', labelcolor='darkorange')
    ax2.set_ylim(0, 30)

    # Combine legends
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()

    ax1.legend(lines1 + lines2, labels1 + labels2,
               loc='upper left')

    plt.title(
        'Table Mountain: September Irradiation and Smoke Days\n'
        f'2005–2025 | Cloud Fraction ≤ {max_cloud:.0%}'
    )

    fig.tight_layout()
    fig.savefig(output_file, dpi=300)
    plt.close(fig)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--start-year',type=int,default=2005)
    p.add_argument('--end-year',type=int,default=2025)
    p.add_argument('--max-cloud',type=float,default=.10)
    p.add_argument('--min-coverage',type=float,default=.98)
    p.add_argument('--min-pixels',type=int,default=1)
    p.add_argument('--source',choices=['auto','master','cache'],default='auto')
    p.add_argument('--project-dir',type=Path,default=ROOT)
    p.add_argument('--output-dir',type=Path,help='Default: PROJECT/figures/offline')
    p.add_argument('--no-yearly-plots',action='store_true',help='Skip creating individual September plots')
    args=p.parse_args(argv)
    try:
        df=read_local_study(root=args.project_dir,start_year=args.start_year,end_year=args.end_year,
                            months=[9],stations=['tbl'],source=args.source)
        df=quality_flags(df,max_cloud=args.max_cloud,min_coverage=args.min_coverage,
                         min_pixels=args.min_pixels)
    except (ValueError,FileNotFoundError) as exc:
        p.error(str(exc))
    years=list(range(args.start_year,args.end_year+1))
    out=args.output_dir or args.project_dir/'figures'/'offline'
    tables=args.project_dir/'data'/'processed'/'offline'
    out.mkdir(parents=True,exist_ok=True)
    tables.mkdir(parents=True,exist_ok=True)
    suffix=f'{args.start_year}_{args.end_year}'
    daily=tables/f'table_mountain_september_{suffix}_daily_audit.csv'
    df.to_csv(daily,index=False)
    summary=yearly_stats(df)
    stats=tables/f'table_mountain_september_{suffix}_yearly_QC.csv'
    summary.to_csv(stats,index=False)

    # Plot annual September average irradiation vs. smoke days
    yearly_plot = out / f'table_mountain_september_{suffix}_yearly_comparison.png'

    plot_yearly_irradiance_smoke(summary, yearly_plot, args.max_cloud)

    print('Saved yearly irradiation vs smoke plot:', yearly_plot)

    for filtered,tag in [(False,'all_valid'),(True,'cloud_filtered')]:
        path=out/f'table_mountain_september_{suffix}_{tag}_heatmap.png'
        draw_heatmaps(df,years,path,screened=filtered,max_cloud=args.max_cloud)
        print('Saved:',path)
    if not args.no_yearly_plots:
        ydir=out/'table_mountain_september_by_year'
        ydir.mkdir(exist_ok=True)
        for year in years:
            draw_year(df,year,ydir/f'september_tbl_{year}.png',args.max_cloud)
        print(f'Saved {len(years)} per-year plots to {ydir}')
    print('Saved daily audit:',daily)
    print('Saved yearly verification summary:',stats)
    print(summary[['year','valid_radiation_days','low_cloud_days','days_passing_all_filters',
                   'smoky_days_passing_all_filters','days_flagged_physical_review']].to_string(index=False))
    print('All files were read locally. No new NASA or NOAA requests were made.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
