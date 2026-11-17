# Grower Web Map Index

Interactive, grower-level HTML maps built from real data-pipeline field
boundaries.

- [Overview](README.md) — behavior, runtime path, and output
- [Examples](examples/README.md) — command lines for the seeded growers
- Canonical entrypoint: `../src/scripts/reporting/generate_grower_web_map.py`

## Entry points

| Need | Command |
| --- | --- |
| Map one grower | `generate_grower_web_map.py --grower-slug <grower>` |
| Map one farm | `generate_grower_web_map.py --grower-slug <grower> --farm-slug <farm>` |
| Custom output | add `--output <path.html>` |

## Inputs and outputs

- Input: `growers/<grower>/farms/<farm>/boundary/field_boundaries.geojson`
  plus `farm.json`, `manifests/field-inventory.csv`, and per-field
  `field.json` for labels.
- Output: `growers/<grower>/derived/reports/<grower>_web_map.html`
  (or `<grower>_<farm>_web_map.html` when `--farm-slug` is used).
