# Wildfire Smoke and Solar Irradiance in the United States (2005–2025)

**EN 530.637 — Energy Meteorology | Graduate Semester Project | Johns Hopkins University**

This repository investigates how often satellite-detected wildfire smoke occurs over selected U.S. solar-radiation stations and how measured solar irradiance differs between **smoky and non-smoky days** under relatively low-cloud conditions. The project joins NOAA smoke maps, ground-based irradiance observations, and MODIS satellite cloud information into a reproducible station-by-day dataset.

**Study period:** June 1–October 31 each year, 2005–2025  
**Stations:** Table Mountain (CO), Fort Peck (MT), Desert Rock (NV), Bondville (IL)  
**Main variables:** global horizontal irradiance (GHI), direct normal irradiance (DNI), diffuse horizontal irradiance (DHI), smoke presence, cloud fraction

> **Scope:** The results are observational associations, not causal estimates of smoke-related reductions in solar generation. HMS smoke can be aloft rather than at ground level, and satellite cloud detection can mistake dense smoke for cloud.

## 1. Research question and hypotheses

**Research question:** How did the frequency of wildfire-smoke days change at selected U.S. locations from 2005 to 2025, and how did measured solar irradiance differ between smoke and no-smoke days when substantial cloud contamination was excluded?

The analysis tests two hypotheses:

1. **Smoke frequency:** The share or count of HMS-detected smoke days varies over time and differs among stations.
2. **Irradiance response:** On relatively low-cloud days, smoke is associated with lower direct normal irradiation (DNI), lower global horizontal irradiation (GHI), and changes in diffuse horizontal irradiation (DHI).

The project first checks the September 2020 observations against a known severe U.S. wildfire-smoke episode, then examines June–October of the full 2005–2025 period.

## 2. Data sources and stations

| Source | Role in the analysis | Native coverage / considerations | Access |
| --- | --- | --- | --- |
| **NOAA Hazard Mapping System (HMS)** smoke polygons | Classifies each station-day as smoke detected, no smoke detected, or unavailable; retains plume density when reported | Historical daily polygon archive; detection/coverage are not uniform across all years | [NOAA HMS annual archives](https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Smoke_Polygons/Shapefile/Annual_Bundles/) |
| **NOAA SURFRAD** | Ground-observed GHI, DNI, DHI integrated into daily irradiation (kWh/m²) | Daily observation files; 3-minute samples in earlier years and 1-minute samples from 2009 onward | [SURFRAD](https://gml.noaa.gov/grad/surfrad/) · [Data directory](https://gml.noaa.gov/aftp/data/radiation/surfrad/) |
| **NASA MCD06COSP_D3_MODIS, Collection 6.2** | Independent satellite estimate of cloud-mask fraction for filtering cloud-affected days | Daily **1° × 1°** grid; cloud value represents a grid cell, not the point directly above the station | [LAADS archive](https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/62/MCD06COSP_D3_MODIS/) · [Product DOI](https://doi.org/10.5067/MODIS/MCD06COSP_D3_MODIS.062) |

The station coordinates used by the analysis are defined in [`scripts/settings.py`](scripts/settings.py).

| Station ID | SURFRAD station | Latitude | Longitude |
| --- | --- | ---: | ---: |
| `tbl` | Table Mountain, Colorado | 40.12498 | −105.23680 |
| `fpk` | Fort Peck, Montana | 48.30783 | −105.10170 |
| `dra` | Desert Rock, Nevada | 36.62373 | −116.01947 |
| `bon` | Bondville, Illinois | 40.05192 | −88.37309 |

June–October covers **153 days per year**. Across 21 years and four stations, the complete study grid contains **12,852 possible station-days**, before missing observations and quality screening. NOAA HMS historical coverage begins **August 5, 2005**; June and July 2005 must be treated as unavailable for smoke classification, not as no-smoke days.

## 3. Methodology

### 3.1 Identify smoke days

The program intersects the geographic coordinates of each station with that day's NOAA HMS smoke polygons. It assigns:

- `smoke_present = 1` when a detected plume overlaps the station;
- `smoke_present = 0` when a usable HMS classification has **no** overlapping plume;
- missing/unknown when the HMS data are unavailable or could not be processed.

Where available, the strongest intersecting HMS density classification (light, medium, or heavy) is retained. These classifications reflect **satellite-detected plumes**, not continuous local PM2.5 measurements.

### 3.2 Process measured solar irradiance

SURFRAD observations of GHI, DNI, and DHI (W/m²) are quality-screened and integrated over the day to obtain **daily irradiation (kWh/m²)**. The default quality threshold in the offline figure scripts requires at least **98% estimated daytime measurement coverage** for each radiation component. Days failing required measurement checks are excluded from quantitative comparisons.

DNI is radiation incident on a surface kept normal to the sun; its daily integrated total should **not** be interpreted as electricity delivered by a fixed horizontal PV panel.

### 3.3 Reduce cloud contamination

For each station-day, the pipeline extracts `Cloud_Mask_Fraction/Mean` and its observation count from NASA MCD06COSP_D3_MODIS. The primary low-cloud subset requires:

- MODIS cloud fraction **≤ 0.10 (10%)**;
- a valid MODIS observation and adequate SURFRAD measurements;
- a known HMS classification.

The threshold is a screening choice, not a perfect separation of cloud and smoke effects. The scripts allow sensitivity checks at **1%** and **25%** cloud fraction. Thick smoke can be misidentified as clouds, and MODIS cloud fraction has coarse spatial resolution.

### 3.4 Compare smoke and no-smoke days

For each **station, year, and month** independently, the script calculates the mean daily irradiation of retained smoke and no-smoke days. For GHI, DNI, and DHI, the percentage difference is:

$$
\%\,\mathrm{difference} =
100\,\frac{\overline{I}_{\mathrm{smoke}}-\overline{I}_{\mathrm{no\ smoke}}}
{\overline{I}_{\mathrm{no\ smoke}}}.
$$

A negative percentage means the observed mean on smoke days is lower. The grouped-bar analysis requires at least **two valid days in each group** and **90% HMS coverage** in that station/month/year; comparisons without adequate data are shown as missing, **not as 0%**.

*Smoke-day counts in the monthly dual-axis figures include HMS-classified smoke days regardless of the cloud filter. Irradiance means use low-cloud, radiation-QC-passing days. These are intentionally different subsets.*

## 4. Repository structure

```text
wildfire-smoke-solar-energy/
├── README.md
├── requirements.txt
├── .gitignore
├── run_2005_2025.bat                 # optional Windows batch runner
├── scripts/
│   ├── run_project.py               # coordinated data retrieval / base analysis
│   ├── hms.py                       # HMS smoke-polygon processing
│   ├── surfrad.py                   # SURFRAD retrieval / daily irradiation
│   ├── download_laads_cosp.py       # NASA authenticated NetCDF downloads
│   ├── extract_modis_cosp_cloud.py  # station cloud-fraction extraction
│   ├── analysis.py                  # base merge and analysis figures
│   ├── offline_data.py              # local data reader and QC helpers
│   ├── plot_offline_scatter.py      # daily smoke-labeled scatter plots
│   ├── verify_september_tbl.py      # Table Mountain September validation
│   ├── plot_monthly_site_trends.py  # monthly dual-axis station comparisons*
│   └── plot_smoke_irradiance_percent_bars_fixed.py  # percent-difference bars*
├── tests/
├── data/
│   ├── raw/                         # bulk source files; do not commit
│   ├── cache/                       # local downloaded/extracted caches
│   └── processed/                   # master and summary CSVs
└── figures/
    └── offline/                     # generated scatter, trend and bar figures
```

`*` The two most recent offline scripts were added after the original ZIP project. Copy them into `scripts/` if they are not yet present. If you have saved the revised month-by-month plot or bar script under a different filename, use that name in the commands below.

The grading criteria use `results/` as an example destination for selected final figures and tables. Keeping all generated figures under `figures/` is also logically organized; consider copying **a curated set of final images** to `results/` before submission and linking them here.

## 5. Installation

Requires **Python 3.10+**. From the repository root in **VS Code / Windows PowerShell**:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
```

If PowerShell prevents activation, use `.venv\Scripts\python.exe` in place of `python`, or activate from Command Prompt. The packages include pandas, NumPy, Matplotlib, requests, GeoPandas, Shapely, h5py, and pytest.

### NASA authentication (only for new downloads)

NASA LAADS downloads require a NASA Earthdata account and an authentication token. Supply the token locally when prompted; **never commit it, share it publicly, or store it in the README**. Text pasted into a `getpass` prompt is intentionally invisible. The downloader also supports a `curl` fallback for NASA redirects.

## 6. Reproduce the analyses

### A. Original download and processing pipeline (internet required)

> **Skip this step if the data are already downloaded.** The offline plotting commands in Section 6B do **not** contact NOAA or NASA.

Small validation run:

```powershell
python scripts/run_project.py --start-year 2020 --end-year 2020 --months 9
```

Full study, June–October, 2005–2025:

```powershell
python scripts/run_project.py
```

The downloader caches successful observations. It can resume interrupted downloads, but the full MODIS study would require substantial network transfer. To rebuild the master table from **existing local cache files**, without requesting the raw observations again, use:

```powershell
python scripts/run_project.py --steps merge analyze
```

**Caution:** This merge command rebuilds `master_station_days.csv` from cache records and may overwrite a pre-existing master CSV. If you have only CSV exports and not the cache, **do not use it**; run the offline scripts directly instead.

### B. Offline figures (no redownloading)

Run these commands from the repository root. The offline scripts read `data/processed/master_station_days.csv`, `data/processed/smoke_days.csv` where relevant, or previously saved JSON caches.

**1. Daily scatter plots of GHI, DNI and DHI, with smoke days labeled**

```powershell
python scripts/plot_offline_scatter.py
```

Outputs include one station plot per site and a four-station GHI comparison. Days with significant cloud contamination or invalid irradiance are excluded.

**2. September verification for Table Mountain (2005–2025)**

```powershell
python scripts/verify_september_tbl.py --no-yearly-plots
```

Generates daily irradiation heatmaps and verification tables. Remove `--no-yearly-plots` for individual September plots for each year.

**3. Monthly trend charts (June–October), with station-specific panels and dual y-axes**

```powershell
python scripts/plot_monthly_site_trends.py
```

Each monthly figure displays average daily GHI, DNI and DHI (left axis) against the number of HMS-detected smoky days (right axis). The latest requested layout uses four station panels per month. *Check that your local script is the revised version; the earlier file made panels by metric.*

**4. Smoke versus no-smoke percentage-difference grouped bar charts**

```powershell
python scripts/plot_smoke_irradiance_percent_bars_fixed.py
```

Produces one figure for each month, with four site panels and grouped GHI/DNI/DHI bars by year. It also creates a CSV with the two group means, percent differences, full HMS counts, and retained sample sizes. Unlike the earlier script, this version can explicitly join `data/processed/smoke_days.csv` to restore smoke classifications when necessary.

### Change the cloud threshold

For example, repeat the scatter and percentage-difference analyses at **1%** and **25%** cloud fraction:

```powershell
python scripts/plot_offline_scatter.py --max-cloud 0.01
python scripts/plot_smoke_irradiance_percent_bars_fixed.py --max-cloud 0.25
```

**Note:** These scripts may overwrite outputs with the same filenames. Copy or rename figures before rerunning thresholds if you want to compare them side by side.

## 7. Outputs and figure types

| Output / example filename | Figure type | What it shows |
| --- | --- | --- |
| `figures/offline/irradiance_scatter_tbl_2005_2025.png` | **Scatter plot** | Individual low-cloud daily irradiance observations, identified as smoke or no-smoke |
| `figures/offline/table_mountain_september_2005_2025_cloud_filtered_heatmap.png` | **Heatmap** | September irradiance by year and day-of-month, allowing a date-by-date quality check |
| `figures/offline/09_september_irradiance_smoke_2005_2025.png` | **Dual-axis time series** | September mean daily irradiance across years (left) and monthly smoke-day count (right) |
| `figures/offline/09_september_smoke_percent_difference_bar_2005_2025.png` | **Grouped bar chart** | GHI/DNI/DHI percentage differences for smoke vs no-smoke days, station-by-station and year-by-year |
| `figures/annual_smoke_frequency.png` | **Time series** | Annual share of classified June–October days with HMS-detected smoke (subject to coverage threshold) |

These are the **types of figures the scripts generate**, not a claim that the PNG files have already been committed to GitHub. Upload your selected final images alongside the code so the instructor can view them without running the analysis.

The processed data are saved primarily in:

- `data/processed/master_station_days.csv` — one row per station and UTC date, merging all three datasets;
- `data/processed/smoke_days.csv` — independent HMS station-day classification table;
- `data/processed/cloud_fraction.csv` and `surfrad_daily.csv` — source-specific daily summaries;
- `data/processed/offline/` — offline plotting audit and monthly summary CSVs;
- `figures/offline/` — figures from the offline analysis scripts.

## 8. Key columns and quality flags

| Column | Meaning |
| --- | --- |
| `date`, `station` | UTC observation date and station ID (`tbl`, `fpk`, `dra`, `bon`) |
| `smoke_present` | `1` = HMS smoke detected; `0` = no detected plume; missing = unknown |
| `hms_status`, `surfrad_status`, `modis_status` | Whether each source returned usable information |
| `smoke_density` | Reported HMS light, medium, or heavy plume classification, if available |
| `cloud_fraction` | MODIS cloud-mask fraction, between 0 and 1 |
| `modis_pixel_count` | Number of observations contributing to the MODIS statistic |
| `ghi_kwh_m2`, `dni_kwh_m2`, `dhi_kwh_m2` | Daily integrated irradiance components (kWh/m²) |
| `ghi_coverage`, `dni_coverage`, `dhi_coverage` | Estimated fraction of required daytime measurements that passed QC |
| `clearness_index` | Daily GHI divided by estimated extraterrestrial horizontal irradiation in this pipeline; **not** an independently derived cloud-free flag |

## 9. Limitations and interpretation

- **Smoke detection:** HMS polygons identify detected smoke in the atmospheric column, not necessarily smoke at the ground or during the entire solar day. Detection methods and completeness can change over time.
- **Missing coverage:** Missing HMS records and the pre-August 2005 period are **unknown**, not smoke-free. Station-year or station-month trends should require a coverage threshold.
- **Cloud filtering:** The MODIS 1° cloud statistic may not describe local sky conditions, and dense smoke can be classified as cloud. A stricter filter can remove the very smoky days of interest.
- **Solar geometry and weather:** Monthly grouping reduces—but does not eliminate—seasonality and meteorological confounding. The comparison is **not a causal attribution** of irradiance loss to smoke.
- **Small samples:** Some station/month/year combinations contain too few low-cloud smoky days and non-smoky days for stable means. Missing bars are deliberately not drawn as zero.
- **Measurement uncertainty:** Daily SURFRAD integration depends on sample frequency, QC flags and availability. Consult [NOAA SURFRAD quality notices](https://gml.noaa.gov/grad/surfrad/problems.html) for known station/instrument issues.
- **Timestamp alignment:** Data are merged by **UTC calendar date**; daily HMS polygons and satellite overpasses are not perfectly synchronized with each station's daylight hours.

## 10. Reproducibility and GitHub submission

This repository is intended to document the complete analysis without uploading the very large original MODIS and SURFRAD archives.

1. Commit `README.md`, `requirements.txt`, all analysis scripts and test scripts.
2. Commit **a representative set of final plots and tables** (at least three distinct figure types: scatter, heatmap and grouped bar/dual-axis figures).
3. Include a compact processed CSV or a link to the public data sources; document the fields and any exclusions.
4. Do **not** commit `data/raw/`, downloaded MODIS `.nc` files, local credentials, `.env`, or Earthdata tokens.
5. Before submitting, confirm that the repository is accessible to the instructor and that the figures and command examples match the files actually present in your latest commit.

For the semester report, figure captions should explain time range, variable, units, filtering criteria, sample size and which days are counted as smoke. The independent scientific question, uncertainty discussion, and reproducible code are important complements to the figures.

## 11. References and scientific context

- Juliano et al. (2022), *Smoke from 2020 United States wildfires responsible for substantial solar energy forecast errors*. [DOI: 10.1088/1748-9326/ac5143](https://doi.org/10.1088/1748-9326/ac5143).
- Corwin et al. (2025), *Solar energy resource availability under extreme and historical wildfire smoke conditions*. [DOI: 10.1038/s41467-024-54163-8](https://doi.org/10.1038/s41467-024-54163-8).
- Keelin et al. (2021), *Quantifying the solar impacts of wildfire smoke in western North America*. [DOI: 10.1109/PVSC43889.2021.9518440](https://doi.org/10.1109/PVSC43889.2021.9518440).
- Additional study suggested for distinguishing smoke and non-smoke days: [DOI: 10.1029/2022JD037446](https://doi.org/10.1029/2022JD037446).
- Data: [NOAA SURFRAD](https://gml.noaa.gov/grad/surfrad/), [NOAA HMS](https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Smoke_Polygons/Shapefile/Annual_Bundles/), and [NASA MCD06COSP_D3_MODIS Collection 6.2](https://doi.org/10.5067/MODIS/MCD06COSP_D3_MODIS.062).

---
