# Grower Web Map Examples

Run from the runtime source copy so paths resolve against live grower data.

## Illinois grower

```bash
export DATA_PIPELINE_DATA_ROOT=/home/coder/my-farm-advisor-runtime
cd "${DATA_PIPELINE_DATA_ROOT}/data-pipeline/src"
"${DATA_PIPELINE_DATA_ROOT}/data-pipeline/.venv/bin/python" \
  scripts/reporting/generate_grower_web_map.py --grower-slug il-grower
```

Output: `growers/il-grower/derived/reports/il-grower_web_map.html`

## Iowa grower

```bash
export DATA_PIPELINE_DATA_ROOT=/home/coder/my-farm-advisor-runtime
cd "${DATA_PIPELINE_DATA_ROOT}/data-pipeline/src"
"${DATA_PIPELINE_DATA_ROOT}/data-pipeline/.venv/bin/python" \
  scripts/reporting/generate_grower_web_map.py --grower-slug ia-grower
```

Output: `growers/ia-grower/derived/reports/ia-grower_web_map.html`

## Single farm

```bash
"${DATA_PIPELINE_DATA_ROOT}/data-pipeline/.venv/bin/python" \
  scripts/reporting/generate_grower_web_map.py \
  --grower-slug il-grower --farm-slug il-grower-illinois
```

Output: `growers/il-grower/derived/reports/il-grower_il-grower-illinois_web_map.html`

## Custom output path

```bash
"${DATA_PIPELINE_DATA_ROOT}/data-pipeline/.venv/bin/python" \
  scripts/reporting/generate_grower_web_map.py \
  --grower-slug ia-grower --output /tmp/ia-grower-map.html
```

## Expected summary

```json
{
  "grower_slug": "il-grower",
  "farms": [{"slug": "il-grower-illinois", "name": "Prairie Ridge Farm", "fields": "3"}],
  "field_count": 3,
  "total_acres": 313.2,
  "output": ".../growers/il-grower/derived/reports/il-grower_web_map.html",
  "size_kb": 25.0
}
```
