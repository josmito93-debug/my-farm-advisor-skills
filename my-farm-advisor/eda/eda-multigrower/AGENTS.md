# EDA Multigrower — Local Instructions

## Purpose

This subskill owns the field-level EDA workflow that compares multiple growers
across three data categories: field boundaries, weather, and CDL cropland.
It drives one reporting script and publishes the resulting figures, analysis
tables, and single-page HTML report.

## Safe edit scope

Edits stay in this folder and in the single runtime entrypoint
`../../data-pipeline/src/scripts/reporting/generate_eda_multigrower.py`.
Do not change parent `SKILL.md`, sibling EDA workflows, or root policy from
this subskill unless the task explicitly asks for it.

## Runtime contract

- `DATA_PIPELINE_DATA_ROOT` is required and must be an absolute path outside
  the skill checkout.
- Pipeline root is `${DATA_PIPELINE_DATA_ROOT}/data-pipeline` when it exists,
  otherwise the data root itself.
- Read only existing runtime artifacts: `growers/<grower>/farms/<farm>/farm.json`,
  `.../boundary/field_boundaries.geojson`, `.../manifests/field-inventory.csv`,
  `.../derived/tables/<farm>_<year>_cdl.csv`, and
  `.../derived/tables/<farm>_weather_<start>_<end>.csv`.
- Shared geoadmin county and state layers under `shared/geoadmin/` are read for
  the context map.
- Never write inside the runtime tree. Generated outputs go to `--output-dir`,
  which defaults to this subskill's `examples/output/`.
- Do not require soil, DEM, or satellite products. This workflow intentionally
  runs against a boundaries + weather + CDL ingest only.

## Design constraints

- Static output only: PNG figures, CSV tables, and one self-contained HTML
  report. No interactive dashboards, tile maps, or web apps.
- Two statistical figures and one comparison/correlation analysis per category,
  plus one geospatial context map.
- Keep committed figures small (target < 1 MB each, dpi 150). Do not commit raw
  runtime data or geospatial payloads.
- Standard data stack only: pandas, numpy, scipy, matplotlib, seaborn,
  geopandas. No third-party charting or dashboard packages.

## Command runbook

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

The default output directory is this subskill's `examples/output/` when the
script runs from the checkout; pass `--output-dir` explicitly when running the
runtime copy.

## Local validation

Re-run the generator against all seeded growers and confirm the printed JSON
reports 10 fields per grower, a report file, and figures under 1 MB. Run
`./scripts/validate.sh` from the repository root after structural changes.

## Local-delta-only reminder

This nested AGENTS.md only records instructions that differ from the parent or
root files. Do not duplicate root-wide asset, vendor, or validation policy here
except this pointer to `../../../AGENTS.md`.
