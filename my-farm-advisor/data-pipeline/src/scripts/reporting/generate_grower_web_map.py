#!/usr/bin/env python3
"""Render one lightweight interactive HTML web map per grower.

Reads the farm-level canonical field boundaries produced by the data pipeline
(``growers/<grower>/farms/<farm>/boundary/field_boundaries.geojson``) and emits
a single self-contained page per grower under
``growers/<grower>/derived/reports/``. Field polygons are drawn over Esri
World Imagery tiles; no raster or imagery payload is embedded, so the HTML
stays in the tens of kilobytes.

Usage:
  export DATA_PIPELINE_DATA_ROOT=/absolute/path/to/my-farm-advisor-runtime
  .venv/bin/python src/scripts/reporting/generate_grower_web_map.py \
      --grower-slug il-grower
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

LEAFLET_VERSION = "1.9.4"


def _pipeline_root() -> Path:
    raw = os.environ.get("DATA_PIPELINE_DATA_ROOT")
    if not raw:
        raise SystemExit(
            "DATA_PIPELINE_DATA_ROOT is required (absolute path to the runtime root)"
        )
    data_root = Path(raw).expanduser().resolve()
    nested = data_root / "data-pipeline"
    return nested if nested.is_dir() else data_root


def _normalize_id(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _field_slugs(farm_dir: Path) -> dict[str, str]:
    """Map normalized field id -> field slug using the inventory and field dirs."""
    slugs: dict[str, str] = {}
    inventory = farm_dir / "manifests" / "field-inventory.csv"
    if inventory.exists():
        with inventory.open(newline="", encoding="utf-8") as handle:
            for row in csv.reader(handle):
                if len(row) >= 2 and row[0].strip() and row[0].strip() != "field_id":
                    slugs[_normalize_id(row[0])] = row[1].strip()
    fields_dir = farm_dir / "fields"
    if fields_dir.is_dir():
        for child in sorted(fields_dir.iterdir()):
            if child.is_dir():
                slugs.setdefault(_normalize_id(child.name), child.name)
    return slugs


def _field_meta(farm_dir: Path, slug: str) -> dict[str, Any]:
    return _read_json(farm_dir / "fields" / slug / "field.json", {}) or {}


def _display_name(meta: dict[str, Any], slug: str, field_id: str, ordinal: int) -> str:
    candidate = str(meta.get("display_name") or "").strip()
    if candidate and _normalize_id(candidate) not in {
        _normalize_id(slug),
        _normalize_id(field_id),
    }:
        return candidate
    return f"Field {ordinal}"


def _collect_fields(
    pipeline_root: Path, grower_slug: str, farm_filter: str | None
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    grower_dir = pipeline_root / "growers" / grower_slug
    farms_dir = grower_dir / "farms"
    if not farms_dir.is_dir():
        raise SystemExit(f"no farms directory for grower '{grower_slug}' at {farms_dir}")

    grower_meta = _read_json(grower_dir / "grower.json", {}) or {}
    grower_name = str(grower_meta.get("display_name") or grower_slug)

    features: list[dict[str, Any]] = []
    farm_summaries: list[dict[str, str]] = []

    farm_dirs = [d for d in sorted(farms_dir.iterdir()) if d.is_dir()]
    if farm_filter:
        farm_dirs = [d for d in farm_dirs if d.name == farm_filter]
        if not farm_dirs:
            available = sorted(d.name for d in (farms_dir).iterdir() if d.is_dir())
            raise SystemExit(
                f"farm slug '{farm_filter}' not found for grower '{grower_slug}'. "
                f"Available: {available}"
            )

    for farm_dir in farm_dirs:
        farm_slug = farm_dir.name
        farm_meta = _read_json(farm_dir / "farm.json", {}) or {}
        farm_name = str(farm_meta.get("display_name") or farm_slug)
        boundary_path = farm_dir / "boundary" / "field_boundaries.geojson"
        if not boundary_path.exists():
            print(f"warn  {farm_slug}: missing {boundary_path}; skipping farm")
            continue

        collection = _read_json(boundary_path, {}) or {}
        raw_features = [
            f
            for f in collection.get("features", [])
            if isinstance(f, dict) and f.get("geometry")
        ]
        if not raw_features:
            print(f"warn  {farm_slug}: no field polygons in {boundary_path}; skipping farm")
            continue

        slug_by_id = _field_slugs(farm_dir)
        raw_features.sort(key=lambda f: str(f.get("properties", {}).get("field_id", "")))

        for ordinal, feature in enumerate(raw_features, start=1):
            props = dict(feature.get("properties") or {})
            field_id = str(props.get("field_id") or f"field-{ordinal}")
            slug = slug_by_id.get(_normalize_id(field_id), _normalize_id(field_id))
            meta = _field_meta(farm_dir, slug)
            name = _display_name(meta, slug, field_id, ordinal)
            props.update(
                {
                    "field_id": field_id,
                    "field_name": name,
                    "field_slug": slug,
                    "farm_slug": farm_slug,
                    "farm_name": farm_name,
                    "grower_slug": grower_slug,
                    "grower_name": grower_name,
                }
            )
            features.append({"type": "Feature", "properties": props, "geometry": feature["geometry"]})

        farm_summaries.append(
            {"slug": farm_slug, "name": farm_name, "fields": str(len(raw_features))}
        )

    if not features:
        raise SystemExit(f"no field polygons found for grower '{grower_slug}'")
    return features, farm_summaries


def _center(features: list[dict[str, Any]]) -> tuple[float, float]:
    lats: list[float] = []
    lons: list[float] = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        kind = geometry.get("type", "")
        coords = geometry.get("coordinates") or []
        rings: list[list[list[float]]] = []
        if kind == "Polygon":
            rings = [coords[0]] if coords else []
        elif kind == "MultiPolygon":
            rings = [polygon[0] for polygon in coords if polygon]
        for ring in rings:
            for point in ring:
                if len(point) >= 2:
                    lons.append(float(point[0]))
                    lats.append(float(point[1]))
    if not lats:
        return 40.0, -90.0
    return sum(lats) / len(lats), sum(lons) / len(lons)


def _build_html(
    *,
    features: list[dict[str, Any]],
    farm_summaries: list[dict[str, str]],
    grower_slug: str,
    grower_name: str,
    farm_filter: str | None,
) -> str:
    payload = json.dumps(
        {"type": "FeatureCollection", "features": features}, separators=(",", ":")
    )
    groups = [
        {
            "farm_slug": farm["slug"],
            "farm_name": farm["name"],
            "fields": [
                {
                    "id": f["properties"]["field_id"],
                    "name": f["properties"]["field_name"],
                    "acres": round(float(f["properties"].get("area_acres") or 0), 1),
                }
                for f in features
                if f["properties"]["farm_slug"] == farm["slug"]
            ],
        }
        for farm in farm_summaries
    ]
    groups_json = json.dumps(groups, separators=(",", ":"))
    total_acres = sum(float(f["properties"].get("area_acres") or 0) for f in features)
    lat, lon = _center(features)
    title = f"{grower_name} — Grower Web Map"
    subtitle = f"{len(features)} fields · {total_acres:,.0f} acres · {len(farm_summaries)} farm(s)"
    if farm_filter:
        subtitle += f" · {farm_filter}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{title}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
  #container {{ display: flex; height: 100vh; }}
  #sidebar {{ width: 330px; background: #fafafa; border-right: 1px solid #ddd; padding: 16px; overflow-y: auto; flex-shrink: 0; }}
  #sidebar h1 {{ font-size: 1.15em; color: #1B5E20; }}
  #sidebar .subtitle {{ font-size: .85em; color: #666; margin: 4px 0 12px; }}
  .toolbar {{ display: flex; gap: 8px; margin-bottom: 12px; }}
  .toolbar button {{ flex: 1; padding: 7px 9px; font-size: .82em; border: 1px solid #c8e6c9; background: #fff; color: #1B5E20; border-radius: 6px; cursor: pointer; }}
  .toolbar button:hover {{ background: #e8f5e9; }}
  .layer-control {{ font-size: .82em; color: #555; margin-bottom: 12px; }}
  .farm-group {{ margin-bottom: 12px; }}
  .farm-group h2 {{ font-size: .82em; text-transform: uppercase; letter-spacing: .04em; color: #555; margin-bottom: 6px; }}
  .field-item {{ padding: 8px 10px; margin: 4px 0; border-radius: 6px; background: #fff; border: 1px solid #e0e0e0; cursor: pointer; font-size: .87em; }}
  .field-item:hover {{ background: #e8f5e9; }}
  .field-item .name {{ font-weight: 600; color: #1B5E20; }}
  .field-item .detail {{ font-size: .82em; color: #777; margin-top: 2px; }}
  #map {{ flex: 1; }}
  .leaflet-popup-content {{ font-size: .88em; line-height: 1.5; }}
  .leaflet-popup-content b {{ color: #1B5E20; }}
</style>
</head>
<body>
<div id="container">
  <div id="sidebar">
    <h1>{grower_name}</h1>
    <div class="subtitle">{subtitle}</div>
    <div class="toolbar">
      <button type="button" id="btn-fit">Zoom to all fields</button>
      <button type="button" id="btn-clear">Clear selection</button>
    </div>
    <div class="layer-control">
      <label><input type="checkbox" id="chk-osm"> Use OpenStreetMap basemap</label>
    </div>
    <div id="field-groups"></div>
  </div>
  <div id="map"></div>
</div>
<script>
  var GROWER = {json.dumps(grower_name)};
  var FIELDS = {payload};
  var GROUPS = {groups_json};

  function esc(value) {{
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {{
      return {{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }}[c];
    }});
  }}

  var satellite = L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
    {{ attribution: 'Imagery &copy; Esri, Maxar, Earthstar Geographics', maxZoom: 19 }}
  );
  var osm = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    attribution: '&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19
  }});

  var map = L.map('map', {{ center: [{lat:.6f}, {lon:.6f}], zoom: 13, layers: [satellite] }});
  L.control.scale({{ imperial: true, metric: false }}).addTo(map);

  function popupHtml(p) {{
    var rows = [
      ['Grower', p.grower_name],
      ['Farm', p.farm_name],
      ['Field', p.field_name],
      ['Field ID', p.field_id]
    ];
    if (p.area_acres) rows.push(['Area', Number(p.area_acres).toFixed(1) + ' acres']);
    if (p.crop_name) rows.push(['Crop', p.crop_name]);
    if (p.county_name) rows.push(['County', p.county_name]);
    return rows.map(function (r) {{
      return '<b>' + esc(r[0]) + ':</b> ' + esc(r[1]);
    }}).join('<br>');
  }}

  var fieldLayer = L.geoJSON(FIELDS, {{
    style: {{ color: '#2E7D32', weight: 2, fillColor: '#43A047', fillOpacity: 0.3 }},
    onEachFeature: function (feature, layer) {{
      layer.bindPopup(popupHtml(feature.properties));
      layer.on('mouseover', function () {{ this.setStyle({{ fillOpacity: 0.55, weight: 3 }}); }});
      layer.on('mouseout', function () {{ this.setStyle({{ fillOpacity: 0.3, weight: 2 }}); }});
    }}
  }}).addTo(map);

  function zoomAll() {{
    if (fieldLayer.getLayers().length) map.fitBounds(fieldLayer.getBounds().pad(0.05));
  }}
  function layerFor(id) {{
    var found = null;
    fieldLayer.eachLayer(function (layer) {{
      if (!found && layer.feature && layer.feature.properties.field_id === id) found = layer;
    }});
    return found;
  }}
  function zoomTo(id) {{
    var layer = layerFor(id);
    if (!layer) return;
    map.fitBounds(layer.getBounds().pad(0.35), {{ maxZoom: 16 }});
    layer.openPopup();
    layer.setStyle({{ fillOpacity: 0.55, weight: 3 }});
  }}

  var groupsEl = document.getElementById('field-groups');
  GROUPS.forEach(function (group) {{
    var box = document.createElement('div');
    box.className = 'farm-group';
    var heading = document.createElement('h2');
    heading.textContent = group.farm_name;
    box.appendChild(heading);
    group.fields.forEach(function (field) {{
      var item = document.createElement('div');
      item.className = 'field-item';
      var name = document.createElement('div');
      name.className = 'name';
      name.textContent = field.name;
      var detail = document.createElement('div');
      detail.className = 'detail';
      detail.textContent = field.acres ? field.acres.toFixed(1) + ' acres' : 'field';
      item.appendChild(name);
      item.appendChild(detail);
      item.addEventListener('click', function () {{ zoomTo(field.id); }});
      box.appendChild(item);
    }});
    groupsEl.appendChild(box);
  }});

  document.getElementById('btn-fit').addEventListener('click', zoomAll);
  document.getElementById('btn-clear').addEventListener('click', function () {{
    map.closePopup();
    zoomAll();
  }});
  document.getElementById('chk-osm').addEventListener('change', function (e) {{
    if (e.target.checked) {{ map.removeLayer(satellite); osm.addTo(map); }}
    else {{ map.removeLayer(osm); satellite.addTo(map); }}
  }});

  zoomAll();
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grower-slug", required=True, help="Grower slug, e.g. il-grower")
    parser.add_argument("--farm-slug", default=None, help="Optional farm slug filter")
    parser.add_argument(
        "--output",
        default=None,
        help="Optional explicit output HTML path (defaults to the grower reports dir)",
    )
    args = parser.parse_args()

    pipeline_root = _pipeline_root()
    features, farm_summaries = _collect_fields(
        pipeline_root, args.grower_slug, args.farm_slug
    )
    grower_meta = _read_json(pipeline_root / "growers" / args.grower_slug / "grower.json", {}) or {}
    grower_name = str(grower_meta.get("display_name") or args.grower_slug)

    if args.output:
        out_path = Path(args.output).expanduser()
        if not out_path.is_absolute():
            out_path = pipeline_root / out_path
    else:
        suffix = f"{args.grower_slug}_{args.farm_slug}" if args.farm_slug else args.grower_slug
        out_path = (
            pipeline_root
            / "growers"
            / args.grower_slug
            / "derived"
            / "reports"
            / f"{suffix}_web_map.html"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    html = _build_html(
        features=features,
        farm_summaries=farm_summaries,
        grower_slug=args.grower_slug,
        grower_name=grower_name,
        farm_filter=args.farm_slug,
    )
    out_path.write_text(html, encoding="utf-8")

    total_acres = sum(float(f["properties"].get("area_acres") or 0) for f in features)
    print(
        json.dumps(
            {
                "grower_slug": args.grower_slug,
                "farms": farm_summaries,
                "field_count": len(features),
                "total_acres": round(total_acres, 1),
                "output": str(out_path),
                "size_kb": round(out_path.stat().st_size / 1024, 1),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
