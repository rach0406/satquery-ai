"""Multi-date specialists: bi-temporal change analysis and index time series."""
from __future__ import annotations

import concurrent.futures as cf

import numpy as np

from ..agent.context import RunContext
from ..agent.grounding import fact
from ..config import settings
from ..datasources import gibs
from ..processing import change as CH
from ..processing import indices as IX
from ..processing import regions as RG
from ..schemas import ToolResult
from ..utils import render

VERSION = "1.0.0"


def run_change_analyzer(ctx: RunContext, indices: list[str] | None = None,
                        max_regions: int = 6, min_pixels: int = 40) -> ToolResult:
    before = ctx.get("before")
    after = ctx.get("after")
    if before is None or after is None:
        return ToolResult(
            tool="change_analyzer", tool_version=VERSION, status="skipped",
            message="Change analysis needs two scenes; only one is loaded.")

    if before.shape != after.shape:
        return ToolResult(
            tool="change_analyzer", tool_version=VERSION, status="error",
            message=(f"The two scenes are on different grids "
                     f"({before.shape} vs {after.shape}) and cannot be differenced."))

    mask = before.valid & after.valid
    if mask.mean() < 0.02:
        return ToolResult(
            tool="change_analyzer", tool_version=VERSION, status="no_data",
            message=(f"Only {mask.mean() * 100:.1f}% of the area was observed on *both* dates "
                     f"({before.date} and {after.date}), which is too little to compare. "
                     "Cloud cover or a gap in the acquisition schedule is the usual cause."))
    if mask.mean() < 0.5:
        ctx.warn(f"Only {mask.mean() * 100:.0f}% of the AOI was observed on both dates; "
                 "change statistics cover that overlap only.")

    seg_b = ctx.cache.get("seg:before")
    seg_a = ctx.cache.get("seg:after")
    if seg_b is None and "nir" in before.bands:
        seg_b = IX.segment_landcover(before.bands, mask)
        ctx.cache["seg:before"] = seg_b
    if seg_a is None and "nir" in after.bands:
        seg_a = IX.segment_landcover(after.bands, mask)
        ctx.cache["seg:after"] = seg_a

    want = [i.upper() for i in (indices or ctx.plan.indices or ["NDVI", "MNDWI", "NBR", "NDBI"])]
    res = CH.analyse_change(
        before.bands, after.bands, mask, seg_b, seg_a,
        pixel_area_km2=ctx.pixel_area_km2, indices=tuple(want),
    )
    ctx.cache["change"] = res

    src = f"{before.provenance.source} ({before.date}) vs {after.provenance.source} ({after.date})"
    facts = [
        fact(key="change_fraction", label="Share of observed area that changed",
             value=res.changed_fraction, unit="fraction",
             method=f"{res.changed_pixels} of {res.valid_pixels} co-observed pixels; {res.method}",
             tool="change_analyzer", source=src, sample_size=res.valid_pixels),
        fact(key="change_pixels", label="Changed pixels", value=res.changed_pixels,
             unit="pixels", method=res.method, tool="change_analyzer", source=src),
        fact(key="change_threshold", label="CVA change threshold", value=res.threshold,
             method="Otsu cut on the change-vector magnitude histogram",
             tool="change_analyzer", source=src),
        fact(key="coobserved_pixels", label="Pixels observed on both dates",
             value=res.valid_pixels, unit="pixels",
             method="intersection of the two validity masks",
             tool="change_analyzer", source=src),
        fact(key="coobserved_fraction", label="Overlap of the two observations",
             value=float(mask.mean()), unit="fraction",
             method="co-observed pixels / total pixels in the AOI grid",
             tool="change_analyzer", source=src),
    ]
    if ctx.georeferenced:
        facts.append(fact(
            key="change_area_km2", label="Changed area", value=ctx.area_of(res.changed_pixels),
            unit="km2", method=f"{res.changed_pixels} px x {ctx.pixel_area_km2:.6f} km2/px",
            tool="change_analyzer", source=src))

    for name, st in res.index_delta_stats.items():
        for stat, key, lbl in (
            ("mean", "mean", "mean change"), ("before_mean", "before", "mean before"),
            ("after_mean", "after", "mean after"),
            ("fraction_increased", "increased", "share increased"),
            ("fraction_decreased", "decreased", "share decreased"),
        ):
            facts.append(fact(
                key=f"d{name.lower()}_{key}", label=f"{name} {lbl}", value=st[stat],
                unit="fraction" if "fraction" in stat else None,
                method=(f"{name} computed per date, then differenced over "
                        f"{res.valid_pixels} co-observed pixels"),
                tool="change_analyzer", source=src, sample_size=res.valid_pixels))

    for cls, d in res.class_deltas.items():
        facts.append(fact(
            key=f"{cls}_fraction_before", label=f"{IX.CLASS_LABELS[cls]} share before",
            value=d["fraction_before"], unit="fraction",
            method=f"{d['pixels_before']} px on {before.date}",
            tool="change_analyzer", source=src))
        facts.append(fact(
            key=f"{cls}_fraction_after", label=f"{IX.CLASS_LABELS[cls]} share after",
            value=d["fraction_after"], unit="fraction",
            method=f"{d['pixels_after']} px on {after.date}",
            tool="change_analyzer", source=src))
        if ctx.georeferenced:
            facts.append(fact(
                key=f"{cls}_delta_area_km2", label=f"{IX.CLASS_LABELS[cls]} area change",
                value=d["delta_area_km2"], unit="km2",
                method=(f"{d['area_after_km2']} km2 on {after.date} minus "
                        f"{d['area_before_km2']} km2 on {before.date}"),
                tool="change_analyzer", source=src))
        if d.get("relative_change_pct") is not None:
            facts.append(fact(
                key=f"{cls}_relative_change_pct",
                label=f"{IX.CLASS_LABELS[cls]} relative change",
                value=d["relative_change_pct"], unit="percent",
                method=f"({d['pixels_after']} - {d['pixels_before']}) / {d['pixels_before']} x 100",
                tool="change_analyzer", source=src))

    regs = CH.largest_change_regions(res.change_mask, ctx.bbox or [0, 0, 1, 1],
                                     res.direction, max_regions=max_regions,
                                     min_pixels=min_pixels)
    for r in regs[:3]:
        facts.append(fact(
            key=f"change_region{r['rank']}_area_km2" if ctx.georeferenced
            else f"change_region{r['rank']}_pixels",
            label=f"Change region #{r['rank']} size",
            value=RG.region_size(r, ctx.georeferenced), unit=ctx.area_unit(),
            method=("connected component of the change mask, centroid "
                    f"{RG.region_location(r)}"),
            tool="change_analyzer", source=src))

    # ---- artefacts ------------------------------------------------------
    arts = [
        render.image_artifact(
            render.stamp_scene(before.rgb, np.where(before.valid, 255, 0).astype(np.uint8)),
            f"Before - {before.label}", before.bbox,
            description=f"Acquired {before.date}.", provenance=before.provenance,
            kind="image_overlay", prefix="before"),
        render.image_artifact(
            render.stamp_scene(after.rgb, np.where(after.valid, 255, 0).astype(np.uint8)),
            f"After - {after.label}", after.bbox,
            description=f"Acquired {after.date}.", provenance=after.provenance,
            kind="image_overlay", prefix="after"),
        render.image_artifact(
            CH.colorise_change(res.change_mask, res.direction, mask),
            f"Change map {before.date} -> {after.date}", ctx.bbox,
            description=(f"{res.method}. Blue = index increased, red = index decreased."),
            legend=[{"label": "Increase", "color": "rgb(57,135,229)"},
                    {"label": "Decrease", "color": "rgb(217,89,38)"}],
            prefix="change"),
        render.image_artifact(
            IX.colorise_index(res.magnitude, mask, 0.0, float(max(res.magnitude[mask].max(), 0.1)),
                              "magma"),
            "Change magnitude (CVA)", ctx.bbox,
            description="Euclidean distance between the two dates in band space.",
            colormap="magma",
            legend=render.ramp_legend(0.0, float(max(res.magnitude[mask].max(), 0.1)), "magma"),
            prefix="cvamag"),
    ]

    if res.transitions:
        changed_rows = [t for t in res.transitions if t["is_change"]][:8]
        if changed_rows:
            arts.append(render.bar_chart(
                "Largest land-cover transitions",
                [f"{IX.CLASS_LABELS[t['from']]} -> {IX.CLASS_LABELS[t['to']]}"
                 for t in changed_rows],
                [RG.region_size(t, ctx.georeferenced) for t in changed_rows],
                ylabel=f"Area ({ctx.area_unit()})",
                description="Per-pixel class transitions between the two dates."))
            arts.append(render.table_artifact(
                "Land-cover transition matrix",
                [{"key": "from", "label": "From"}, {"key": "to", "label": "To"},
                 {"key": "area_km2", "label": f"Area ({ctx.area_unit()})"},
                 {"key": "pixels", "label": "Pixels"},
                 {"key": "pct", "label": "% of scene"}],
                [{"from": IX.CLASS_LABELS[t["from"]], "to": IX.CLASS_LABELS[t["to"]],
                  "area_km2": RG.region_size(t, ctx.georeferenced),
                  "pixels": t["pixels"], "pct": round(t["fraction_of_scene"] * 100, 3)}
                 for t in res.transitions if t["is_change"]][:12]))

    if res.class_deltas:
        names = [IX.CLASS_LABELS[c] for c in res.class_deltas]
        arts.append(render.grouped_bar_chart(
            "Land-cover composition: before vs after", names,
            [{"name": f"Before ({before.date})",
              "y": [round(d["fraction_before"] * 100, 2) for d in res.class_deltas.values()],
              "color": "#d95926"},
             {"name": f"After ({after.date})",
              "y": [round(d["fraction_after"] * 100, 2) for d in res.class_deltas.values()],
              "color": "#3987e5"}],
            ylabel="% of co-observed area"))

    for name, st in res.index_delta_stats.items():
        arts.append(render.histogram_chart(
            f"Δ{name} distribution", st["histogram"], st["bin_edges"],
            xlabel=f"{name} change ({before.date} → {after.date})", color="#3987e5",
            marker_lines=[{"x": st["mean"], "label": f"mean {st['mean']:+.3f}",
                           "color": "#d95926"}]))
        if name in res.index_deltas:
            arts.append(render.image_artifact(
                IX.colorise_index(res.index_deltas[name], mask, -0.6, 0.6, "coolwarm"),
                f"Δ{name} map", ctx.bbox,
                description=f"{name} on {after.date} minus {name} on {before.date}.",
                colormap="coolwarm",
                legend=render.ramp_legend(-0.6, 0.6, "coolwarm"), prefix=f"d{name.lower()}"))

    if regs:
        arts.append(render.boxes_artifact(
            f"Largest change regions ({len(regs)})", regs, ctx.bbox,
            description="Connected components of the change mask, ranked by area."))
        arts.append(render.table_artifact(
            "Change regions",
            [{"key": "rank", "label": "#"},
             {"key": "area_km2", "label": f"Area ({ctx.area_unit()})"},
             {"key": "direction", "label": "Direction"},
             {"key": "mean_delta", "label": "Mean Δ"},
             {"key": "centroid", "label": "Centroid (lon, lat)"}],
            [{"rank": r["rank"],
              "area_km2": r["area_km2"] if ctx.georeferenced else r["pixels"],
              "direction": r.get("direction", "-"), "mean_delta": r.get("mean_delta", "-"),
              "centroid": f"{r['centroid'][0]:.4f}, {r['centroid'][1]:.4f}"} for r in regs]))

    return ToolResult(
        tool="change_analyzer", tool_version=VERSION, status="ok",
        message=(f"{res.changed_fraction * 100:.2f}% of the co-observed area changed between "
                 f"{before.date} and {after.date} ({res.changed_pixels:,} pixels)."),
        facts=facts, artifacts=arts,
        provenance=[before.provenance, after.provenance], confidence=0.78,
        parameters={"indices": list(res.index_delta_stats.keys()),
                    "cva_threshold": round(res.threshold, 5),
                    "max_regions": max_regions, "min_pixels": min_pixels},
    )


# --------------------------------------------------------------------------
# Time series
# --------------------------------------------------------------------------
def run_timeseries_analyzer(ctx: RunContext, steps: int = 8, interval_days: int = 30,
                            index: str = "NDVI") -> ToolResult:
    from datetime import date, timedelta

    bbox = ctx.bbox
    if not bbox:
        return ToolResult(tool="timeseries_analyzer", tool_version=VERSION, status="skipped",
                          message="A time series needs a geographic area of interest.")

    index = index.upper()
    anchor_iso = (ctx.plan.dates[-1] if ctx.plan.dates
                  else (date.today() - timedelta(days=5)).isoformat())
    anchor = date.fromisoformat(anchor_iso)
    targets = [(anchor - timedelta(days=interval_days * k)).isoformat()
               for k in range(steps - 1, -1, -1)]

    size = min(settings.default_raster_size, 256)

    def one(d: str):
        try:
            bands, rasters, valid = gibs.fetch_cube(bbox, d, size=size)
            if valid.mean() < 0.25:
                return {"date": d, "status": "low_coverage",
                        "coverage": round(float(valid.mean()), 4)}
            arr = IX.compute_index(index, bands)
            st = IX.index_stats(arr, valid, index, bins=20)
            return {"date": d, "status": "ok", "mean": st.mean, "median": st.median,
                    "p10": st.p10, "p90": st.p90, "std": st.std,
                    "coverage": round(float(valid.mean()), 4),
                    "valid_pixels": st.valid_pixels,
                    "source": rasters[0].provenance.source,
                    "provenance": rasters[0].provenance}
        except KeyError as exc:
            return {"date": d, "status": "unavailable_index", "error": str(exc)}
        except Exception as exc:
            return {"date": d, "status": "no_data", "error": str(exc)[:180]}

    with cf.ThreadPoolExecutor(max_workers=settings.max_parallel_fetch) as ex:
        rows = list(ex.map(one, targets))
    rows.sort(key=lambda r: r["date"])

    ok = [r for r in rows if r["status"] == "ok"]
    if len(ok) < 3:
        return ToolResult(
            tool="timeseries_analyzer", tool_version=VERSION, status="no_data",
            message=(f"Only {len(ok)} of {len(rows)} requested dates had a usable "
                     f"cloud-free observation of this area, which is not enough for a trend. "
                     f"Dates attempted: {[r['date'] for r in rows]}."))

    provs = []
    for r in ok:
        p = r.pop("provenance", None)
        if p is not None and not provs:
            provs.append(p)

    xs = np.arange(len(ok), dtype=float)
    ys = np.array([r["mean"] for r in ok], dtype=float)
    slope, intercept = np.polyfit(xs, ys, 1)
    pred = slope * xs + intercept
    ss_res = float(((ys - pred) ** 2).sum())
    ss_tot = float(((ys - ys.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    per_year = slope * (365.0 / interval_days)

    hi = max(ok, key=lambda r: r["mean"])
    lo = min(ok, key=lambda r: r["mean"])
    src = ok[0].get("source", "NASA GIBS")

    facts = [
        fact(key="ts_index", label="Time-series index", value=index,
             method=f"{IX.INDEX_META[index]['name']}", tool="timeseries_analyzer", source=src),
        fact(key="ts_observations", label="Usable observations", value=len(ok), unit="dates",
             method=f"{len(ok)} of {len(rows)} attempted dates had >=25% valid coverage",
             tool="timeseries_analyzer", source=src),
        fact(key="ts_mean", label=f"Mean {index} across the series",
             value=float(ys.mean()), method=f"mean of {len(ok)} per-date scene means",
             tool="timeseries_analyzer", source=src, sample_size=len(ok)),
        fact(key="ts_first", label=f"{index} at series start ({ok[0]['date']})",
             value=ok[0]["mean"], method="scene mean on the earliest usable date",
             tool="timeseries_analyzer", source=src),
        fact(key="ts_last", label=f"{index} at series end ({ok[-1]['date']})",
             value=ok[-1]["mean"], method="scene mean on the latest usable date",
             tool="timeseries_analyzer", source=src),
        fact(key="ts_net_change", label=f"Net {index} change over the series",
             value=ok[-1]["mean"] - ok[0]["mean"],
             method=f"{index} on {ok[-1]['date']} minus {index} on {ok[0]['date']}",
             tool="timeseries_analyzer", source=src),
        fact(key="ts_slope_per_step", label=f"{index} trend per {interval_days}-day step",
             value=float(slope), method="ordinary least squares fit over the usable dates",
             tool="timeseries_analyzer", source=src, sample_size=len(ok)),
        fact(key="ts_slope_per_year", label=f"{index} trend per year", value=float(per_year),
             method=f"OLS slope scaled by 365/{interval_days}",
             tool="timeseries_analyzer", source=src),
        fact(key="ts_r2", label="Trend fit R²", value=float(r2),
             method="coefficient of determination of the OLS fit",
             tool="timeseries_analyzer", source=src),
        fact(key="ts_max", label=f"Highest {index} ({hi['date']})", value=hi["mean"],
             method="maximum of the per-date scene means",
             tool="timeseries_analyzer", source=src),
        fact(key="ts_min", label=f"Lowest {index} ({lo['date']})", value=lo["mean"],
             method="minimum of the per-date scene means",
             tool="timeseries_analyzer", source=src),
    ]

    arts = [
        render.line_chart(
            f"{index} time series - {ctx.plan.aoi_name or 'AOI'}",
            [r["date"] for r in ok],
            [{"name": f"{index} scene mean", "y": [round(r["mean"], 4) for r in ok],
              "color": "#3987e5", "mode": "lines+markers"},
             {"name": "P10-P90 band", "y": [round(r["p10"], 4) for r in ok],
              "y_upper": [round(r["p90"], 4) for r in ok], "color": "#3987e5",
              "fill": True, "opacity": 0.18},
             {"name": "OLS trend", "y": [round(float(v), 4) for v in pred],
              "color": "#d95926", "dash": "dash", "mode": "lines"}],
            ylabel=index, xlabel="Acquisition date",
            description=(f"{len(ok)} usable observations of {len(rows)} attempted. "
                         f"Trend {per_year:+.4f} {index}/year, R² {r2:.3f}.")),
        render.table_artifact(
            f"{index} per-date observations",
            [{"key": "date", "label": "Date"}, {"key": "status", "label": "Status"},
             {"key": "mean", "label": f"{index} mean"}, {"key": "p10", "label": "P10"},
             {"key": "p90", "label": "P90"}, {"key": "coverage", "label": "Coverage"},
             {"key": "valid_pixels", "label": "Valid px"}],
            [{"date": r["date"], "status": r["status"],
              "mean": round(r["mean"], 4) if r["status"] == "ok" else "-",
              "p10": round(r["p10"], 4) if r["status"] == "ok" else "-",
              "p90": round(r["p90"], 4) if r["status"] == "ok" else "-",
              "coverage": r.get("coverage", "-"), "valid_pixels": r.get("valid_pixels", "-")}
             for r in rows],
            description="Dates without a usable observation are listed explicitly rather "
                        "than interpolated."),
    ]

    skipped = [r["date"] for r in rows if r["status"] != "ok"]
    if skipped:
        ctx.warn(f"{len(skipped)} date(s) had no usable observation and were excluded "
                 f"from the trend: {', '.join(skipped)}.")

    return ToolResult(
        tool="timeseries_analyzer", tool_version=VERSION, status="ok",
        message=(f"Built a {len(ok)}-point {index} series; trend {per_year:+.4f}/year "
                 f"(R²={r2:.2f})."),
        facts=facts, artifacts=arts, provenance=provs, confidence=min(0.9, 0.4 + 0.06 * len(ok)),
        parameters={"steps": steps, "interval_days": interval_days, "index": index,
                    "raster_size": size, "dates_attempted": targets},
    )
