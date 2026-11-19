
"""Grouped-bar comparison of smoke vs no-smoke irradiation, June–October, 2005–2025.

Read-only, offline: requires data/processed/master_station_days.csv.
Creates five figures (one per month, four station panels) and a summary CSV.

Run from your project directory:
    python scripts/plot_smoke_irradiance_percent_bars.py
    python scripts/plot_smoke_irradiance_percent_bars.py --max-cloud 0.01 --min-days 2
"""

from matplotlib.patches import Patch
from pathlib import Path
import argparse
import calendar

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

STATIONS = {
    "tbl": "Table Mountain",
    "fpk": "Fort Peck",
    "dra": "Desert Rock",
    "bon": "Bondville",
}
MONTHS = (6, 7, 8, 9, 10)
METRICS = {
    "ghi_kwh_m2": ("GHI", "blue"),
    "dni_kwh_m2": ("DNI", "green"),
    "dhi_kwh_m2": ("DHI", "purple"),
}


def load_filtered_data(csv_file, max_cloud, min_coverage):
    df = pd.read_csv(csv_file, parse_dates=["date"])
    required = {
        "date", "station", "smoke_present", "hms_status", "modis_status",
        "surfrad_status", "cloud_fraction", "modis_pixel_count",
        "ghi_coverage", "dni_coverage", "dhi_coverage", *METRICS,
    }
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing required CSV columns: {sorted(missing)}")

    if df.duplicated(["date", "station"]).any():
        raise ValueError("The input has duplicate date/station rows.")

    numeric = [
        "smoke_present", "cloud_fraction", "modis_pixel_count",
        "ghi_coverage", "dni_coverage", "dhi_coverage", *METRICS,
    ]
    if "solar_extraterrestrial_kwh_m2" in df:
        numeric.append("solar_extraterrestrial_kwh_m2")
    for col in numeric:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    df["station"] = df["station"].astype(str).str.lower().str.strip()
    df = df.loc[
        df["year"].between(2005, 2025)
        & df["month"].isin(MONTHS)
        & df["station"].isin(STATIONS)
    ].copy()

    # Include only reliable radiation, independently observed low-cloud days,
    # and valid HMS smoke classifications. Missing smoke status is NOT no smoke.
    valid = (
        df["hms_status"].eq("ok")
        & df["modis_status"].eq("ok")
        & df["surfrad_status"].eq("ok")
        & df["smoke_present"].isin([0, 1])
        & df["cloud_fraction"].between(0, max_cloud)
        & df["modis_pixel_count"].ge(1)
        & df[["ghi_coverage", "dni_coverage", "dhi_coverage"]]
            .ge(min_coverage).all(axis=1)
        & df[list(METRICS)].notna().all(axis=1)
        & df[list(METRICS)].ge(0).all(axis=1)
        & (df["dhi_kwh_m2"] <= df["ghi_kwh_m2"] + 0.10)
    )
    if "solar_extraterrestrial_kwh_m2" in df:
        toa = df["solar_extraterrestrial_kwh_m2"]
        valid &= ~(toa.gt(0) & df["ghi_kwh_m2"].gt(1.10 * toa))

    return df, df.loc[valid].copy()


def build_summary(all_days, filtered_days, min_days, min_hms_coverage):
    rows = []
    for month in MONTHS:
        for station in STATIONS:
            for year in range(2005, 2026):
                all_group = all_days.loc[
                    (all_days["month"] == month)
                    & (all_days["station"] == station)
                    & (all_days["year"] == year)
                ]
                group = filtered_days.loc[
                    (filtered_days["month"] == month)
                    & (filtered_days["station"] == station)
                    & (filtered_days["year"] == year)
                ]
                smoke = group.loc[group["smoke_present"].eq(1)]
                no_smoke = group.loc[group["smoke_present"].eq(0)]

                days_in_month = calendar.monthrange(year, month)[1]
                hms_coverage = (
                    (all_group["hms_status"].eq("ok")
                     & all_group["smoke_present"].isin([0, 1])).sum()
                    / days_in_month
                )
                enough = (
                    len(smoke) >= min_days
                    and len(no_smoke) >= min_days
                    and hms_coverage >= min_hms_coverage
                )
                row = {
                    "station": station, "month": month, "year": year,
                    "hms_coverage": hms_coverage,
                    "smoke_days_used": len(smoke),
                    "no_smoke_days_used": len(no_smoke),
                    "comparison_valid": enough,
                }
                for column, (label, _) in METRICS.items():
                    mean_smoke = smoke[column].mean()
                    mean_clear = no_smoke[column].mean()
                    row[f"{label.lower()}_mean_smoke_kwh_m2"] = mean_smoke
                    row[f"{label.lower()}_mean_no_smoke_kwh_m2"] = mean_clear
                    row[f"{label.lower()}_percent_diff"] = (
                        100 * (mean_smoke - mean_clear) / mean_clear
                        if enough and pd.notna(mean_clear) and mean_clear > 0
                        else np.nan
                    )
                rows.append(row)
    return pd.DataFrame(rows)


def plot_month(summary, month, max_cloud, min_days, output_file):
    """Four station panels; each year has side-by-side GHI/DNI/DHI bars."""
    fig, axes = plt.subplots(2, 2, figsize=(19, 11), sharex=True)
    years = np.arange(2005, 2026)
    width = 0.25
    offsets = [-width, 0, width]

    for ax, (station, title) in zip(axes.flat, STATIONS.items()):
        data = (
            summary.loc[
                summary["station"].eq(station) & summary["month"].eq(month)
            ]
            .set_index("year")
            .reindex(years)
        )
        for (column, (label, color)), offset in zip(METRICS.items(), offsets):
            values = pd.to_numeric(
                data[f"{label.lower()}_percent_diff"], errors="coerce"
            ).to_numpy(dtype=float)
            mask = np.isfinite(values)

            # Plot only valid comparisons: missing years are not zero.
            ax.bar(
                years[mask] + offset, values[mask],
                width=width * 0.92, color=color, alpha=0.82, label=label,
            )

        valid_count = int(data["comparison_valid"].fillna(False).sum())
        ax.set_title(f"{title} ({valid_count} qualifying years)")
        ax.set_ylabel("Smoke vs no-smoke difference (%)")
        ax.axhline(0, color="black", linewidth=1, alpha=0.7)
        ax.grid(axis="y", alpha=0.25)
        ax.set_axisbelow(True)
        ax.set_xticks(years)
        ax.tick_params(axis="x", rotation=45, labelbottom=True)
        ax.set_xlim(2004.4, 2025.6)
        ax.legend(
            handles=[
                Patch(facecolor=color, label=label)
                for label, color in METRICS.values()
            ],
            loc="best", fontsize=9
        )

    for ax in axes[1, :]:
        ax.set_xlabel("Year")

    month_name = calendar.month_name[month]
    fig.suptitle(
        f"{month_name} | Low-cloud smoke vs no-smoke irradiation (% difference)\n"
        f"2005–2025 | MODIS cloud fraction ≤ {max_cloud:.0%}; "
        f"≥{min_days} valid days per group; missing bars = insufficient data",
        fontsize=16,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    fig.savefig(output_file, dpi=250, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]

    parser.add_argument(
        "--input", type=Path,
        default=root / "data" / "processed" / "master_station_days.csv"
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=root / "figures" / "offline"
    )
    parser.add_argument("--max-cloud", type=float, default=0.10)
    parser.add_argument("--min-coverage", type=float, default=0.98)
    parser.add_argument("--min-days", type=int, default=2,
                        help="Minimum smoke AND no-smoke days per comparison")
    parser.add_argument("--min-hms-coverage", type=float, default=0.90)

    args = parser.parse_args()

    if not (
        0 <= args.max_cloud <= 1
        and 0 <= args.min_coverage <= 1
        and 0 <= args.min_hms_coverage <= 1
        and args.min_days >= 1
    ):
        parser.error(
            "Invalid filter: fractions must be 0–1 and min-days >= 1"
        )
    if not args.input.is_file():
        parser.error(f"Input CSV not found: {args.input}")

    all_days, filtered_days = load_filtered_data(
        args.input, args.max_cloud, args.min_coverage
    )
    summary = build_summary(
        all_days, filtered_days,
        args.min_days, args.min_hms_coverage
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    csv_output = (
        args.output_dir / "smoke_vs_no_smoke_monthly_2005_2025.csv"
    )
    summary.to_csv(csv_output, index=False)
    print(f"Saved summary CSV: {csv_output}")
    print(
        "Qualifying station-month-year comparisons:",
        int(summary["comparison_valid"].sum()), "of", len(summary)
    )

    for month in MONTHS:
        fig_output = args.output_dir / (
            f"{month:02d}_{calendar.month_name[month].lower()}_"
            "smoke_percent_difference_bar_2005_2025.png"
        )
        plot_month(
            summary, month, args.max_cloud,
            args.min_days, fig_output
        )
        print(f"Saved figure: {fig_output}")

    print("Finished. No data downloaded.")


if __name__ == "__main__":
    main()
