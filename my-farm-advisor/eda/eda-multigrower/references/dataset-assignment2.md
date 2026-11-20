# Assignment 2 dataset provenance

Reference dataset for the [`eda-multigrower`](../GUIDE.md) workflow: three
growers, ten fields each, in Illinois, Iowa, and Nebraska. This file records
the seeds and county selections so the runtime can be rebuilt and the committed
figures reproduced.

Raw boundaries, weather, and CDL payloads stay under
`${DATA_PIPELINE_DATA_ROOT}` and are not committed.

## Summary

| Grower | Farm | State | County | FIPS | Seed | Min acres | Mode | Fields | Total acres | Median field (ac) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `il-grower` | Prairie Ridge Farm | Illinois | Iroquois | 17075 | 42 | 20 | append | 10 | 1,487.7 | 59.4 |
| `ia-grower` | Hawkeye Valley Farm | Iowa | Kossuth | 19109 | 42 | 20 | append | 10 | 1,474.8 | 149.8 |
| `ne-grower` | Platte Valley Farm | Nebraska | York | 31185 | 42 | 40 | create | 10 | 1,059.9 | 74.2 |

Assignment 1 fields are kept and seven fields were appended for IL and IA
(`--sampling-mode append`, `--min-acres 20`). Nebraska is a new grower
(`--sampling-mode create`, `--min-acres 40`) selected by CDL corn+soybean share;
see [`ne-county-selection.md`](ne-county-selection.md).

The Illinois set deliberately retains the 3.2-acre meadow polygon from
Assignment 1. It is the only sub-10-acre field in the dataset and anchors the
outlier discussion in figure 1 and the boundary analysis.

## Field inventory

### Illinois — Iroquois County (`il-grower`)

| Field ID | Area (ac) | Polsby-Popper | OSM crop tag |
| --- | --- | --- | --- |
| `osm-1499317764` | 612.4 | 0.724 | farmland |
| `osm-1499317763` | 259.5 | 0.478 | farmland |
| `osm-1219831272` | 202.9 | 0.444 | farmland |
| `osm-192327222` | 171.5 | 0.394 | farmland |
| `osm-1255924317` | 61.5 | 0.427 | farmland |
| `osm-889020598` | 57.2 | 0.748 | farmland |
| `osm-1525396389` | 50.6 | 0.622 | farmland |
| `osm-1499460319` | 45.4 | 0.703 | farmland |
| `osm-1499208298` | 23.5 | 0.715 | farmland |
| `osm-1288035236` | 3.2 | 0.615 | meadow |

Total 1,487.7 ac across 10 fields; range 3.2–612.4 ac.

### Iowa — Kossuth County (`ia-grower`)

| Field ID | Area (ac) | Polsby-Popper | OSM crop tag |
| --- | --- | --- | --- |
| `osm-1539433115` | 453.2 | 0.502 | farmland |
| `osm-1052400056` | 252.6 | 0.611 | farmland |
| `osm-1360316094` | 155.8 | 0.785 | farmland |
| `osm-1360336623` | 155.3 | 0.785 | farmland |
| `osm-1360316095` | 154.9 | 0.719 | farmland |
| `osm-1360386502` | 144.6 | 0.331 | farmland |
| `osm-1360326400` | 113.5 | 0.530 | farmland |
| `osm-1360084788` | 32.0 | 0.609 | farmland |
| `osm-1539406576` | 6.8 | 0.475 | farmland |
| `osm-1360386518` | 6.1 | 0.607 | farmland |

Total 1,474.8 ac across 10 fields; range 6.1–453.2 ac.

### Nebraska — York County (`ne-grower`)

| Field ID | Area (ac) | Polsby-Popper | OSM crop tag |
| --- | --- | --- | --- |
| `osm-554107587` | 299.0 | 0.680 | farmland |
| `osm-554483482` | 149.4 | 0.649 | farmland |
| `osm-1276617429` | 141.8 | 0.785 | farmland |
| `osm-1364744114` | 131.9 | 0.717 | farmland |
| `osm-1363582358` | 79.9 | 0.702 | farmland |
| `osm-554936516` | 68.4 | 0.454 | farmland |
| `osm-1363582355` | 53.7 | 0.514 | farmland |
| `osm-554107590` | 48.0 | 0.502 | farmland |
| `osm-554936507` | 47.7 | 0.775 | farmland |
| `osm-1363582347` | 40.1 | 0.792 | farmland |

Total 1,059.9 ac across 10 fields; range 40.1–299.0 ac.

## Runtime inputs

Expected artifacts per grower under
`${DATA_PIPELINE_DATA_ROOT}/data-pipeline/growers/<grower>/farms/<farm>/`:

| Artifact | Path | Expected shape |
| --- | --- | --- |
| Field boundaries | `boundary/field_boundaries.geojson` | 10 polygon features |
| Field inventory | `manifests/field-inventory.csv` | 10 rows |
| Weather | `derived/tables/<farm>_weather_2021-01-01_2025-12-31.csv` | 18,260 rows (10 fields x 1,826 days) |
| CDL | `derived/tables/<farm>_<year>_cdl.csv` | 2019–2023, 10 field IDs per year |

## Rebuild commands

From `${DATA_PIPELINE_DATA_ROOT}/data-pipeline/src`, with the runtime venv:

```bash
# IL and IA: keep Assignment 1 fields, append to ten
python scripts/ingest/bootstrap_farm_from_county.py \
  --state IL --county Iroquois --grower-slug il-grower \
  --farm-slug il-grower-illinois --sampling-mode append \
  --target-fields 10 --min-acres 20 --seed 42

python scripts/ingest/bootstrap_farm_from_county.py \
  --state IA --county Kossuth --grower-slug ia-grower \
  --farm-slug ia-grower-iowa --sampling-mode append \
  --target-fields 10 --min-acres 20 --seed 42

# NE: new grower in York County
python scripts/ingest/bootstrap_farm_from_county.py \
  --state NE --county York --grower-slug ne-grower \
  --farm-slug ne-grower-nebraska --sampling-mode create \
  --target-fields 10 --min-acres 40 --seed 42
```

Then run the boundaries, weather, and CDL ingests for each grower and farm
(see the runbook in [`../GUIDE.md`](../GUIDE.md)). Soil, DEM, and satellite
products are not required for this workflow.

## Verification

The generator prints a JSON summary. Expected output for this dataset:

```json
{ "growers": { "IL": 10, "IA": 10, "NE": 10 }, "fields": 30 }
```

`farm.json` state codes were reconciled with boundary `state_fips`
(17 IL, 19 IA, 31 NE). The county bootstrap defaults new metadata to `IA`,
so the state must be checked after any `--structure-test` run.
