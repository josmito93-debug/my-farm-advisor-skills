---
name: eda-multigrower
description: Field-level EDA across multiple growers and states using field boundaries, NASA POWER weather, and USDA CDL cropland. Produces six statistical figures, three comparison/correlation analyses, one static geospatial map, and a single-page HTML report.
version: 1.0.0
author: Boreal Bytes
tags: [eda, boundaries, weather, cdl, multigrower, matplotlib, geopandas]
---

# Workflow: eda-multigrower

## Description

Compares field-level conditions across growers that sit in different states.
Each category — boundaries, weather, and CDL cropland — gets two statistical
figures and one comparison or correlation analysis, and the whole dataset gets
one static geospatial map plus a self-contained HTML report.

The reference dataset is three growers with ten fields each: Illinois
(Iroquois County), Iowa (Kossuth County), and Nebraska (York County).

## When to Use This Workflow

- Comparing field geometry, weather exposure, or crop rotation across growers
- Explaining within-field, across-field, and across-grower variation in one pass
- Producing static evidence for a review, assignment, or grower conversation
- Sanity-checking a freshly expanded runtime before deeper crop modelling

Do not use it for soil, terrain, or satellite analysis — those categories are
deliberately out of scope.

## Inputs

All inputs are read-only runtime artifacts under
`${DATA_PIPELINE_DATA_ROOT}/data-pipeline`:

| Input | Path | Used for |
| --- | --- | --- |
| Farm metadata | `growers/<grower>/farms/<farm>/farm.json` | State, farm display name |
| Field boundaries | `.../boundary/field_boundaries.geojson` | Area, perimeter, shape, map |
| Field inventory | `.../manifests/field-inventory.csv` | Expected field count |
| Farm weather | `.../derived/tables/<farm>_weather_<start>_<end>.csv` | GDD, precipitation |
| CDL by year | `.../derived/tables/<farm>_<year>_cdl.csv` | Crop composition, rotation |
| County outlines | `shared/geoadmin/l2_counties/counties_usa.parquet` | Context map |
| State outlines | `shared/geoadmin/l1_states/states_usa.parquet` | Locator inset |

Populate them with a boundaries + weather + CDL ingest. On an existing runtime
that is three steps per grower from `${DATA_PIPELINE_DATA_ROOT}/data-pipeline/src`:

```bash
python scripts/ingest/download_fields.py
python scripts/ingest/download_weather.py --force --weather-backend zarr \
  --weather-start-year 2021 --weather-end-year 2025 --weather-time-standard lst
python scripts/ingest/download_cdl.py
```

with `AG_GROWER_SLUG`, `AG_FARM_SLUG`, `AG_INVENTORY_CSV`, and `AG_BOUNDARIES`
exported first. Soil, DEM, and satellite steps are not needed.

## Run the Workflow

```bash
export DATA_PIPELINE_DATA_ROOT=/absolute/path/to/my-farm-advisor-runtime
cd "${DATA_PIPELINE_DATA_ROOT}/data-pipeline/src"
"${DATA_PIPELINE_DATA_ROOT}/data-pipeline/.venv/bin/python" \
  scripts/reporting/generate_eda_multigrower.py \
  --grower-slug il-grower \
  --grower-slug ia-grower \
  --grower-slug ne-grower \
  --output-dir /path/to/my-farm-advisor/eda/eda-multigrower/examples/output
```

Omit `--grower-slug` to include every grower that has field boundaries. The
script prints a JSON summary with field counts, report path, and output sizes.

## Outputs

| File | Category | Level | What it shows |
| --- | --- | --- | --- |
| `fig01_boundary_area_distribution.png` | Boundaries | Across fields / growers | Field size distribution, medians, outliers |
| `fig02_boundary_shape_vs_area.png` | Boundaries | Across fields | Shape index vs area, compactness trend |
| `fig03_weather_seasonal_gdd.png` | Weather | Across fields / growers | Seasonal GDD by grower and year |
| `fig04_weather_cumulative_precip.png` | Weather | Within field / across growers | Cumulative growing-season precipitation |
| `fig05_cdl_crop_composition.png` | CDL | Across growers | Corn / soybean / other share by grower-year |
| `fig06_cdl_rotation_heatmap.png` | CDL | Within field | Dominant crop per field and year |
| `map01_grower_fields_context.png` | Spatial | All levels | Three-state footprint with county context |
| `analysis01_boundary_comparison.csv` | Boundaries | Across growers | Kruskal-Wallis + Holm-corrected Mann-Whitney |
| `analysis01_boundary_summary.csv` | Boundaries | Across growers | Per-grower median/mean/std/min/max |
| `analysis02_weather_comparison.csv` | Weather | Within field / across growers | GDD vs precipitation correlations, cross-grower tests |
| `analysis03_cdl_comparison.csv` | CDL | Within field / across growers | Crop-mix chi-square, corn share vs GDD |
| `dataset_field_summary.csv` | Dataset | Field | Area, perimeter, compactness, shape index |
| `eda_multigrower_report.html` | Report | All levels | Single-page report with inline figures and tables |

Column definitions for every table are in
[`references/data-dictionary.md`](references/data-dictionary.md).

## Analysis Design

- **Boundaries.** Area and Polsby-Popper compactness per field, computed in
  EPSG:5070. Cross-grower differences use Kruskal-Wallis with pairwise
  Mann-Whitney and Holm correction; rank-biserial gives the effect size.
- **Weather.** Corn GDD (base 10 °C, 30 °C cap) and seasonal precipitation for
  April 1 – September 30, per field-year. Spearman correlation between GDD and
  precipitation per grower, plus cross-grower Kruskal-Wallis tests.
- **CDL.** Per-field-year crop composition collapsed to corn, soybean, and
  other, normalised to 100%. A chi-square test on dominant-class counts compares
  crop mixes; Cramér's V reports effect size. Corn share vs seasonal GDD uses
  the 2021–2023 overlap between CDL and weather coverage.
- **Levels.** Within field: crop sequence and year-to-year weather. Across
  fields within a grower: area, shape, and composition spread. Across growers:
  the tests and the three-panel map.

## Reading the Results

- Wide area spreads are normal in volunteer-mapped boundaries; report medians
  and area-weighted totals rather than means alone.
- Compactness near 1.13 means section-line rectangles; values well below 1.0
  indicate irregular parcels or road-frontage slivers.
- GDD differences between states are expected; use them to contextualise crop
  composition, not to rank growers.
- Significant chi-square results say crop mixes differ, not that one system is
  better.
- Treat p-values from 30 fields as descriptive evidence, not confirmatory
  statistics.

## Limitations

- OSM field polygons are a sample of mapped land, not a complete farm inventory.
- CDL is 30 m pixel composition and does not describe management or irrigation.
- Weather is gridded reanalysis sampled at field centroids, not on-farm sensors.
- CDL covers 2019–2023; weather covers 2021–2025. Cross-category tests use the
  overlap only.
- Soil, terrain, and satellite products are out of scope.

## Regenerating the Committed Artifacts

Figures, tables, and the HTML report under `examples/output/` are small review
artifacts committed on purpose. Raw runtime data stays under
`DATA_PIPELINE_DATA_ROOT` and must not be committed. Regenerate by re-running
the command above against the same grower seeds recorded in
[`references/dataset-assignment2.md`](references/dataset-assignment2.md).
