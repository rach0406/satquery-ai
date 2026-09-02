"""HTTP surface for SatQuery AI."""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from ..agent import controller, nlu, registry
from ..config import settings
from ..datasources import gazetteer, gibs, imagery_io
from ..ml import classifier
from ..processing.indices import CLASS_LABELS, INDEX_META, INDEX_REQUIREMENTS
from ..schemas import QueryRequest, QueryResponse
from .routes_auth import optional_user
from .samples import SAMPLE_QUERIES

router = APIRouter()
_START = time.time()


# --------------------------------------------------------------------------
# Health & metadata
# --------------------------------------------------------------------------
@router.get("/health", tags=["system"])
def health() -> dict:
    info = classifier.model_info()
    return {
        "status": "ok",
        "app": settings.app_name,
        "team": settings.team,
        "problem_statement": settings.problem_statement,
        "version": settings.version,
        "uptime_seconds": round(time.time() - _START, 1),
        "server_date": date.today().isoformat(),
        "offline_mode": settings.offline_mode,
        "cache_enabled": settings.cache_enabled,
        "strict_grounding": settings.strict_grounding,
        "llm": {
            "available": settings.llm_available,
            "model": settings.llm_model if settings.llm_available else None,
            "role": ("query parsing and narration only; it never produces measurements "
                     "and its output is numerically verified against the fact store"),
        },
        "rs_model": {
            "available": info["available"],
            "name": info["name"],
            "adapted_on": info["adapted_on"],
            "test_accuracy": info["test_accuracy"],
            "macro_f1": info["macro_f1"],
            "error": info["error"],
        },
        "tools_registered": len(registry.SPECS),
        "auth": {
            "enabled": True,
            "required_by_api": settings.require_auth,
            "note": ("The console always gates access on sign-in. Set "
                     "SATQUERY_REQUIRE_AUTH=true to make the API refuse anonymous calls too."),
        },
    }


@router.get("/catalog", tags=["system"])
def catalog() -> dict:
    """Everything the system can query, and what it can compute from it."""
    return {
        "layers": gibs.layer_catalog(),
        "indices": [
            {"name": k, **INDEX_META[k], "required_bands": list(v)}
            for k, v in INDEX_REQUIREMENTS.items()
        ],
        "landcover_classes": [{"key": k, "label": v} for k, v in CLASS_LABELS.items()],
        "places": [
            {"name": p.name, "bbox": list(p.bbox), "kind": p.kind, "country": p.country,
             "area_km2": round(gazetteer.bbox_area_km2(p.bbox), 1), "note": p.note}
            for p in gazetteer.all_places()
        ],
        "data_policy": {
            "principle": ("Every number shown is measured from retrieved pixels. The language "
                          "model may phrase results but may not produce them; each numeral it "
                          "writes is matched back to a measured fact before display."),
            "origins": {
                "live_satellite": "Fetched now from a public NASA archive.",
                "cached_satellite": "Real archive imagery served from the local disk cache.",
                "user_upload": "Imagery supplied by the analyst.",
                "bundled_sample": "Real imagery shipped with the repository.",
                "synthetic_demo": "NOT REAL - clearly badged, never mixed with measurements.",
            },
        },
    }


@router.get("/registry", tags=["system"])
def tool_registry() -> dict:
    return {
        "tools": registry.registry_manifest(),
        "workflows": {t.value: names for t, names in controller.WORKFLOWS.items()},
        "stages": list(controller.STAGES),
    }


@router.get("/model", tags=["system"])
def model_card() -> dict:
    """Full model card for the remote-sensing-adapted classifier."""
    info = classifier.model_info()
    if not info["available"]:
        return JSONResponse(status_code=200, content={
            **info,
            "hint": "Train it with: python -m app.ml.train_eurosat --limit-per-class 900",
        })
    return info


@router.get("/samples", tags=["demo"])
def samples() -> dict:
    return {"samples": SAMPLE_QUERIES, "count": len(SAMPLE_QUERIES)}


# --------------------------------------------------------------------------
# Query
# --------------------------------------------------------------------------
@router.post("/query", response_model=QueryResponse, tags=["query"])
def query(req: QueryRequest, user: dict | None = Depends(optional_user)) -> QueryResponse:
    try:
        return controller.run_query(req)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@router.post("/query/stream", tags=["query"])
def query_stream(req: QueryRequest,
                 user: dict | None = Depends(optional_user)) -> StreamingResponse:
    """Server-sent events: one message per pipeline stage, then the result.

    Timings in the stream are the real ones; no stage is delayed for effect.
    """
    def gen():
        try:
            for msg in controller.run_query_streaming(req):
                yield f"data: {json.dumps(msg, default=str)}\n\n"
        except Exception as exc:  # pragma: no cover
            yield f"data: {json.dumps({'event': 'error', 'message': str(exc)})}\n\n"
        yield "data: {\"event\": \"done\"}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive",
    })


@router.get("/locate", tags=["query"])
def locate(q: str = "") -> dict:
    """Resolve just the place named in a query. Cheap enough to call while typing.

    The console uses this to swing the globe towards the area as the question
    is written, so the visual and the analysis agree on where "Kerala" is. It
    runs the same resolver the pipeline uses - there is no second, looser
    geocoder that could disagree with the analysis.
    """
    text = (q or "").strip()
    if len(text) < 3:
        return {"query": text, "resolved": False, "place": None}
    place = gazetteer.resolve(text)
    if place is None:
        return {"query": text, "resolved": False, "place": None,
                "reason": "No place name was recognised in this text."}
    lon, lat = place.center
    return {
        "query": text,
        "resolved": True,
        "place": {
            "name": place.name,
            "kind": place.kind,
            "country": place.country,
            "bbox": list(place.bbox),
            "center": [lon, lat],
            "area_km2": round(gazetteer.bbox_area_km2(place.bbox), 1),
            "note": place.note,
        },
        "event": nlu.intent.detect_event(text).label if nlu.intent.detect_event(text) else None,
    }


@router.post("/parse", tags=["query"])
def parse_only(req: QueryRequest) -> dict:
    """Expose the NLU stage alone - useful for showing intent extraction live."""
    plan = nlu.parse(req.query, use_llm=req.use_llm)
    rules = nlu.parse_rules(req.query)
    return {
        "plan": plan.model_dump(mode="json"),
        "rule_parser_plan": rules.model_dump(mode="json"),
        "interpretation": plan.interpretation,
        "event": plan.event,
        "unsupported_aspect": plan.unsupported_aspect,
        "llm_used": plan.parser in ("llm", "hybrid"),
        "llm_available": settings.llm_available,
        "eligible_tools": [
            s.name for s in registry.select_tools(
                plan.task, plan.input_configuration, ["optical", "sar"])
        ],
        "workflow": [t for t in controller.WORKFLOWS.get(plan.task, [])],
    }


# --------------------------------------------------------------------------
# Scenes
# --------------------------------------------------------------------------
@router.get("/scenes", tags=["scenes"])
def list_scenes() -> dict:
    rows = []
    for base, kind in ((settings.scenes_dir, "bundled"), (settings.uploads_dir, "upload")):
        for p in sorted(base.iterdir() if base.exists() else []):
            if p.suffix.lower() not in imagery_io.SUPPORTED_EXT:
                continue
            side = p.with_suffix(p.suffix + ".json")
            meta = {}
            if side.exists():
                try:
                    meta = json.loads(side.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            rows.append({
                "scene_id": meta.get("scene_id") or p.stem.split("_")[0],
                "filename": p.name, "kind": kind,
                "size_mb": round(p.stat().st_size / 1e6, 2),
                "modified": datetime.fromtimestamp(p.stat().st_mtime,
                                                   tz=timezone.utc).isoformat(timespec="seconds"),
                **{k: meta.get(k) for k in
                   ("name", "modality", "bbox", "acquisition_date", "width", "height", "bands")},
            })
    return {"scenes": rows, "count": len(rows)}


@router.post("/scenes/upload", tags=["scenes"])
async def upload_scene(file: UploadFile = File(...)) -> dict:
    """Ingest a GeoTIFF/TIFF/PNG/JPEG and report what was actually found in it."""
    data = await file.read()
    try:
        path = imagery_io.save_upload(data, file.filename or "upload.tif")
    except imagery_io.ImageLoadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        scene = imagery_io.load_scene_file(path, scene_id=path.stem.split("_")[0])
    except imagery_io.ImageLoadError as exc:
        # Already phrased for a person; passing it through avoids stacking
        # a second prefix onto an explanation that reads fine on its own.
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"Could not read '{file.filename}': {type(exc).__name__}: {exc}") from exc

    check = imagery_io.check_single_scene(scene)
    summary = scene.summary()
    imagery_io.write_sidecar(path, summary)

    from ..utils import render
    thumb = render.png_data_uri(scene.array[::max(1, scene.shape[0] // 320)][:, ::max(
        1, scene.shape[1] // 320)])
    return {
        "scene": summary,
        "compatibility": check,
        "thumbnail": thumb,
        "rasterio_available": imagery_io.HAS_RASTERIO,
        "note": (None if imagery_io.HAS_RASTERIO else
                 "rasterio is not installed, so GeoTIFF georeferencing and per-band metadata "
                 "were not read. Install it with: pip install rasterio"),
    }


@router.delete("/scenes/{scene_id}", tags=["scenes"])
def delete_scene(scene_id: str) -> dict:
    removed = []
    for p in list(settings.uploads_dir.glob(f"{scene_id}*")):
        p.unlink(missing_ok=True)
        removed.append(p.name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No uploaded scene '{scene_id}'.")
    return {"removed": removed}


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
@router.post("/report", tags=["report"])
def build_report(payload: dict) -> dict:
    """Persist a finished analysis as a downloadable, self-contained record."""
    rid = payload.get("request_id") or f"report_{int(time.time())}"
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    path = settings.reports_dir / f"{rid}.json"
    payload["exported_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["exported_by"] = f"{settings.app_name} v{settings.version} ({settings.team})"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return {"report_id": rid, "url": f"/api/report/{rid}", "bytes": path.stat().st_size}


@router.get("/report/{report_id}", tags=["report"])
def get_report(report_id: str) -> JSONResponse:
    path = settings.reports_dir / f"{report_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found.")
    return JSONResponse(
        content=json.loads(path.read_text(encoding="utf-8")),
        headers={"Content-Disposition": f'attachment; filename="{report_id}.json"'},
    )
