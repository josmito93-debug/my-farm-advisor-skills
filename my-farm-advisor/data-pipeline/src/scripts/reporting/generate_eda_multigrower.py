#!/usr/bin/env python3
"""Field-level EDA across growers: boundaries, weather, and CDL cropland.

Builds the Assignment 2 multigrower EDA package: six statistical figures,
three comparison/correlation tables, one static geospatial map, and a
self-contained single-page HTML report.

Reads only existing runtime artifacts under DATA_PIPELINE_DATA_ROOT:
  growers/<grower>/farms/<farm>/boundary/field_boundaries.geojson
  growers/<grower>/farms/<farm>/manifests/field-inventory.csv
  growers/<grower>/farms/<farm>/derived/tables/<farm>_<year>_cdl.csv
  growers/<grower>/farms/<farm>/derived/tables/<farm>_weather_<start>_<end>.csv

Writes only to --output-dir. Standard data stack only (pandas, numpy, scipy,
matplotlib, seaborn, geopandas); no interactive output.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402
from scipy import stats  # noqa: E402

STATE_COLORS = {"IL": "#2f6db3", "IA": "#d1772c", "NE": "#3f8f5b"}
STATE_BY_FIPS = {
    "17": "IL",
    "19": "IA",
    "31": "NE",
    "20": "KS",
    "27": "MN",
    "29": "MO",
    "38": "ND",
    "46": "SD",
    "55": "WI",
}
CROP_COLORS = {"Corn": "#e3b505", "Soybeans": "#4f9d69", "Other": "#b7b7b7"}
CROP_ORDER = ["Corn", "Soybeans", "Other"]
GDD_BASE_C = 10.0
GDD_CAP_C = 30.0
SEASON_START_DOY = 91  # April 1
SEASON_END_DOY = 273  # September 30


@dataclass
class GrowerData:
    slug: str
    farm: str
    name: str
    state: str
    county: str
    label: str
    fields: gpd.GeoDataFrame
    weather: pd.DataFrame
    cdl: pd.DataFrame
    color: str = "#555555"
    weather_years: list[int] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        default=os.environ.get("DATA_PIPELINE_DATA_ROOT"),
        help="Runtime data root (defaults to DATA_PIPELINE_DATA_ROOT)",
    )
    parser.add_argument(
        "--grower-slug",
        action="append",
        default=None,
        help="Grower slug to include; repeatable. Defaults to every seeded grower.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parents[4] / "eda" / "eda-multigrower" / "examples" / "output"),
        help="Directory for figures, analysis tables, and the HTML report",
    )
    parser.add_argument(
        "--weather-start-year", type=int, default=2021, help="First weather year to expect"
    )
    parser.add_argument(
        "--weather-end-year", type=int, default=2025, help="Last weather year to expect"
    )
    return parser.parse_args()


def resolve_pipeline_root(raw: str | None) -> Path:
    if not raw:
        sys.exit("DATA_PIPELINE_DATA_ROOT is required (or pass --data-root)")
    root = Path(raw)
    if not root.is_absolute():
        sys.exit(f"data root must be absolute: {root}")
    pipeline = root / "data-pipeline"
    return pipeline if pipeline.exists() else root


def discover_growers(root: Path, wanted: list[str] | None) -> list[tuple[Path, str]]:
    growers_dir = root / "growers"
    if not growers_dir.exists():
        sys.exit(f"growers directory missing: {growers_dir}")
    found: list[tuple[Path, str]] = []
    for grower_dir in sorted(p for p in growers_dir.iterdir() if p.is_dir()):
        if wanted and grower_dir.name not in wanted:
            continue
        for farm_dir in sorted(p for p in (grower_dir / "farms").iterdir() if p.is_dir()):
            if (farm_dir / "boundary" / "field_boundaries.geojson").exists():
                found.append((farm_dir, grower_dir.name))
    if not found:
        sys.exit("no growers with field boundaries found under the runtime root")
    return found


def field_metrics(fields: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = fields.copy()
    ea = out.to_crs("EPSG:5070")
    out["area_acres"] = ea.geometry.area / 4046.8564224
    out["perimeter_km"] = ea.geometry.length / 1000.0
    out["polsby_popper"] = 4 * math.pi * ea.geometry.area / (ea.geometry.length**2)
    out["shape_index"] = ea.geometry.length / (2 * np.sqrt(math.pi * ea.geometry.area))
    out["centroid_x"] = ea.geometry.centroid.x
    out["centroid_y"] = ea.geometry.centroid.y
    return out


def load_weather(farm_dir: Path, start_year: int, end_year: int) -> pd.DataFrame:
    tables = sorted((farm_dir / "derived" / "tables").glob("*_weather_*.csv"))
    if not tables:
        sys.exit(f"no farm weather table under {farm_dir}/derived/tables")
    frame = pd.read_csv(tables[-1])
    frame["date"] = pd.to_datetime(frame["date"])
    frame["year"] = frame["date"].dt.year
    frame["doy"] = frame["date"].dt.dayofyear
    frame = frame[(frame["year"] >= start_year) & (frame["year"] <= end_year)].copy()
    tmax = frame["T2M_MAX"].clip(upper=GDD_CAP_C)
    tmin = frame["T2M_MIN"].clip(lower=GDD_BASE_C)
    frame["gdd"] = (((tmax + tmin) / 2.0) - GDD_BASE_C).clip(lower=0.0)
    return frame


def load_cdl(farm_dir: Path) -> pd.DataFrame:
    tables = sorted((farm_dir / "derived" / "tables").glob("*_20??_cdl.csv"))
    if not tables:
        sys.exit(f"no CDL year tables under {farm_dir}/derived/tables")
    frames = []
    for path in tables:
        year = int(path.stem.split("_")[-2])
        frame = pd.read_csv(path)
        frame["year"] = year
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def load_growers(root: Path, wanted: list[str] | None, start: int, end: int) -> list[GrowerData]:
    growers: list[GrowerData] = []
    for farm_dir, slug in discover_growers(root, wanted):
        meta_path = farm_dir / "farm.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        fields = field_metrics(gpd.read_file(farm_dir / "boundary" / "field_boundaries.geojson"))
        state = str(meta.get("state") or "").upper()
        if "state_fips" in fields.columns and len(fields):
            fips = str(fields["state_fips"].iloc[0]).split(".")[0].zfill(2)
            state = STATE_BY_FIPS.get(fips, state)
        county = ""
        if "county_name" in fields.columns and len(fields):
            county = str(fields["county_name"].dropna().iloc[0])
        growers.append(
            GrowerData(
                slug=slug,
                farm=farm_dir.name,
                name=str(meta.get("display_name") or farm_dir.name),
                state=state,
                county=county,
                label=state or slug[:2].upper(),
                fields=fields,
                weather=load_weather(farm_dir, start, end),
                cdl=load_cdl(farm_dir),
            )
        )
    growers.sort(key=lambda g: (["IL", "IA", "NE"].index(g.label) if g.label in ("IL", "IA", "NE") else 99, g.label))
    for idx, grower in enumerate(growers):
        grower.color = STATE_COLORS.get(
            grower.label, ["#2f6db3", "#d1772c", "#3f8f5b", "#8d5fa8"][idx % 4]
        )
        grower.weather_years = sorted(grower.weather["year"].unique().tolist())
    return growers


# --------------------------------------------------------------------------
# Derived tables
# --------------------------------------------------------------------------


def season_frame(weather: pd.DataFrame) -> pd.DataFrame:
    season = weather[
        (weather["doy"] >= SEASON_START_DOY) & (weather["doy"] <= SEASON_END_DOY)
    ].copy()
    grouped = (
        season.groupby(["field_id", "year"])
        .agg(
            gdd_total=("gdd", "sum"),
            precip_mm=("PRECTOTCORR", "sum"),
            tmean_c=("T2M", "mean"),
            solar_mj=("ALLSKY_SFC_SW_DWN", "sum"),
        )
        .reset_index()
    )
    return grouped


def crop_frame(cdl: pd.DataFrame) -> pd.DataFrame:
    frame = cdl.copy()
    frame["crop_class"] = np.where(
        frame["crop_name"].eq("Corn"),
        "Corn",
        np.where(frame["crop_name"].eq("Soybeans"), "Soybeans", "Other"),
    )
    shares = (
        frame.groupby(["field_id", "year", "crop_class"])["pct"].sum().unstack(fill_value=0.0)
    )
    shares = shares.reindex(columns=CROP_ORDER, fill_value=0.0).reset_index()
    totals = shares[CROP_ORDER].sum(axis=1).replace(0.0, np.nan)
    for crop in CROP_ORDER:
        shares[f"{crop.lower()}_share"] = (shares[crop] / totals).fillna(0.0)
    dominant = (
        frame.sort_values("pct", ascending=False)
        .groupby(["field_id", "year"])["crop_class"]
        .first()
        .rename("dominant_crop")
    )
    return shares.merge(dominant, on=["field_id", "year"], how="left")


def holm_adjust(pvalues: list[float]) -> list[float]:
    order = np.argsort(pvalues)
    adjusted = np.full(len(pvalues), np.nan)
    running = 0.0
    for rank, idx in enumerate(order):
        value = min(1.0, (len(pvalues) - rank) * pvalues[idx])
        running = max(running, value)
        adjusted[idx] = running
    return adjusted.tolist()


def rank_biserial(u_stat: float, n_a: int, n_b: int) -> float:
    return float(1.0 - (2.0 * u_stat) / (n_a * n_b))


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------


def style() -> None:
    sns.set_theme(style="whitegrid", context="talk")
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.dpi": 150,
            "font.size": 11,
            "axes.titlesize": 13,
            "axes.labelsize": 11,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 9,
            "axes.titleweight": "bold",
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def fig_boundary_area(growers: list[GrowerData], out: Path) -> None:
    rows = [
        {"grower": g.label, "area_acres": row["area_acres"], "field_id": row["field_id"]}
        for g in growers
        for _, row in g.fields.iterrows()
    ]
    frame = pd.DataFrame(rows)
    frame["log_area"] = np.log10(frame["area_acres"])
    fig, ax = plt.subplots(figsize=(8.8, 5.3))
    order = [g.label for g in growers]
    palette = {g.label: g.color for g in growers}
    sns.violinplot(
        data=frame,
        x="grower",
        y="log_area",
        order=order,
        hue="grower",
        palette=palette,
        inner=None,
        cut=0,
        linewidth=0.8,
        ax=ax,
        legend=False,
        alpha=0.30,
    )
    sns.stripplot(
        data=frame,
        x="grower",
        y="log_area",
        order=order,
        hue="grower",
        palette=palette,
        size=6,
        jitter=0.12,
        alpha=0.9,
        ax=ax,
        legend=False,
    )
    ax.set_xlabel("")
    ax.set_ylabel("Field area (acres, log scale)")
    ax.set_title("Field size distribution by grower")
    ax.set_yticks([0, 1, 2, 3])
    ax.set_yticklabels(["1", "10", "100", "1,000"])
    ax.set_ylim(-0.25, 3.25)
    ax.set_xlim(-0.55, 2.55)
    for idx, label in enumerate(order):
        subset = frame.loc[frame["grower"] == label, "log_area"]
        median = subset.median()
        ax.annotate(
            f"median {10 ** median:,.0f} ac",
            xy=(idx, median),
            ha="center",
            va="center",
            fontsize=8.5,
            color="#1d2329",
            bbox={"boxstyle": "round,pad=0.22", "facecolor": "white", "edgecolor": "none", "alpha": 0.85},
        )
    smallest = frame.loc[frame["area_acres"].idxmin()]
    ax.annotate(
        f"{smallest['grower']} meadow outlier: {smallest['area_acres']:.1f} ac",
        xy=(order.index(smallest["grower"]) + 0.04, np.log10(smallest["area_acres"])),
        xytext=(1.42, 0.22),
        fontsize=8.5,
        color="#8a3b3b",
        ha="left",
        va="center",
        arrowprops={"arrowstyle": "->", "color": "#8a3b3b", "lw": 0.9,
                    "connectionstyle": "arc3,rad=-0.15"},
    )
    fig.tight_layout()
    fig.savefig(out / "fig01_boundary_area_distribution.png")
    plt.close(fig)


def fig_boundary_shape(growers: list[GrowerData], out: Path) -> None:
    rows = [
        {
            "grower": g.label,
            "area_acres": row["area_acres"],
            "shape_index": row["shape_index"],
            "polsby_popper": row["polsby_popper"],
            "field_id": row["field_id"],
        }
        for g in growers
        for _, row in g.fields.iterrows()
    ]
    frame = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    for grower in growers:
        subset = frame[frame["grower"] == grower.label]
        ax.scatter(
            subset["area_acres"],
            subset["shape_index"],
            s=70,
            label=f"{grower.label} ({len(subset)} fields)",
            color=grower.color,
            edgecolor="white",
            linewidth=0.8,
            alpha=0.9,
        )
    ax.set_xscale("log")
    ax.set_xticks([10, 100, 1000])
    ax.set_xticklabels(["10", "100", "1,000"])
    ax.minorticks_off()
    ax.set_xlabel("Field area (acres, log scale)")
    ax.set_ylabel("Shape index  (1.0 = perfect circle)")
    ax.set_title("Field shape vs size")
    ax.axhline(1.13, color="#999999", linestyle="--", linewidth=1.0)
    ax.text(
        0.995,
        1.13,
        "section-line square (1.13)",
        transform=ax.get_yaxis_transform(),
        ha="right",
        va="bottom",
        fontsize=8,
        color="#777777",
    )
    ax.legend(frameon=True, fontsize=9, loc="upper left")
    fig.tight_layout()
    fig.savefig(out / "fig02_boundary_shape_vs_area.png")
    plt.close(fig)


def fig_weather_gdd(growers: list[GrowerData], seasons: pd.DataFrame, out: Path) -> None:
    years = sorted(seasons["year"].unique())
    fig, axes = plt.subplots(1, len(growers), figsize=(12.8, 4.7), sharey=True)
    if len(growers) == 1:
        axes = [axes]
    for ax, grower in zip(axes, growers):
        subset = seasons[seasons["grower"] == grower.label]
        sns.boxplot(
            data=subset,
            x="year",
            y="gdd_total",
            order=years,
            color=grower.color,
            width=0.62,
            linewidth=1.0,
            fliersize=2.5,
            showmeans=True,
            meanprops={
                "marker": "D",
                "markerfacecolor": "white",
                "markeredgecolor": "#333333",
                "markersize": 4,
            },
            ax=ax,
        )
        ax.set_title(
            f"{grower.label}: {grower.county} County\n"
            f"mean {subset['gdd_total'].mean():,.0f} GDD | {subset['field_id'].nunique()} fields",
            fontsize=11,
        )
        ax.set_xlabel("")
        ax.tick_params(axis="x", labelsize=9)
        if len(years) > 5:
            ax.set_xticks(range(0, len(years), 2))
            ax.set_xticklabels([str(years[i]) for i in range(0, len(years), 2)])
    axes[0].set_ylabel("Seasonal GDD (base 10 degC, Apr-Sep)")
    fig.suptitle("Seasonal growing degree days by year, faceted by grower", fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(out / "fig03_weather_seasonal_gdd.png")
    plt.close(fig)


def fig_weather_precip(growers: list[GrowerData], out: Path) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 5.2))
    for grower in growers:
        weather = grower.weather[
            (grower.weather["doy"] >= SEASON_START_DOY)
            & (grower.weather["doy"] <= SEASON_END_DOY)
        ]
        by_year_field = (
            weather.groupby(["year", "field_id", "doy"])["PRECTOTCORR"].sum().reset_index()
        )
        daily = (
            by_year_field.groupby(["year", "doy"])["PRECTOTCORR"].mean().reset_index()
        )
        cumulative = daily.sort_values(["year", "doy"]).copy()
        cumulative["cum_precip"] = cumulative.groupby("year")["PRECTOTCORR"].cumsum()
        summary = cumulative.groupby("doy")["cum_precip"].agg(["mean", "min", "max"])
        ax.plot(
            summary.index,
            summary["mean"],
            color=grower.color,
            linewidth=2.2,
            label=f"{grower.label} ({len(grower.weather_years)} yr mean)",
        )
        ax.fill_between(
            summary.index, summary["min"], summary["max"], color=grower.color, alpha=0.15
        )
    ax.set_xlabel("Day of year")
    ax.set_ylabel("Cumulative precipitation (mm)")
    ax.set_title("Growing-season precipitation accumulation")
    ticks = [91, 121, 152, 182, 213, 244, 274]
    ax.set_xticks(ticks)
    ax.set_xticklabels(["Apr 1", "May 1", "Jun 1", "Jul 1", "Aug 1", "Sep 1", "Oct 1"], fontsize=9)
    ax.set_xlim(SEASON_START_DOY, SEASON_END_DOY + 1)
    ax.set_ylim(bottom=0)
    ax.legend(fontsize=9, loc="upper left")
    fig.text(
        0.5,
        0.008,
        "Line = multi-year mean across fields; band = field-year min/max",
        ha="center",
        fontsize=8,
        color="#6b6b6b",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out / "fig04_weather_cumulative_precip.png")
    plt.close(fig)


def fig_crop_composition(crops: pd.DataFrame, out: Path) -> None:
    grouped = (
        crops.groupby(["grower", "year"])[["corn_share", "soybeans_share", "other_share"]]
        .mean()
        .reset_index()
    )
    grower_order = [g for g in ["IL", "IA", "NE"] if g in set(grouped["grower"])]
    grouped["grower"] = pd.Categorical(grouped["grower"], categories=grower_order, ordered=True)
    grouped = grouped.sort_values(["grower", "year"]).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(11.5, 5.6))
    x = np.arange(len(grouped))
    bottom = np.zeros(len(grouped))
    for crop, column in [("Corn", "corn_share"), ("Soybeans", "soybeans_share"), ("Other", "other_share")]:
        values = grouped[column].to_numpy() * 100
        ax.bar(
            x,
            values,
            bottom=bottom,
            color=CROP_COLORS[crop],
            width=0.82,
            label=crop,
            edgecolor="white",
            linewidth=1.0,
        )
        bottom += values
    for xi, value in zip(x, grouped["corn_share"].to_numpy() * 100):
        ax.text(xi, value / 2, f"{value:.0f}%", ha="center", va="center", fontsize=7.5, color="#4a3600")
    ax.set_xticks(x)
    ax.set_xticklabels(grouped["year"].astype(str), fontsize=9)
    ax.set_ylabel("Share of field area (%)")
    ax.set_ylim(0, 100)
    ax.set_title("CDL crop composition by grower and year (mean across fields)", pad=30)
    ax.legend(
        ncol=3,
        fontsize=9,
        loc="lower left",
        bbox_to_anchor=(0.0, 1.005),
        frameon=False,
        handlelength=1.2,
        columnspacing=1.6,
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    for grower in grouped["grower"].unique():
        idx = grouped.index[grouped["grower"] == grower]
        if idx.min() > 0:
            ax.axvline(idx.min() - 0.5, color="#c9c9c9", linewidth=0.9, linestyle=(0, (4, 3)))
        ax.text(
            float(idx.to_numpy().mean()),
            -0.13,
            grower,
            transform=ax.get_xaxis_transform(),
            ha="center",
            va="top",
            fontsize=11,
            fontweight="bold",
            color=STATE_COLORS.get(grower, "#555555"),
        )
    fig.tight_layout()
    fig.savefig(out / "fig05_cdl_crop_composition.png")
    plt.close(fig)


def fig_crop_heatmap(growers: list[GrowerData], crops: pd.DataFrame, out: Path) -> None:
    years = sorted(crops["year"].unique())
    labels: list[str] = []
    matrix: list[list[int]] = []
    class_to_int = {crop: idx for idx, crop in enumerate(CROP_ORDER)}
    for grower in growers:
        field_ids = (
            grower.fields.sort_values("area_acres", ascending=False)["field_id"].astype(str).tolist()
        )
        for field_id in field_ids:
            row: list[int] = []
            for year in years:
                match = crops[(crops["field_id"].astype(str) == field_id) & (crops["year"] == year)]
                crop = match["dominant_crop"].iloc[0] if len(match) else "Other"
                row.append(class_to_int.get(crop, class_to_int["Other"]))
            labels.append(f"{grower.label} {field_id.replace('osm-', '')[-6:]}")
            matrix.append(row)
    arr = np.array(matrix)
    cmap = ListedColormap([CROP_COLORS[c] for c in CROP_ORDER])
    fig, ax = plt.subplots(figsize=(7.8, 9.4))
    ax.imshow(arr, aspect="auto", cmap=cmap, vmin=-0.5, vmax=2.5)
    for boundary in range(1, len(years)):
        ax.axvline(boundary - 0.5, color="white", linewidth=1.8)
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels(years)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=7.5)
    ax.set_title("Dominant CDL crop by field and year", pad=30)
    ax.set_xlabel("Year")
    ax.tick_params(axis="both", length=0)
    grower_offsets = []
    running = 0
    for grower in growers:
        count = len(grower.fields)
        grower_offsets.append((grower, running, running + count))
        running += count
    for grower, start, end in grower_offsets:
        ax.axhline(start - 0.5, color="white", linewidth=2.2)
        ax.text(
            -0.62,
            (start + end - 1) / 2,
            grower.label,
            transform=ax.get_yaxis_transform(),
            ha="right",
            va="center",
            fontsize=11,
            fontweight="bold",
            color=grower.color,
        )
    handle_labels = [
        plt.Rectangle((0, 0), 1, 1, color=CROP_COLORS[c]) for c in CROP_ORDER
    ]
    ax.legend(
        handle_labels,
        CROP_ORDER,
        ncol=3,
        fontsize=9,
        loc="lower center",
        bbox_to_anchor=(0.5, 1.005),
        frameon=False,
        handlelength=1.2,
    )
    fig.savefig(out / "fig06_cdl_rotation_heatmap.png", bbox_inches="tight")
    plt.close(fig)


def draw_scalebar(ax, length_km: float = 20.0, left_frac: float = 0.04) -> None:
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    width = (x1 - x0) * 0.16
    height = (y1 - y0) * 0.012
    left = x0 + (x1 - x0) * left_frac
    bottom = y0 + (y1 - y0) * 0.05
    ax.add_patch(
        plt.Rectangle((left, bottom), width, height, facecolor="#333333", edgecolor="none", zorder=6)
    )
    ax.add_patch(
        plt.Rectangle(
            (left + width / 2, bottom), width / 2, height, facecolor="white", edgecolor="#333333", linewidth=0.6, zorder=6
        )
    )
    ax.text(
        left + width / 2,
        bottom + height * 2.4,
        f"{length_km:.0f} km",
        ha="center",
        va="bottom",
        fontsize=8,
        color="#333333",
        zorder=6,
    )


def draw_north_arrow(ax) -> None:
    ax.annotate(
        "N",
        xy=(0.95, 0.12),
        xytext=(0.95, 0.055),
        xycoords="axes fraction",
        textcoords="axes fraction",
        ha="center",
        va="bottom",
        fontsize=9,
        fontweight="bold",
        color="#333333",
        arrowprops={"arrowstyle": "-|>", "color": "#333333", "lw": 1.4},
        zorder=6,
    )


def fig_context_map(growers: list[GrowerData], root: Path, out: Path) -> None:
    counties = gpd.read_parquet(root / "shared" / "geoadmin" / "l2_counties" / "counties_usa.parquet")
    states = gpd.read_parquet(root / "shared" / "geoadmin" / "l1_states" / "states_usa.parquet")
    counties = counties.to_crs("EPSG:5070")
    states = states.to_crs("EPSG:5070")
    conus = states[~states["state_code"].isin(["AK", "HI", "PR", "VI", "GU", "AS", "MP"])]

    fig = plt.figure(figsize=(18.5, 5.9))
    grid = fig.add_gridspec(1, len(growers) + 1, width_ratios=[1.15] + [1.0] * len(growers), wspace=0.06)

    locator = fig.add_subplot(grid[0, 0])
    conus.plot(ax=locator, facecolor="#f0ede7", edgecolor="#c9c2b6", linewidth=0.4)
    for grower in growers:
        state_code = grower.label
        state_shape = states[states["state_code"] == state_code]
        if len(state_shape):
            state_shape.plot(ax=locator, facecolor=grower.color, edgecolor="#333333", linewidth=0.8, alpha=0.85)
        centroid = grower.fields.to_crs("EPSG:5070").union_all().centroid
        locator.plot(centroid.x, centroid.y, marker="*", color="#111111", markersize=9, zorder=6)
        locator.annotate(
            state_code,
            xy=(centroid.x, centroid.y),
            xytext=(-30 if state_code == "NE" else 10, 4),
            textcoords="offset points",
            fontsize=10,
            fontweight="bold",
            color=grower.color,
        )
    locator.set_title("CONUS locator\n30 fields, 3 states", fontsize=11)
    locator.set_axis_off()

    axes = [fig.add_subplot(grid[0, idx + 1]) for idx in range(len(growers))]
    for ax, grower in zip(axes, growers):
        state_fips = str(grower.fields["state_fips"].iloc[0]).split(".")[0].zfill(2)
        state_counties = counties[counties["state_fips"].astype(str).str.zfill(2) == state_fips]
        state_shape = states[states["state_fips"].astype(str).str.zfill(2) == state_fips]
        fields = grower.fields.to_crs("EPSG:5070")
        minx, miny, maxx, maxy = fields.total_bounds
        span = max(maxx - minx, maxy - miny)
        pad = max(span * 0.28, 5000.0)
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        xspan = (maxx - minx) + 2 * pad
        yspan = (maxy - miny) + 2 * pad
        target_ratio = 0.92  # panel height / width in the figure grid
        if yspan / xspan > target_ratio:
            xspan = yspan / target_ratio
        else:
            yspan = xspan * target_ratio
        ax.set_xlim(cx - xspan / 2, cx + xspan / 2)
        ax.set_ylim(cy - yspan / 2, cy + yspan / 2)

        state_counties.plot(ax=ax, facecolor="#f7f4ee", edgecolor="#cfc8bb", linewidth=0.5)
        fields.plot(ax=ax, facecolor=grower.color, edgecolor="#1b1b1b", linewidth=1.5, alpha=0.9)
        fields.centroid.plot(ax=ax, color="#111111", markersize=5)

        farm_county = grower.county
        target_county = state_counties[
            state_counties["county_name"].astype(str).str.lower() == farm_county.lower()
        ]
        if len(target_county):
            target_county.boundary.plot(ax=ax, color="#8a2b2b", linewidth=1.8)

        draw_scalebar(ax, 20, left_frac=0.62)
        draw_north_arrow(ax)
        ax.set_title(
            f"{grower.label}: {farm_county} County\n"
            f"{grower.name} | {len(grower.fields)} fields | {grower.fields['area_acres'].sum():,.0f} ac",
            fontsize=11,
        )
        ax.set_axis_off()

        inset = ax.inset_axes([0.03, 0.02, 0.27, 0.30])
        state_shape.plot(ax=inset, facecolor="#e9e4da", edgecolor="#9e978b", linewidth=0.6)
        if len(target_county):
            target_county.plot(ax=inset, facecolor=grower.color, edgecolor="#222222", linewidth=0.6)
        inset.set_axis_off()

    fig.suptitle(
        "Three-grower footprint: Illinois, Iowa, and Nebraska field boundaries",
        fontsize=14,
        fontweight="bold",
        y=0.97,
    )
    fig.subplots_adjust(top=0.78, bottom=0.10, left=0.02, right=0.98)
    fig.text(
        0.5,
        0.015,
        "Field polygons: OpenStreetMap/Overpass. County and state outlines: US Census TIGER (geoadmin). Equal-area EPSG:5070 panels; state insets show the farm county.",
        ha="center",
        fontsize=8,
        color="#6b6b6b",
    )
    fig.savefig(out / "map01_grower_fields_context.png", bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------------
# Analyses
# --------------------------------------------------------------------------


def boundary_analysis(growers: list[GrowerData]) -> tuple[pd.DataFrame, pd.DataFrame]:
    field_rows = []
    for grower in growers:
        for _, row in grower.fields.iterrows():
            field_rows.append(
                {
                    "grower": grower.label,
                    "state": grower.state,
                    "grower_slug": grower.slug,
                    "farm": grower.farm,
                    "county": grower.county,
                    "field_id": row["field_id"],
                    "area_acres": round(float(row["area_acres"]), 2),
                    "perimeter_km": round(float(row["perimeter_km"]), 3),
                    "polsby_popper": round(float(row["polsby_popper"]), 4),
                    "shape_index": round(float(row["shape_index"]), 4),
                }
            )
    fields = pd.DataFrame(field_rows)

    records = []
    for metric in ["area_acres", "polsby_popper"]:
        samples = [
            fields.loc[fields["grower"] == g.label, metric].to_numpy() for g in growers
        ]
        h_stat, p_value = stats.kruskal(*samples)
        records.append(
            {
                "test": "kruskal_wallis",
                "metric": metric,
                "group_a": "all growers",
                "group_b": "",
                "n_a": int(sum(len(s) for s in samples)),
                "n_b": 0,
                "statistic": round(float(h_stat), 4),
                "p_value": p_value,
                "p_adjusted": p_value,
                "effect_size": "",
                "interpretation": (
                    "distributions differ across growers"
                    if p_value < 0.05
                    else "no detectable difference across growers"
                ),
            }
        )
        pairs = []
        for i in range(len(growers)):
            for j in range(i + 1, len(growers)):
                a = fields.loc[fields["grower"] == growers[i].label, metric]
                b = fields.loc[fields["grower"] == growers[j].label, metric]
                u_stat, p_pair = stats.mannwhitneyu(a, b, alternative="two-sided")
                pairs.append(
                    {
                        "test": "mann_whitney_u",
                        "metric": metric,
                        "group_a": growers[i].label,
                        "group_b": growers[j].label,
                        "n_a": int(len(a)),
                        "n_b": int(len(b)),
                        "statistic": round(float(u_stat), 3),
                        "p_value": p_pair,
                        "effect_size": round(rank_biserial(u_stat, len(a), len(b)), 3),
                    }
                )
        adjusted = holm_adjust([row["p_value"] for row in pairs])
        for row, padj in zip(pairs, adjusted):
            row["p_adjusted"] = padj
            row["interpretation"] = (
                f"{row['group_a']} vs {row['group_b']}: "
                + ("difference survives Holm correction" if padj < 0.05 else "not significant after correction")
            )
            records.append(row)
    tests = pd.DataFrame(records)

    summary = (
        fields.groupby("grower")[["area_acres", "perimeter_km", "polsby_popper", "shape_index"]]
        .agg(["median", "mean", "std", "min", "max"])
        .round(3)
    )
    return fields, tests, summary


def weather_analysis(growers: list[GrowerData], seasons: pd.DataFrame) -> pd.DataFrame:
    records = []
    for grower in growers:
        subset = seasons[seasons["grower"] == grower.label]
        if len(subset) < 3:
            continue
        rho, p_value = stats.spearmanr(subset["gdd_total"], subset["precip_mm"])
        records.append(
            {
                "test": "spearman_correlation",
                "comparison": grower.label,
                "metric": "seasonal_gdd_vs_precip",
                "statistic": round(float(rho), 4),
                "p_value": p_value,
                "effect_size": round(float(rho), 4),
                "n": int(len(subset)),
                "detail": "field-year pairs, 2021-2025",
            }
        )
    samples = [seasons.loc[seasons["grower"] == g.label, "gdd_total"].to_numpy() for g in growers]
    h_stat, p_value = stats.kruskal(*samples)
    records.append(
        {
            "test": "kruskal_wallis",
            "comparison": "all growers",
            "metric": "seasonal_gdd",
            "statistic": round(float(h_stat), 4),
            "p_value": p_value,
            "effect_size": "",
            "n": int(sum(len(s) for s in samples)),
            "detail": "field-year seasonal GDD",
        }
    )
    samples = [seasons.loc[seasons["grower"] == g.label, "precip_mm"].to_numpy() for g in growers]
    h_stat, p_value = stats.kruskal(*samples)
    records.append(
        {
            "test": "kruskal_wallis",
            "comparison": "all growers",
            "metric": "seasonal_precip",
            "statistic": round(float(h_stat), 4),
            "p_value": p_value,
            "effect_size": "",
            "n": int(sum(len(s) for s in samples)),
            "detail": "field-year seasonal precipitation",
        }
    )
    trend = (
        seasons.groupby(["grower", "year"])[["gdd_total", "precip_mm"]]
        .mean()
        .reset_index()
    )
    for _, row in trend.iterrows():
        records.append(
            {
                "test": "yearly_mean",
                "comparison": f"{row['grower']} {int(row['year'])}",
                "metric": "seasonal_gdd",
                "statistic": round(float(row["gdd_total"]), 1),
                "p_value": "",
                "effect_size": "",
                "n": int((seasons["grower"] == row["grower"]).sum()),
                "detail": f"seasonal precip {row['precip_mm']:.1f} mm",
            }
        )
    return pd.DataFrame(records)


def cdl_analysis(growers: list[GrowerData], crops: pd.DataFrame, seasons: pd.DataFrame) -> pd.DataFrame:
    records = []
    contingency = (
        crops.groupby(["grower", "dominant_crop"]).size().unstack(fill_value=0)
    )
    contingency = contingency.reindex(columns=CROP_ORDER, fill_value=0)
    if contingency.to_numpy().sum() == 0:
        raise RuntimeError("CDL crop classes are empty; check the per-year CDL tables")
    chi2, p_value, dof, _ = stats.chi2_contingency(contingency.to_numpy())
    n = int(contingency.to_numpy().sum())
    cramers_v = math.sqrt(chi2 / (n * (min(contingency.shape) - 1)))
    records.append(
        {
            "test": "chi_square",
            "comparison": "crop mix across growers",
            "metric": "dominant_crop",
            "statistic": round(float(chi2), 4),
            "p_value": p_value,
            "effect_size": round(float(cramers_v), 4),
            "n": n,
            "detail": f"dof={int(dof)}; field-year dominant CDL class",
        }
    )

    merged = crops.merge(
        seasons[["field_id", "year", "gdd_total", "precip_mm"]],
        on=["field_id", "year"],
        how="inner",
    )
    if len(merged) >= 5:
        rho, p_value = stats.spearmanr(merged["corn_share"], merged["gdd_total"])
        records.append(
            {
                "test": "spearman_correlation",
                "comparison": "all growers",
                "metric": "corn_share_vs_gdd",
                "statistic": round(float(rho), 4),
                "p_value": p_value,
                "effect_size": round(float(rho), 4),
                "n": int(len(merged)),
                "detail": "field-years where CDL and weather both cover the year (2021-2023)",
            }
        )
        for grower in growers:
            subset = merged[merged["grower"] == grower.label]
            if len(subset) < 5:
                continue
            rho, p_value = stats.spearmanr(subset["corn_share"], subset["gdd_total"])
            records.append(
                {
                    "test": "spearman_correlation",
                    "comparison": grower.label,
                    "metric": "corn_share_vs_gdd",
                    "statistic": round(float(rho), 4),
                    "p_value": p_value,
                    "effect_size": round(float(rho), 4),
                    "n": int(len(subset)),
                    "detail": "field-years, 2021-2023 overlap",
                }
            )
    for grower in growers:
        subset = crops[crops["grower"] == grower.label]
        records.append(
            {
                "test": "yearly_mean",
                "comparison": grower.label,
                "metric": "corn_share",
                "statistic": round(float(subset["corn_share"].mean()) * 100, 1),
                "p_value": "",
                "effect_size": "",
                "n": int(len(subset)),
                "detail": "mean percent of field area in corn, 2019-2023",
            }
        )
    return pd.DataFrame(records)


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def jpeg_data_uri(path: Path, quality: int = 82) -> str:
    from PIL import Image

    with Image.open(path) as image:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def table_html(frame: pd.DataFrame, cols: list[str] | None = None, floats: int = 3) -> str:
    view = frame[cols] if cols else frame
    return view.to_html(
        index=False, border=0, classes="tbl", float_format=lambda v: f"{v:.{floats}f}"
    )


def write_report(
    out: Path,
    growers: list[GrowerData],
    fields: pd.DataFrame,
    boundary_tests: pd.DataFrame,
    boundary_summary: pd.DataFrame,
    weather_tests: pd.DataFrame,
    cdl_tests: pd.DataFrame,
    seasons: pd.DataFrame,
    crops: pd.DataFrame,
) -> None:
    total_fields = len(fields)
    total_acres = fields["area_acres"].sum()
    cdl_years = sorted(crops["year"].unique())

    boundary_kw = boundary_tests[
        (boundary_tests["test"] == "kruskal_wallis") & (boundary_tests["metric"] == "area_acres")
    ].iloc[0]
    shape_kw = boundary_tests[
        (boundary_tests["test"] == "kruskal_wallis") & (boundary_tests["metric"] == "polsby_popper")
    ].iloc[0]
    area_pair = boundary_tests[
        (boundary_tests["test"] == "mann_whitney_u")
        & (boundary_tests["metric"] == "area_acres")
        & (boundary_tests["group_a"] == "IL")
        & (boundary_tests["group_b"] == "NE")
    ]
    smallest = fields.sort_values("area_acres").iloc[0]
    largest = fields.sort_values("area_acres", ascending=False).iloc[0]

    gdd_by_grower = seasons.groupby("grower")["gdd_total"].agg(["min", "max", "mean"]).round(0)
    precip_by_grower = seasons.groupby("grower")["precip_mm"].mean().round(0)
    corn_by_grower = crops.groupby("grower")["corn_share"].mean().mul(100).round(1)
    soy_by_grower = crops.groupby("grower")["soybeans_share"].mean().mul(100).round(1)
    driest = precip_by_grower.idxmin()
    gdd_order = gdd_by_grower["mean"].idxmax()

    weather_kw = weather_tests[weather_tests["metric"] == "seasonal_gdd"].iloc[0]
    precip_kw = weather_tests[weather_tests["metric"] == "seasonal_precip"].iloc[0]
    corr_rows = weather_tests[weather_tests["test"] == "spearman_correlation"]
    corr_text = "; ".join(
        f"{row['comparison']}: rho={row['statistic']:.2f} (p={row['p_value']:.3f})"
        for _, row in corr_rows.iterrows()
    )

    chi_row = cdl_tests[cdl_tests["test"] == "chi_square"].iloc[0]
    corn_gdd = cdl_tests[
        (cdl_tests["test"] == "spearman_correlation") & (cdl_tests["comparison"] == "all growers")
    ]
    corn_text = (
        f"Overall corn share vs seasonal GDD: rho={corn_gdd['statistic'].iloc[0]:.2f} "
        f"(p={corn_gdd['p_value'].iloc[0]:.3f}, n={int(corn_gdd['n'].iloc[0])})."
        if len(corn_gdd)
        else "Corn share vs GDD not computed."
    )

    grower_rows = "".join(
        f"<tr><td><strong>{g.label}</strong></td><td>{g.name}</td><td>{g.county} County</td>"
        f"<td>{len(g.fields)}</td><td>{g.fields['area_acres'].sum():,.0f}</td>"
        f"<td>{g.fields['area_acres'].median():.1f}</td>"
        f"<td>{g.weather_years[0]}-{g.weather_years[-1]}</td></tr>"
        for g in growers
    )

    figures = [
        (
            "fig01_boundary_area_distribution.png",
            "1. Field size distribution",
            "Areas span three orders of magnitude and the distributions overlap heavily, so the "
            f"cross-grower Kruskal-Wallis result is not significant (p={boundary_kw['p_value']:.2f}). "
            f"Medians differ (IL {boundary_summary.loc['IL', ('area_acres', 'median')]:.0f} ac, "
            f"IA {boundary_summary.loc['IA', ('area_acres', 'median')]:.0f} ac, "
            f"NE {boundary_summary.loc['NE', ('area_acres', 'median')]:.0f} ac) but a "
            f"{smallest['area_acres']:.1f}-acre {smallest['grower']} meadow polygon and a "
            f"{largest['area_acres']:.0f}-acre {largest['grower']} field drive the tails. "
            "Compare acre-weighted totals, not field counts.",
        ),
        (
            "fig02_boundary_shape_vs_area.png",
            "2. Field shape vs size",
            "Compactness rises with area: small parcels inherit road-frontage geometry, larger "
            "parcels approach section-line rectangles (shape index near 1.13). "
            f"Kruskal-Wallis on compactness: H={shape_kw['statistic']:.2f}, p={shape_kw['p_value']:.2f}, "
            "so shape differences are descriptive rather than statistically separable at n=10.",
        ),
        (
            "fig03_weather_seasonal_gdd.png",
            "3. Seasonal growing degree days",
            f"Seasonal GDD (base 10 degC, Apr-Sep) separates growers clearly "
            f"(H={weather_kw['statistic']:.1f}, p={weather_kw['p_value']:.1e}). "
            f"{gdd_order} averages {gdd_by_grower.loc[gdd_order, 'mean']:.0f} GDD "
            f"(range {gdd_by_grower.loc[gdd_order, 'min']:.0f}-{gdd_by_grower.loc[gdd_order, 'max']:.0f}), "
            "the highest of the three sites in every year, while field-to-field spread stays modest.",
        ),
        (
            "fig04_weather_cumulative_precip.png",
            "4. Growing-season precipitation",
            f"Seasonal precipitation also separates growers (H={precip_kw['statistic']:.1f}, "
            f"p={precip_kw['p_value']:.1e}). {driest} is the driest site on average "
            f"({precip_by_grower.loc[driest]:.0f} mm versus "
            f"{precip_by_grower.max():.0f} mm at {precip_by_grower.idxmax()}), and 2024 is visibly "
            "the wettest year in all three states.",
        ),
        (
            "fig05_cdl_crop_composition.png",
            "5. CDL crop composition",
            f"Corn is the largest single crop everywhere, but the split is uneven: "
            f"NE {corn_by_grower.loc['NE']:.0f}% corn / {soy_by_grower.loc['NE']:.0f}% soybean "
            f"versus IL {corn_by_grower.loc['IL']:.0f}% / {soy_by_grower.loc['IL']:.0f}% and "
            f"IA {corn_by_grower.loc['IA']:.0f}% / {soy_by_grower.loc['IA']:.0f}%. 'Other' is a "
            "small residual, so the comparison is effectively corn-soybean rotation intensity.",
        ),
        (
            "fig06_cdl_rotation_heatmap.png",
            "6. Field-level crop sequence",
            "The heatmap exposes within-field rotation behavior: most rows alternate corn and "
            "soybean, while a few fields stay in corn for consecutive years or hold pasture. "
            "This is the within-field level of the analysis.",
        ),
    ]

    figure_html = "\n".join(
        f"""
    <section class="card">
      <h3>{title}</h3>
      <img alt="{title}" src="{jpeg_data_uri(out / name)}" />
      <p>{caption}</p>
    </section>"""
        for name, title, caption in figures
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Field-level EDA: Illinois, Iowa, Nebraska</title>
<style>
  :root {{ --ink:#1d2329; --muted:#5f6b76; --line:#e2e6ea; --bg:#f7f8f9; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         line-height:1.55; }}
  header {{ background:#1f3b57; color:#fff; padding:34px 8vw 26px; }}
  header h1 {{ margin:0 0 6px; font-size:26px; }}
  header p {{ margin:0; color:#cfdae4; font-size:14px; }}
  main {{ max-width:1080px; margin:0 auto; padding:26px 22px 60px; }}
  h2 {{ font-size:19px; margin:34px 0 12px; border-bottom:2px solid var(--line); padding-bottom:6px; }}
  h3 {{ font-size:15px; margin:0 0 10px; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:10px;
           padding:16px 18px; margin:14px 0; }}
  .card img {{ width:100%; height:auto; border-radius:6px; border:1px solid #eef1f3; }}
  .card p {{ color:var(--muted); font-size:13.5px; margin:10px 0 0; }}
  table.tbl {{ border-collapse:collapse; width:100%; font-size:12.5px; background:#fff; }}
  table.tbl th {{ text-align:left; background:#eef2f5; padding:7px 9px; border-bottom:1px solid var(--line); }}
  table.tbl td {{ padding:6px 9px; border-bottom:1px solid #f0f2f4; }}
  .meta {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; }}
  .pill {{ background:#eaf0f5; border-radius:999px; padding:5px 12px; font-size:12.5px; color:#33475b; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; }}
  .kpi {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
  .kpi b {{ display:block; font-size:22px; }}
  .kpi span {{ color:var(--muted); font-size:12.5px; }}
  footer {{ color:var(--muted); font-size:12px; border-top:1px solid var(--line); margin-top:30px; padding-top:14px; }}
  code {{ background:#eef2f5; padding:1px 5px; border-radius:4px; font-size:12px; }}
</style>
</head>
<body>
<header>
  <h1>Field-level EDA and spatial comparison</h1>
  <p>Three growers, three states, 30 fields: boundaries, NASA POWER weather, and USDA CDL cropland (2019-2023) and weather (2021-2025).</p>
</header>
<main>
  <div class="grid">
    <div class="kpi"><b>{total_fields}</b><span>fields analysed</span></div>
    <div class="kpi"><b>{total_acres:,.0f}</b><span>total acres</span></div>
    <div class="kpi"><b>{len(growers)}</b><span>growers / states</span></div>
    <div class="kpi"><b>{len(cdl_years)}</b><span>CDL years ({cdl_years[0]}-{cdl_years[-1]})</span></div>
  </div>

  <h2>Dataset</h2>
  <table class="tbl">
    <thead><tr><th>Grower</th><th>Farm</th><th>County</th><th>Fields</th><th>Acres</th><th>Median field (ac)</th><th>Weather</th></tr></thead>
    <tbody>{grower_rows}</tbody>
  </table>
  <p class="card">Field polygons come from OpenStreetMap/Overpass through the data pipeline county bootstrap.
  Weather is NASA POWER daily data sampled at each field centroid. Cropland classes are USDA CDL 30 m
  compositions per field-year. Soil is intentionally out of scope for this assignment.</p>

  <h2>Spatial context</h2>
  <section class="card">
    <img alt="Grower footprint map" src="{jpeg_data_uri(out / "map01_grower_fields_context.png")}" />
    <p>Left: CONUS locator with the three states highlighted. Right: one equal-area panel per
    grower with 20 km scale bars, field polygons, and a state inset showing the farm county.
    The red outline marks the farm's home county.</p>
  </section>

  <h2>Field boundaries</h2>
  {figure_html}

  <h2>Comparisons and correlations</h2>
  <h3>Boundary comparison</h3>
  <p>{boundary_kw['interpretation'].capitalize()} (Kruskal-Wallis H={boundary_kw['statistic']:.2f},
  p={boundary_kw['p_value']:.3f}). {area_pair.iloc[0]['interpretation'] if len(area_pair) else ''}.</p>
  {table_html(boundary_tests, ["test","metric","group_a","group_b","n_a","n_b","statistic","p_value","p_adjusted","effect_size"])}
  <h3>Weather comparison</h3>
  <p>{corr_text}. Winter-to-summer heat accumulation is the dominant separator between the three sites.</p>
  {table_html(weather_tests[weather_tests["test"] != "yearly_mean"], ["test","comparison","metric","statistic","p_value","effect_size","n","detail"])}
  <h3>CDL comparison</h3>
  <p>Crop-mix chi-square: chi2={chi_row['statistic']:.2f}, p={chi_row['p_value']:.3f},
  Cramer's V={chi_row['effect_size']:.2f} (n={int(chi_row['n'])} field-years). {corn_text}</p>
  {table_html(cdl_tests[cdl_tests["test"] != "yearly_mean"], ["test","comparison","metric","statistic","p_value","effect_size","n","detail"])}

  <h2>Levels of comparison</h2>
  <div class="card">
    <p><strong>Within a field:</strong> crop sequence by year (figure 6) and year-to-year weather at the
    same centroid (figures 3-4). <strong>Across fields within a grower:</strong> area and shape spread
    (figures 1-2), composition spread (figure 5). <strong>Across growers:</strong> IL vs IA vs NE tests
    above and the three-panel map.</p>
  </div>

  <h2>Limitations</h2>
  <div class="card">
    <p>OSM field polygons are volunteer-mapped, so field counts and shapes are a sample, not a complete
    farm inventory. CDL is 30 m and reports pixel composition rather than management. Weather comes from
    a gridded reanalysis product, not on-farm sensors. CDL covers {cdl_years[0]}-{cdl_years[-1]} while
    weather covers 2021-2025, so cross-category tests use the 2021-2023 overlap. Soil properties are not
    analysed here.</p>
  </div>

  <footer>
    Generated by <code>data-pipeline/src/scripts/reporting/generate_eda_multigrower.py</code>.
    Runtime inputs stay under <code>DATA_PIPELINE_DATA_ROOT</code>; this report and its figures are the
    committed review artifacts for the <code>eda-multigrower</code> subskill.
  </footer>
</main>
</body>
</html>
"""
    (out / "eda_multigrower_report.html").write_text(html, encoding="utf-8")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> None:
    args = parse_args()
    root = resolve_pipeline_root(args.data_root)
    out = Path(args.output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    style()

    growers = load_growers(root, args.grower_slug, args.weather_start_year, args.weather_end_year)
    if len(growers) < 3:
        sys.exit(f"expected at least three growers, found {len(growers)}")

    fields, boundary_tests, boundary_summary = boundary_analysis(growers)

    season_rows = []
    for grower in growers:
        season = season_frame(grower.weather)
        season["grower"] = grower.label
        season["grower_slug"] = grower.slug
        season_rows.append(season)
    seasons = pd.concat(season_rows, ignore_index=True)

    crop_rows = []
    for grower in growers:
        crops = crop_frame(grower.cdl)
        crops["grower"] = grower.label
        crops["grower_slug"] = grower.slug
        crop_rows.append(crops)
    crops = pd.concat(crop_rows, ignore_index=True)

    fig_boundary_area(growers, out)
    fig_boundary_shape(growers, out)
    fig_weather_gdd(growers, seasons, out)
    fig_weather_precip(growers, out)
    fig_crop_composition(crops, out)
    fig_crop_heatmap(growers, crops, out)
    fig_context_map(growers, root, out)

    weather_tests = weather_analysis(growers, seasons)
    cdl_tests = cdl_analysis(growers, crops, seasons)

    fields.to_csv(out / "dataset_field_summary.csv", index=False)
    boundary_tests.to_csv(out / "analysis01_boundary_comparison.csv", index=False)
    boundary_summary.round(3).to_csv(out / "analysis01_boundary_summary.csv")
    weather_tests.to_csv(out / "analysis02_weather_comparison.csv", index=False)
    cdl_tests.to_csv(out / "analysis03_cdl_comparison.csv", index=False)

    write_report(
        out,
        growers,
        fields,
        boundary_tests,
        boundary_summary,
        weather_tests,
        cdl_tests,
        seasons,
        crops,
    )

    sizes = {
        path.name: round(path.stat().st_size / 1024, 1)
        for path in sorted(out.iterdir())
        if path.is_file()
    }
    print(
        json.dumps(
            {
                "growers": {g.label: len(g.fields) for g in growers},
                "fields": int(len(fields)),
                "report": str(out / "eda_multigrower_report.html"),
                "outputs_kb": sizes,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
