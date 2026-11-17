# Grower Web Map

Render one lightweight, interactive HTML map per grower from the canonical
field boundaries the data pipeline already produced.

- [Subskill index](INDEX.md)
- [Local instructions](AGENTS.md)
- [Examples](examples/README.md)

## What it does

Reads `growers/<grower>/farms/<farm>/boundary/field_boundaries.geojson` for
every farm of a grower and writes a single self-contained page to
`growers/<grower>/derived/reports/<grower>_web_map.html`.

The map:

- draws the real pipeline field polygons over Esri World Imagery tiles
  (Leaflet 1.9.4 from CDN, no imagery embedded),
- fits all of the grower's fields on load and supports zoom in/out,
- lists fields per farm in a sidebar; clicking a field zooms to it and opens
  its popup,
- shows grower, farm, field name, field ID, acres, crop, and county on click,
- optionally switches to an OpenStreetMap basemap.

Output is normally tens of kilobytes because only boundary geometry is
inlined — no rasters, tiles, or downloaded imagery.

## Runtime

The canonical entrypoint ships in the pipeline `src/` tree so the installer
copies it into the runtime:

```text
my-farm-advisor/data-pipeline/src/scripts/reporting/generate_grower_web_map.py
${DATA_PIPELINE_DATA_ROOT}/data-pipeline/src/scripts/reporting/generate_grower_web_map.py
```

## Quick start

```bash
export DATA_PIPELINE_DATA_ROOT=/absolute/path/to/my-farm-advisor-runtime
cd "${DATA_PIPELINE_DATA_ROOT}/data-pipeline/src"
"${DATA_PIPELINE_DATA_ROOT}/data-pipeline/.venv/bin/python" \
  scripts/reporting/generate_grower_web_map.py --grower-slug il-grower
```

Run it once per grower. Use `--farm-slug` to render a single farm, or
`--output` to write the HTML somewhere else.
