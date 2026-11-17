# Grower Web Map — Local Instructions

## Purpose

Render a grower-level interactive HTML map from the canonical field polygons
already produced by the data pipeline. One page per grower, all farms and
fields included.

## Safe edit scope

Edits stay in this folder and in the single runtime entrypoint
`../src/scripts/reporting/generate_grower_web_map.py`. Do not change parent
`SKILL.md`, sibling workflows, or root policy from this subskill unless the
task explicitly asks for it.

## Runtime contract

- `DATA_PIPELINE_DATA_ROOT` is required and must be an absolute path outside
  the skill checkout.
- Pipeline root is `${DATA_PIPELINE_DATA_ROOT}/data-pipeline` when it exists,
  otherwise the data root itself.
- Read only existing runtime artifacts: `growers/<grower>/grower.json`,
  `growers/<grower>/farms/<farm>/farm.json`,
  `.../boundary/field_boundaries.geojson`,
  `.../manifests/field-inventory.csv`, and `.../fields/<slug>/field.json`.
- Write only to `growers/<grower>/derived/reports/` unless `--output` says
  otherwise. Never write inside the skill checkout.

## Design constraints

- Keep the HTML lightweight: inline GeoJSON boundaries only. Do not embed
  rasters, NDVI composites, tile pyramids, or full data bundles.
- Basemap tiles load from the internet (Esri World Imagery by default,
  optional OpenStreetMap). The page is not usable fully offline.
- Every field popup must include grower, farm, and field name. Keep acres,
  crop, and county when present.
- No third-party Python dependencies: the script is standard library only, so
  it runs with the runtime venv or plain `python3`.

## Command runbook

```bash
export DATA_PIPELINE_DATA_ROOT=/absolute/path/to/my-farm-advisor-runtime
cd "${DATA_PIPELINE_DATA_ROOT}/data-pipeline/src"
"${DATA_PIPELINE_DATA_ROOT}/data-pipeline/.venv/bin/python" \
  scripts/reporting/generate_grower_web_map.py --grower-slug il-grower
"${DATA_PIPELINE_DATA_ROOT}/data-pipeline/.venv/bin/python" \
  scripts/reporting/generate_grower_web_map.py --grower-slug ia-grower
```

Verify the printed JSON summary reports the expected field count and a
`size_kb` in the tens of kilobytes, and that the output file exists under the
grower's `derived/reports/` directory.

## Local validation

Re-run the generator against both seeded growers after changing the script.
Run `./scripts/validate.sh` from the repository root after structural changes.
