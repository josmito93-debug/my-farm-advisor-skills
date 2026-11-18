# Nebraska county selection

The Nebraska grower in this dataset sits in **York County (FIPS 31185)**. This
note records how that county was chosen so the choice is reproducible and the
trade-offs are explicit.

## Method

1. Start from the committed CDL 2023 cropscape for Nebraska.
2. For each of the 93 Nebraska counties, sum cropland pixels (CDL crop classes,
   excluding developed, water, wetland, and forest classes).
3. Collapse the crop mix to **corn + soybean share of cropland**, the rotation
   signal that matters for a corn/soy comparison against Illinois and Iowa.
4. Rank counties by that share, with cropland acreage as a tiebreaker.

The screen is a county-level crop-mix filter, not a parcel or irrigation
filter. It answers "where is the Nebraska corn/soy system most dominant?" and
nothing more.

## Result

York County ranked first of 93 counties:

| Rank | County | FIPS | Cropland (ac) | Corn share | Soy share | Corn + soy | Other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | York | 31185 | 368,535 | 0.592 | 0.260 | **0.852** | 0.148 |
| 2 | Fillmore | 31059 | 368,976 | 0.527 | 0.320 | 0.847 | 0.153 |
| 3 | Hamilton | 31081 | 348,628 | 0.611 | 0.216 | 0.827 | 0.173 |
| 4 | Wayne | 31179 | 283,741 | 0.457 | 0.360 | 0.817 | 0.183 |
| 5 | Burt | 31021 | 318,007 | 0.419 | 0.379 | 0.798 | 0.202 |
| 6 | Cuming | 31039 | 367,782 | 0.448 | 0.340 | 0.787 | 0.213 |
| 7 | Kearney | 31099 | 330,463 | 0.530 | 0.254 | 0.784 | 0.216 |
| 8 | Phelps | 31137 | 345,867 | 0.563 | 0.221 | 0.784 | 0.216 |
| 9 | Polk | 31143 | 282,014 | 0.496 | 0.283 | 0.778 | 0.222 |
| 10 | Dodge | 31053 | 347,530 | 0.428 | 0.350 | 0.778 | 0.222 |

Full table: [`ne-county-screening-full.csv`](ne-county-screening-full.csv)
(93 rows). Top ten only: [`ne-county-screening.csv`](ne-county-screening.csv).

York County has 85.2% of its 368,535 cropland acres in corn or soybeans across
33 CDL crop classes, the highest concentration in the state and the closest
Nebraska analogue to the Iowa and Illinois sites.

## Field sampling

The county bootstrap sampled ten fields with `--min-acres 40` and `--seed 42`:

```bash
python scripts/ingest/bootstrap_farm_from_county.py \
  --state NE --county York --grower-slug ne-grower \
  --farm-slug ne-grower-nebraska --sampling-mode create \
  --target-fields 10 --min-acres 40 --seed 42
```

The 40-acre floor keeps the Nebraska set in the working-cropland size range
and avoids sub-acre polygons; it is higher than the 20-acre floor used for the
Illinois and Iowa append because Nebraska parcels in this county are larger.

## Why the fields are rectangular, not pivot circles

York County is center-pivot country, and the grower narrative references
center-pivot irrigation. The OSM polygons that passed the sampler are, however,
section-line rectangles rather than circles: Polsby-Popper compactness runs
0.45–0.79 with none above 0.8. The dataset keeps them as-is.

That is a deliberate choice:

- Rectangles are what the volunteer-mapped boundaries actually contain, so the
  boundary analysis stays honest about its source instead of inventing geometry.
- The pivot context is still documented at county level through the CDL corn
  and soybean share and in this note.
- The resulting contrast is useful: Nebraska fields are compact and mid-sized,
  while Illinois carries both the largest field (612 ac) and the 3.2-acre
  meadow outlier. That spread is the point of figure 1.

If a later assignment needs pivot geometry, add a circularity filter
(`--min-polsby-popper 0.8`) and reseed; do not hand-edit boundaries.

## Sources

- USDA NASS Cropland Data Layer, 2023 Nebraska cropscape.
- County boundaries: US Census TIGER, staged under
  `shared/geoadmin/l2_counties/counties_usa.parquet`.
- Field polygons: OpenStreetMap via Overpass.
