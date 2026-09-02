"""Scene acquisition: resolve a plan into real, co-registered pixels.

This is where the controller's duty to "check the number, modality, format,
metadata and compatibility of the input images" is actually discharged. For
archive-sourced imagery that means probing what the sensor really observed
rather than assuming a date is available - Sentinel-1 revisits a given track
every 6-12 days, and an optical sensor sees nothing useful through a monsoon
cloud deck.

Every probe is logged and surfaced in the execution trace.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np

from ..config import settings
from ..datasources import gibs, imagery_io
from ..schemas import DataOrigin, InputConfiguration, Provenance, QueryPlan
from .context import RunContext, SceneData


class AcquisitionError(RuntimeError):
    """No real data could be obtained. Never a reason to invent any."""

    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.detail = detail or {}


def _default_date() -> str:
    return (date.today() - timedelta(days=5)).isoformat()


def _scene_from_cube(role: str, bbox: list[float], iso_date: str, size: int,
                     ) -> tuple[SceneData, list[dict]]:
    bands, rasters, valid = gibs.fetch_cube(bbox, iso_date, size=size)
    tc = rasters[0]
    label = f"{tc.layer.platform} {tc.layer.instrument} {iso_date}"
    scene = SceneData(
        role=role, label=label, rgb=tc.array, bands=bands, valid=valid,
        modality="multispectral", provenance=tc.provenance, bbox=list(bbox),
        date=iso_date,
        metadata={
            "layers": [r.layer.id for r in rasters],
            "resolution_m": tc.layer.resolution_m,
            "bands": sorted(bands.keys()),
            "coverage": round(float(valid.mean()), 4),
        },
    )
    checks = [{
        "check": "optical coverage", "date": iso_date,
        "value": round(float(valid.mean()), 4),
        "result": "pass" if valid.mean() >= 0.25 else "degraded",
    }]
    return scene, checks


def _scene_from_sar(role: str, bbox: list[float], iso_date: str, size: int
                    ) -> tuple[SceneData, list[dict]]:
    r = gibs.fetch_raster("opera_rtc_s1", bbox, iso_date, size=size, min_coverage=0.05)
    scene = SceneData(
        role=role, label=f"Sentinel-1 OPERA RTC {iso_date}",
        rgb=r.array, bands={"vv": r.array[..., 0].astype(np.float32) / 255.0,
                            "vh": r.array[..., 1].astype(np.float32) / 255.0},
        valid=r.valid_mask, modality="sar", provenance=r.provenance,
        bbox=list(bbox), date=iso_date,
        metadata={"layer": r.layer.id, "resolution_m": r.layer.resolution_m,
                  "coverage": round(r.coverage, 4)},
    )
    return scene, [{"check": "SAR coverage", "date": iso_date,
                    "value": round(r.coverage, 4), "result": "pass"}]


def _search_optical(bbox: list[float], anchor: str, span: int = 10,
                    ctx: RunContext | None = None, role: str = "scene"
                    ) -> tuple[str, list[dict]]:
    """Find a date the optical sensors actually saw this AOI *through the cloud*.

    Coverage alone is not usability: a monsoon acquisition can be fully covered
    and fully cloudy. Candidate dates are ranked by clear fraction, and if the
    best available date is still mostly cloud the caller is warned rather than
    silently handed a cloud deck.
    """
    best, clear, log = gibs.find_available_date(
        "modis_terra_truecolor", bbox, anchor, span=span, min_coverage=0.6)
    if best is None or clear < 0.30:
        alt, alt_clear, log2 = gibs.find_available_date(
            "viirs_snpp_truecolor", bbox, anchor, span=span, min_coverage=0.6)
        log = log + log2
        if alt is not None and alt_clear > clear:
            best, clear = alt, alt_clear
    if best is None:
        raise AcquisitionError(
            f"No optical sensor (MODIS Terra/Aqua, VIIRS) had a usable observation of this "
            f"area within ±{span} days of {anchor}.",
            {"probes": log})

    if clear < 0.30 and ctx is not None:
        probe = next((r for r in log if r["date"] == best), None)
        cf_pct = (probe or {}).get("cloud_fraction", 1.0) * 100
        ctx.warn(
            f"Every optical acquisition within ±{span} days of {anchor} was heavily clouded. "
            f"The clearest ({best}) is still {cf_pct:.0f}% cloud, so surface statistics for "
            f"the {role} cover only the remaining clear pixels. SAR would be the appropriate "
            "sensor for this date range.")
    return best, log


def _probe_sar_dates(bbox: list[float], dates: list[str]) -> list[dict]:
    import concurrent.futures as cf

    log: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=max(settings.max_parallel_fetch, 12)) as ex:
        futs = {ex.submit(gibs.probe_coverage, "opera_rtc_s1", bbox, d): d
                for d in dict.fromkeys(dates)}
        for fut in cf.as_completed(futs):
            d = futs[fut]
            try:
                log.append({"date": d, "coverage": round(fut.result(), 4)})
            except Exception:
                log.append({"date": d, "coverage": 0.0})
    log.sort(key=lambda r: r["date"])
    return log


def _search_sar(bbox: list[float], anchor: str, wide_span: int = 150,
                ctx: RunContext | None = None) -> tuple[str, list[dict]]:
    """Find a Sentinel-1 acquisition that really covers this AOI.

    OPERA RTC-S1 is published per orbital track, and global coverage is
    staged rather than uniform: an AOI may have a granule every 12 days for
    months and then nothing for a season. So we search in two phases -
    the exact 12-day repeat cycle first (cheap, usually enough), then a wide
    sweep - and if the best acquisition is far from the requested date we say
    so instead of pretending the pair is simultaneous.
    """
    d0 = date.fromisoformat(anchor)
    today = date.today()

    # Phase 1: the nominal 12-day repeat cycle plus the 6-day complementary track.
    phase1 = gibs.sar_repeat_dates(anchor, count=4, cycle=12)
    phase1 += [(d0 + timedelta(days=k)).isoformat()
               for k in (-6, 6, -18, 18) if d0 + timedelta(days=k) <= today]
    log = _probe_sar_dates(bbox, phase1)
    ok = [r for r in log if r["coverage"] >= 0.5]

    # Phase 2: wide sweep when the local cycle came up empty.
    if not ok:
        sweep = [(d0 + timedelta(days=k)).isoformat()
                 for k in range(-wide_span, wide_span + 1, 3)
                 if d0 + timedelta(days=k) <= today]
        log += _probe_sar_dates(bbox, sweep)
        log.sort(key=lambda r: r["date"])
        ok = [r for r in log if r["coverage"] >= 0.5]

    if not ok:
        best_seen = max((r["coverage"] for r in log), default=0.0)
        raise AcquisitionError(
            f"Sentinel-1 has no OPERA RTC acquisition covering this area within "
            f"±{wide_span} days of {anchor}. {len(log)} candidate dates were probed and the "
            f"best returned only {best_seen * 100:.0f}% coverage. OPERA RTC publication is "
            "track-based and its global rollout is staged, so some areas have long gaps. "
            "Areas with dense recent coverage include the Sundarbans, Chennai, Dubai and "
            "California.",
            {"probes": log[:40], "dates_probed": len(log)})

    ok.sort(key=lambda r: (-r["coverage"], abs((date.fromisoformat(r["date"]) - d0).days)))
    chosen = ok[0]["date"]
    gap = abs((date.fromisoformat(chosen) - d0).days)
    if gap > 20 and ctx is not None:
        ctx.warn(
            f"The nearest Sentinel-1 acquisition covering this area is {chosen}, {gap} days "
            f"from the requested {anchor}. The cross-modal pair is therefore not "
            "near-simultaneous, and genuine surface change across that interval will show up "
            "as sensor disagreement rather than as sensor error.")
    return chosen, log


def _load_stored_scene(scene_id: str, role: str) -> SceneData:
    """Load a previously uploaded or bundled scene by id."""
    for base, origin in ((settings.uploads_dir, DataOrigin.USER_UPLOAD),
                         (settings.scenes_dir, DataOrigin.BUNDLED_SAMPLE)):
        for p in base.glob(f"{scene_id}*"):
            if p.suffix.lower() in imagery_io.SUPPORTED_EXT:
                sc = imagery_io.load_scene_file(p, scene_id=scene_id, origin=origin)
                return SceneData(
                    role=role, label=sc.name, rgb=sc.array, bands=sc.bands,
                    valid=sc.valid_mask, modality=sc.modality, provenance=sc.provenance,
                    bbox=sc.bbox, date=sc.acquisition_date, scene_id=sc.scene_id,
                    metadata=sc.metadata,
                )
    raise AcquisitionError(f"Scene '{scene_id}' was not found in uploads or bundled samples.")


def acquire(ctx: RunContext, plan: QueryPlan, scene_ids: list[str] | None = None
            ) -> list[dict]:
    """Populate ``ctx.scenes``. Returns the compatibility/probe log."""
    log: list[dict] = []
    scene_ids = [s for s in (scene_ids or []) if s]
    size = settings.default_raster_size

    # ---------- user-supplied scenes take priority -----------------------
    if scene_ids:
        if len(scene_ids) == 1:
            sc = _load_stored_scene(scene_ids[0], "primary")
            ctx.add_scene(sc)
            chk = imagery_io.check_single_scene(
                imagery_io.Scene(
                    scene_id=sc.scene_id or "s", name=sc.label, array=sc.rgb, bands=sc.bands,
                    valid_mask=sc.valid, modality=sc.modality, bbox=sc.bbox,
                    acquisition_date=sc.date, provenance=sc.provenance, metadata=sc.metadata),
                task_needs=[])
            ctx.compatibility["single"] = chk
            log.append({"check": "single-scene validation", "result":
                        "pass" if chk["compatible"] else "fail", "detail": chk})
            for w in chk["warnings"]:
                ctx.warn(w)
            if not chk["compatible"]:
                raise AcquisitionError("; ".join(chk["issues"]), chk)
            return log

        a = _load_stored_scene(scene_ids[0], "tmp_a")
        b = _load_stored_scene(scene_ids[1], "tmp_b")
        sa = imagery_io.Scene(scene_id="a", name=a.label, array=a.rgb, bands=a.bands,
                              valid_mask=a.valid, modality=a.modality, bbox=a.bbox,
                              acquisition_date=a.date, provenance=a.provenance, metadata=a.metadata)
        sb = imagery_io.Scene(scene_id="b", name=b.label, array=b.rgb, bands=b.bands,
                              valid_mask=b.valid, modality=b.modality, bbox=b.bbox,
                              acquisition_date=b.date, provenance=b.provenance, metadata=b.metadata)
        chk = imagery_io.check_pair_compatibility(sa, sb)
        ctx.compatibility["pair"] = chk
        log.append({"check": "pair compatibility",
                    "result": "pass" if chk["compatible"] else "fail", "detail": chk})
        for w in chk["warnings"]:
            ctx.warn(w)
        if not chk["compatible"]:
            raise AcquisitionError("; ".join(chk["issues"]), chk)

        if chk["configuration"] == "cross_modal_pair":
            a.role, b.role = ("sar", "optical") if a.modality == "sar" else ("optical", "sar")
            plan.input_configuration = InputConfiguration.CROSS_MODAL
        else:
            # Order by acquisition date when both carry one.
            if a.date and b.date and a.date > b.date:
                a, b = b, a
            a.role, b.role = "before", "after"
            plan.input_configuration = InputConfiguration.BITEMPORAL
        ctx.add_scene(a)
        ctx.add_scene(b)
        return log

    # ---------- archive retrieval ---------------------------------------
    bbox = plan.bbox
    if not bbox:
        raise AcquisitionError(
            "No area of interest could be resolved from the question. Name a place "
            "(for example 'Chennai', 'Sundarbans' or 'Chilika Lake'), or upload an image.")

    config = plan.input_configuration

    if config is InputConfiguration.NONE:
        return log  # the time-series tool fetches its own dates

    if config is InputConfiguration.BITEMPORAL:
        if len(plan.dates) >= 2:
            anchors = [plan.dates[0], plan.dates[-1]]
        elif len(plan.dates) == 1:
            d = date.fromisoformat(plan.dates[0])
            anchors = [(d - timedelta(days=365)).isoformat(), plan.dates[0]]
            ctx.warn("Only one date was given, so the comparison uses the same date one year "
                     "earlier as the baseline.")
        else:
            today = date.fromisoformat(_default_date())
            anchors = [(today - timedelta(days=365)).isoformat(), today.isoformat()]
            ctx.warn("No dates were given, so the comparison uses today versus one year ago.")

        resolved: list[str] = []
        for i, anchor in enumerate(anchors):
            d, probes = _search_optical(bbox, anchor, span=10, ctx=ctx,
                                        role=("before" if i == 0 else "after"))
            log.append({"check": f"optical availability ({'before' if i == 0 else 'after'})",
                        "requested": anchor, "selected": d, "probes": probes,
                        "result": "pass"})
            if d != anchor:
                ctx.warn(f"No usable optical observation on {anchor}; used the nearest "
                         f"clear acquisition on {d} instead.")
            resolved.append(d)

        if resolved[0] == resolved[1]:
            raise AcquisitionError(
                f"Both requested dates resolved to the same usable acquisition ({resolved[0]}), "
                "so there is no temporal difference to analyse. Choose dates further apart.",
                {"resolved": resolved})

        for role, d in zip(("before", "after"), resolved):
            sc, checks = _scene_from_cube(role, bbox, d, size)
            ctx.add_scene(sc)
            log.extend(checks)
        plan.dates = resolved

        a, b = ctx.scenes["before"], ctx.scenes["after"]
        coreg = {
            "same_shape": a.shape == b.shape,
            "same_extent": a.bbox == b.bbox,
            "co_registered": a.shape == b.shape and a.bbox == b.bbox,
            "shared_bands": sorted(set(a.bands) & set(b.bands)),
            "method": "identical WMS BBOX/WIDTH/HEIGHT for both dates",
        }
        ctx.compatibility["bitemporal"] = coreg
        log.append({"check": "bi-temporal co-registration",
                    "result": "pass" if coreg["co_registered"] else "fail", "detail": coreg})
        return log

    if config is InputConfiguration.CROSS_MODAL:
        anchor = plan.dates[-1] if plan.dates else _default_date()
        sar_date, sar_probes = _search_sar(bbox, anchor, ctx=ctx)
        log.append({"check": "SAR availability", "requested": anchor, "selected": sar_date,
                    "probes": sar_probes, "result": "pass"})
        if sar_date != anchor:
            ctx.warn(f"Sentinel-1 did not pass over on {anchor}; used the nearest acquisition "
                     f"on {sar_date}.")

        # Pair the optical scene to the SAR date so the two are near-simultaneous.
        opt_date, opt_probes = _search_optical(bbox, sar_date, span=4, ctx=ctx,
                                              role="optical member of the cross-modal pair")
        log.append({"check": "optical availability (paired to SAR date)",
                    "requested": sar_date, "selected": opt_date, "probes": opt_probes,
                    "result": "pass"})
        gap = abs((date.fromisoformat(opt_date) - date.fromisoformat(sar_date)).days)
        if gap:
            ctx.warn(f"The optical and SAR acquisitions are {gap} day(s) apart "
                     f"({opt_date} vs {sar_date}); genuine surface change within that window "
                     "would appear as sensor disagreement.")

        sar_scene, c1 = _scene_from_sar("sar", bbox, sar_date, size)
        opt_scene, c2 = _scene_from_cube("optical", bbox, opt_date, size)
        ctx.add_scene(sar_scene)
        ctx.add_scene(opt_scene)
        log.extend(c1 + c2)
        plan.dates = sorted({opt_date, sar_date})

        from ..processing.sar import check_coregistration
        coreg = check_coregistration(opt_scene.shape, opt_scene.bbox or [],
                                     sar_scene.shape, sar_scene.bbox or [])
        coreg["temporal_gap_days"] = gap
        ctx.compatibility["cross_modal"] = coreg
        log.append({"check": "optical-SAR co-registration",
                    "result": "pass" if coreg["co_registered"] else "fail", "detail": coreg})
        return log

    # ---------- single scene --------------------------------------------
    anchor = plan.dates[-1] if plan.dates else _default_date()
    wants_sar = "sar" in plan.modalities and "optical" not in plan.modalities
    if wants_sar:
        d, probes = _search_sar(bbox, anchor, ctx=ctx)
        log.append({"check": "SAR availability", "requested": anchor, "selected": d,
                    "probes": probes, "result": "pass"})
        sc, checks = _scene_from_sar("sar", bbox, d, size)
        ctx.add_scene(sc)
        # SAR-only requests still benefit from an optical companion for context.
        try:
            od, _ = _search_optical(bbox, d, span=4, ctx=ctx)
            osc, oc = _scene_from_cube("primary", bbox, od, size)
            ctx.add_scene(osc)
            log.extend(oc)
        except Exception:
            log.append({"check": "optical companion", "result": "unavailable"})
        plan.dates = [d]
    else:
        d, probes = _search_optical(bbox, anchor, span=10, ctx=ctx)
        log.append({"check": "optical availability", "requested": anchor, "selected": d,
                    "probes": probes, "result": "pass"})
        if d != anchor:
            ctx.warn(f"No usable optical observation on {anchor}; used the nearest clear "
                     f"acquisition on {d}.")
        sc, checks = _scene_from_cube("primary", bbox, d, size)
        ctx.add_scene(sc)
        log.extend(checks)
        plan.dates = [d]

        if "sar" in plan.modalities:
            try:
                sd, sprobes = _search_sar(bbox, d, ctx=ctx)
                ssc, sc2 = _scene_from_sar("sar", bbox, sd, size)
                ctx.add_scene(ssc)
                log.append({"check": "SAR availability", "requested": d, "selected": sd,
                            "probes": sprobes, "result": "pass"})
            except AcquisitionError as exc:
                ctx.warn(f"SAR requested but unavailable: {exc}")
                log.append({"check": "SAR availability", "result": "unavailable",
                            "detail": str(exc)})
    return log
