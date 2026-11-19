"""
Plot June-October irradiance and smoke trends, 2005-2025.

FORMAT:
- One figure per month (June, July, August, September, October)
- Four subplots per figure (one for each site)
- Each subplot shows:
    * GHI, DNI, DHI average daily irradiation on left y-axis
    * Smoke-day counts on right y-axis
- Uses ONLY previously downloaded local data
"""

import argparse
import calendar
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from offline_data import ROOT, read_local_study, quality_flags

STATIONS = {
    "tbl": "Table Mountain",
    "fpk": "Fort Peck",
    "dra": "Desert Rock",
    "bon": "Bondville",
}

MONTHS = [6, 7, 8, 9, 10]


def make_summary(df, min_days, min_hms_fraction):
    rows = []

    for (month, station, year), group in df.groupby(["month", "station", "year"]):
        year = int(year)
        month = int(month)
        days_in_month = calendar.monthrange(year, month)[1]

        # HMS known classification days
        known = group[group["smoke_known"]]

        # Days passing cloud / QC filters
        valid = group[group["use_for_scatter"]]

        smoke_coverage = len(known) / days_in_month if days_in_month > 0 else 0.0

        row = {
            "year": year,
            "month": month,
            "station": station,
            "hms_days_known": len(known),
            "hms_coverage": smoke_coverage,
            "low_cloud_qc_days": len(valid),
            "smoke_days": (
                int((known["smoke_present"] == 1).sum())
                if smoke_coverage >= min_hms_fraction
                else np.nan
            ),
            "avg_ghi_kwh_m2": valid["ghi_kwh_m2"].mean() if len(valid) >= min_days else np.nan,
            "avg_dni_kwh_m2": valid["dni_kwh_m2"].mean() if len(valid) >= min_days else np.nan,
            "avg_dhi_kwh_m2": valid["dhi_kwh_m2"].mean() if len(valid) >= min_days else np.nan,
        }

        rows.append(row)

    summary = pd.DataFrame(rows).sort_values(["month", "station", "year"])
    return summary


def plot_month_figure(summary, month, years, max_cloud, output_file):
    monthly = summary[summary["month"] == month]

    fig, axes = plt.subplots(2, 2, figsize=(18, 10), sharex=True)
    axes = axes.flatten()

    station_order = ["tbl", "fpk", "dra", "bon"]

    for ax, station in zip(axes, station_order):
        site_name = STATIONS[station]

        site = (
            monthly[monthly["station"] == station]
            .set_index("year")
            .reindex(years)
        )

        # Left axis: GHI, DNI, DHI
        ax.plot(
            years,
            site["avg_ghi_kwh_m2"],
            marker="o",
            linewidth=2,
            color="blue",
            label="GHI",
        )
        ax.plot(
            years,
            site["avg_dni_kwh_m2"],
            marker="o",
            linewidth=2,
            color="green",
            label="DNI",
        )
        ax.plot(
            years,
            site["avg_dhi_kwh_m2"],
            marker="o",
            linewidth=2,
            color="purple",
            label="DHI",
        )

        ax.set_title(site_name, fontsize=13)
        ax.set_ylabel("Average Daily Irradiation (kWh/m²)")
        ax.set_ylim(bottom=0)
        ax.grid(True, alpha=0.3)

        # Right axis: smoke days
        ax2 = ax.twinx()
        ax2.bar(
            years,
            site["smoke_days"],
            color="orange",
            alpha=0.25,
            width=0.7,
            label="Smoke Days",
        )
        ax2.set_ylabel("Number of Smoke Days", color="darkorange")
        ax2.tick_params(axis="y", labelcolor="darkorange")
        ax2.set_ylim(0, 30)

        ax.set_xticks(years)
        ax.tick_params(axis="x", rotation=45)

        # One legend per subplot
        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left")

    month_name = calendar.month_name[month]

    fig.suptitle(
        f"{month_name}: Irradiation and Smoke Days\n"
        f"2005–2025 | Cloud Fraction ≤ {max_cloud:.0%}",
        fontsize=18
    )

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(output_file, dpi=300)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--project-dir", type=Path, default=ROOT)
    parser.add_argument("--source", choices=["auto", "master", "cache"], default="auto")
    parser.add_argument("--max-cloud", type=float, default=0.10)
    parser.add_argument("--min-coverage", type=float, default=0.98)
    parser.add_argument("--min-days", type=int, default=3)
    parser.add_argument("--min-hms-fraction", type=float, default=0.90)

    args = parser.parse_args()

    data = read_local_study(
        root=args.project_dir,
        start_year=2005,
        end_year=2025,
        months=MONTHS,
        stations=list(STATIONS.keys()),
        source=args.source,
    )

    data = quality_flags(
        data,
        max_cloud=args.max_cloud,
        min_coverage=args.min_coverage,
    )

    summary = make_summary(
        data,
        min_days=args.min_days,
        min_hms_fraction=args.min_hms_fraction,
    )

    out_fig = args.project_dir / "figures" / "offline"
    out_fig.mkdir(parents=True, exist_ok=True)

    out_csv = args.project_dir / "data" / "processed" / "offline"
    out_csv.mkdir(parents=True, exist_ok=True)

    summary_file = out_csv / "monthly_site_irradiance_smoke_2005_2025.csv"
    summary.to_csv(summary_file, index=False)
    print("Saved:", summary_file)

    years = np.arange(2005, 2026)

    for month in MONTHS:
        month_name = calendar.month_name[month].lower()
        output_file = out_fig / f"{month:02d}_{month_name}_irradiance_smoke_2005_2025.png"

        plot_month_figure(
            summary=summary,
            month=month,
            years=years,
            max_cloud=args.max_cloud,
            output_file=output_file,
        )
        print("Saved:", output_file)

    print("Finished. No data were downloaded.")


if __name__ == "__main__":
    main()