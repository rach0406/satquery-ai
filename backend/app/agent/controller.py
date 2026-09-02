"""The agentic controller.

Its contract, straight from the problem statement:

* interpret the query and classify the requested task;
* check the number, modality, format, metadata and compatibility of the inputs;
* select one or more models or tools from a predefined registry;
* configure only permitted task parameters and execute the selected workflow;
* combine textual and spatial outputs, estimate confidence, return visual evidence;
* provide an auditable execution summary containing the selected task, model/tool
  names and key parameters.

Every stage emits a :class:`ToolCall` into the trace, including stages that are
*skipped* and why - the trace is the product, not a debug log.
"""
from __future__ import annotations

import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Callable, Iterator

from ..config import settings
from ..schemas import (GroundingReport, InputConfiguration, QueryPlan, QueryRequest,
                       QueryResponse, TaskType, ToolCall, ToolResult)
from ..tools import answer as T_answer
from ..tools import optical as T_optical
from ..tools import radar as T_radar
from ..tools import temporal as T_temporal
from . import acquisition, explain, nlu, registry, summary
from .context import RunContext
from .grounding import FactStore

#: name -> callable(ctx, **params) -> ToolResult
TOOL_IMPL: dict[str, Callable[..., ToolResult]] = {
    "spectral_index": T_optical.run_spectral_index,
    "landcover_segmenter": T_optical.run_landcover_segmenter,
    "rs_scene_classifier": T_optical.run_rs_scene_classifier,
    "region_grounder": T_optical.run_region_grounder,
    "change_analyzer": T_temporal.run_change_analyzer,
    "timeseries_analyzer": T_temporal.run_timeseries_analyzer,
    "sar_analyzer": T_radar.run_sar_analyzer,
    "optical_sar_fusion": T_radar.run_optical_sar_fusion,
    "vqa_resolver": T_answer.run_vqa_resolver,
    "scene_captioner": T_answer.run_scene_captioner,
}

#: Deterministic execution order per task. Measurement tools run first so the
#: answer tools always have a populated fact store to resolve against.
WORKFLOWS: dict[TaskType, list[str]] = {
    TaskType.VQA: ["landcover_segmenter", "spectral_index", "rs_scene_classifier",
                   "sar_analyzer", "vqa_resolver"],
    TaskType.CAPTION: ["landcover_segmenter", "spectral_index", "rs_scene_classifier",
                       "sar_analyzer", "scene_captioner"],
    TaskType.GROUNDING: ["landcover_segmenter", "region_grounder", "spectral_index",
                         "vqa_resolver"],
    TaskType.LANDCOVER: ["landcover_segmenter", "rs_scene_classifier", "spectral_index",
                         "scene_captioner"],
    TaskType.INDEX_ANALYSIS: ["spectral_index", "landcover_segmenter", "vqa_resolver"],
    TaskType.CHANGE_DETECTION: ["change_analyzer", "vqa_resolver"],
    TaskType.CHANGE_VQA: ["change_analyzer", "vqa_resolver"],
    TaskType.OPTICAL_SAR_FUSION: ["landcover_segmenter", "spectral_index", "sar_analyzer",
                                  "optical_sar_fusion", "rs_scene_classifier", "vqa_resolver"],
    TaskType.TIME_SERIES: ["timeseries_analyzer", "vqa_resolver"],
}

STAGES = ("parse", "validate", "acquire", "select", "execute", "ground", "narrate")

#: Earliest observation any layer in the catalogue can serve (MODIS Terra).
ARCHIVE_START = "2000-02-24"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _tool_params(plan: QueryPlan, tool: str) -> dict:
    """Task parameters the controller wants, before registry validation."""
    p: dict = {}
    if tool in ("spectral_index", "change_analyzer") and plan.indices:
        p["indices"] = plan.indices
    if tool == "timeseries_analyzer":
        p["index"] = (plan.indices[0] if plan.indices else "NDVI")
    return p


class Controller:
    """One instance per request."""

    #: What a bare image upload is taken to be asking. Analysing an image the
    #: user just handed over needs no typed question - "here is a scene, tell
    #: me what is in it" is the whole request - so the console is allowed to
    #: send an empty query alongside a scene id and this stands in for it.
    IMAGE_ONLY_QUERY = ("Describe this scene and break down what it contains")

    def __init__(self, req: QueryRequest):
        self.req = req
        self.request_id = f"req_{uuid.uuid4().hex[:12]}"
        self.t0 = time.perf_counter()
        self.trace: list[ToolCall] = []
        self.step = 0
        self.store = FactStore()
        self.ctx: RunContext | None = None
        self.plan: QueryPlan | None = None
        self.selected: list[str] = []
        self.probe_log: list[dict] = []
        self.archive_range_error: str | None = None

    @property
    def has_scene(self) -> bool:
        return bool(self.req.scene_id or self.req.scene_ids)

    @property
    def effective_query(self) -> str:
        """The text the parser sees. Substituted for an image-only request."""
        q = (self.req.query or "").strip()
        if q:
            return q
        if self.has_scene:
            return self.IMAGE_ONLY_QUERY
        return q

    # -- trace helpers ----------------------------------------------------
    def _record(self, tool: str, task: TaskType, status: str, message: str | None = None,
                params: dict | None = None, duration_ms: int = 0,
                fact_keys: list[str] | None = None, artifact_ids: list[str] | None = None,
                confidence: float | None = None, version: str = "1.0.0") -> ToolCall:
        self.step += 1
        call = ToolCall(
            step=self.step, tool=tool, tool_version=version, task=task,
            parameters=params or {}, status=status, started_at=_now(),  # type: ignore[arg-type]
            duration_ms=duration_ms, message=message, fact_keys=fact_keys or [],
            artifact_ids=artifact_ids or [], confidence=confidence,
        )
        self.trace.append(call)
        return call

    def _elapsed(self) -> int:
        return int((time.perf_counter() - self.t0) * 1000)

    # -- stages -----------------------------------------------------------
    def parse(self) -> QueryPlan:
        t = time.perf_counter()
        plan = nlu.parse(self.effective_query, use_llm=self.req.use_llm)

        # Explicit request overrides always win over inference.
        if self.req.bbox:
            plan.bbox = self.req.bbox
            plan.aoi_name = self.req.aoi_name or plan.aoi_name or "custom area"
            plan.notes.append("AOI supplied explicitly by the client")
        elif self.req.aoi_name:
            from ..datasources import gazetteer
            p = gazetteer.resolve(self.req.aoi_name)
            if p:
                plan.bbox, plan.aoi_name = list(p.bbox), p.name
                plan.notes.append(f"AOI '{self.req.aoi_name}' supplied explicitly by the client")
        if self.req.dates:
            plan.dates = sorted(self.req.dates)
            plan.notes.append("dates supplied explicitly by the client")

        n_scenes = len([s for s in ([self.req.scene_id] + self.req.scene_ids) if s])
        if n_scenes == 1 and plan.input_configuration is InputConfiguration.NONE:
            plan.input_configuration = InputConfiguration.SINGLE
        if n_scenes and not (self.req.query or "").strip():
            plan.notes.append(
                "no question was typed; the uploaded image was analysed on its own")

        # The restatement has to reflect the plan the pipeline will actually
        # run, so it is rebuilt after any client override above.
        from . import intent
        plan.interpretation = intent.restate(
            plan.task, plan.aoi_name, plan.dates,
            intent.detect_event(self.effective_query), plan.indices,
            on_upload=self.has_scene)

        self.plan = plan
        self._record(
            "nlu_parser", plan.task, "ok",
            message=(f"Classified as {plan.task.value} / {plan.input_configuration.value} "
                     f"(parser: {plan.parser}, confidence {plan.confidence:.2f})."),
            params={"parser": plan.parser, "aoi": plan.aoi_name, "dates": plan.dates,
                    "target_classes": plan.target_classes, "indices": plan.indices,
                    "modalities": plan.modalities, "llm_available": settings.llm_available},
            duration_ms=int((time.perf_counter() - t) * 1000), confidence=plan.confidence,
        )
        return plan

    def validate(self) -> str | None:
        """Return a clarification question if the plan cannot be executed."""
        t = time.perf_counter()
        plan = self.plan
        assert plan is not None
        issues: list[str] = []
        question: str | None = None

        has_scene = bool(self.req.scene_id or self.req.scene_ids)
        if not plan.bbox and not has_scene and plan.task is not TaskType.UNSUPPORTED:
            issues.append("no area of interest")
            question = ("Which area should I analyse? Name a place (for example "
                        "\"Chennai\", \"Sundarbans\" or \"Chilika Lake\"), or upload a "
                        "GeoTIFF/PNG scene.")

        # Dates outside the archive's lifetime are unanswerable, and saying so
        # up front is more useful than probing 21 dates that cannot exist.
        if plan.dates and not has_scene:
            too_early = [d for d in plan.dates if d < ARCHIVE_START]
            if too_early:
                self.archive_range_error = (
                    f"The requested date(s) {', '.join(too_early)} predate the imagery archive "
                    f"this system can query. MODIS Terra observations begin on {ARCHIVE_START}, "
                    f"Aqua on 2002-07-04, VIIRS on 2015-11-24 and Sentinel-1 OPERA RTC on "
                    f"2023-12-15. There is no observation to measure, so no value is reported."
                )
                issues.append(f"dates before archive start ({ARCHIVE_START})")

        if plan.task in (TaskType.CHANGE_DETECTION, TaskType.CHANGE_VQA) and not has_scene:
            if len(plan.dates) < 2:
                issues.append("change analysis defaulted its comparison dates")

        if plan.indices:
            unknown = [i for i in plan.indices if i not in
                       ("NDVI", "NDWI", "MNDWI", "NBR", "NDBI", "BSI", "VARI")]
            if unknown:
                issues.append(f"unsupported indices {unknown}")

        self._record(
            "plan_validator", plan.task, "ok" if question is None else "no_data",
            message=("Plan is executable." if question is None
                     else "Plan is missing a required parameter."),
            params={"issues": issues, "input_configuration": plan.input_configuration.value,
                    "scene_ids": [s for s in ([self.req.scene_id] + self.req.scene_ids) if s]},
            duration_ms=int((time.perf_counter() - t) * 1000),
        )
        return question

    def acquire(self) -> RunContext:
        t = time.perf_counter()
        plan = self.plan
        assert plan is not None
        ctx = RunContext(plan=plan, store=self.store)
        self.ctx = ctx

        # A question about something these sensors cannot measure still gets
        # the surface analysis it *can* produce - with the gap stated, not
        # papered over.
        if plan.unsupported_aspect:
            ctx.warn(plan.unsupported_aspect)

        ids = [s for s in ([self.req.scene_id] + self.req.scene_ids) if s]
        self.probe_log = acquisition.acquire(ctx, plan, ids)
        self._publish_geometry_facts(ctx)

        detail = []
        for s in ctx.scenes.values():
            detail.append({
                "role": s.role, "label": s.label, "modality": s.modality, "date": s.date,
                "size": f"{s.shape[1]}x{s.shape[0]}",
                "bands": sorted(s.bands.keys()),
                "coverage": round(s.valid_fraction, 4),
                "origin": s.provenance.origin.value,
                "is_real": s.provenance.is_real,
                "source": s.provenance.source,
                "source_url": s.provenance.source_url,
            })
        self._record(
            "data_acquisition", plan.task, "ok",
            message=(f"Retrieved {len(ctx.scenes)} scene(s); "
                     f"{sum(len(p.get('probes', [])) for p in self.probe_log)} archive "
                     "availability probes performed."),
            params={"scenes": detail, "checks": self.probe_log,
                    "compatibility": ctx.compatibility,
                    "raster_size": settings.default_raster_size},
            duration_ms=int((time.perf_counter() - t) * 1000),
        )
        return ctx

    def _publish_geometry_facts(self, ctx: RunContext) -> None:
        """Scene geometry is a measurement too - publish it before any tool runs.

        The narrator legitimately quotes the analysed area and the pixel grid, so
        those numbers must exist in the fact store regardless of which tools the
        workflow happens to select.
        """
        from .grounding import fact

        h, w = ctx.shape
        if not (h and w):
            return
        src = ", ".join(sorted({s.provenance.source for s in ctx.scenes.values()}))
        facts = [
            fact(key="raster_width", label="Raster width", value=w, unit="pixels",
                 method="width of the retrieved analysis grid",
                 tool="data_acquisition", source=src),
            fact(key="raster_height", label="Raster height", value=h, unit="pixels",
                 method="height of the retrieved analysis grid",
                 tool="data_acquisition", source=src),
            fact(key="scene_count", label="Scenes retrieved", value=len(ctx.scenes),
                 unit="scenes", method="number of rasters loaded for this request",
                 tool="data_acquisition", source=src),
        ]
        if ctx.georeferenced:
            facts += [
                fact(key="scene_area_km2", label="Analysed area",
                     value=round(ctx.scene_area_km2, 2), unit="km2",
                     method="geodesic area of the requested bounding box (EPSG:4326)",
                     tool="data_acquisition", source=src),
                fact(key="pixel_area_km2", label="Ground area per pixel",
                     value=round(ctx.pixel_area_km2, 8), unit="km2",
                     method=f"scene area / ({w} x {h}) pixels",
                     tool="data_acquisition", source=src),
            ]
        self.store.add_many(facts)

    def select(self) -> list[str]:
        t = time.perf_counter()
        plan = self.plan
        ctx = self.ctx
        assert plan is not None and ctx is not None

        modalities = sorted({s.modality for s in ctx.scenes.values()})
        # multispectral scenes satisfy an "optical" requirement
        if any(m in ("optical", "multispectral") for m in modalities):
            modalities.append("optical")
        if not ctx.scenes and plan.input_configuration is InputConfiguration.NONE:
            # Multi-date tools retrieve their own imagery, so eligibility is
            # decided by what the archive can serve, not by scenes the
            # acquisition stage was never asked to load.
            modalities = ["optical", "multispectral", "sar"]

        # An uploaded photograph is analysable; it simply has no position on
        # Earth. Only the tools that genuinely need one are gated out.
        georeferenced = ctx.georeferenced or not ctx.scenes
        eligible = {s.name for s in registry.select_tools(
            plan.task, plan.input_configuration, modalities,
            georeferenced=georeferenced)}
        workflow = WORKFLOWS.get(plan.task, ["landcover_segmenter", "vqa_resolver"])

        chosen: list[str] = []
        rejected: list[dict] = []
        for name in workflow:
            spec = registry.SPECS[name]
            if name in eligible:
                chosen.append(name)
                continue
            reason = []
            if plan.task not in spec.tasks:
                reason.append(f"does not serve task '{plan.task.value}'")
            if plan.input_configuration not in spec.input_configurations:
                reason.append(f"does not accept '{plan.input_configuration.value}'")
            missing = set(spec.required_modalities) - set(modalities)
            if missing:
                reason.append(f"requires modality {sorted(missing)} (available: {modalities})")
            if spec.requires_georeferencing and not georeferenced:
                reason.append(
                    "requires georeferencing: this tool retrieves matching imagery for "
                    "other dates, which needs to know where on Earth the image is. The "
                    "uploaded image carries no map projection")
            rejected.append({"tool": name, "reason": "; ".join(reason) or "not eligible"})

        self.selected = chosen
        self._record(
            "tool_selector", plan.task, "ok",
            message=(f"Selected {len(chosen)} of {len(registry.SPECS)} registry tools "
                     f"for task '{plan.task.value}'."),
            params={
                "available_modalities": modalities,
                "selected": [{"tool": n, "version": registry.SPECS[n].version,
                              "backend": registry.SPECS[n].backend,
                              "title": registry.SPECS[n].title} for n in chosen],
                "not_selected": rejected,
                "workflow_order": workflow,
            },
            duration_ms=int((time.perf_counter() - t) * 1000),
        )
        return chosen

    def execute_one(self, name: str) -> ToolResult:
        ctx = self.ctx
        plan = self.plan
        assert ctx is not None and plan is not None
        spec = registry.SPECS[name]
        t = time.perf_counter()

        params, notes = registry.validate_parameters(name, _tool_params(plan, name))
        for n in notes:
            ctx.warn(f"[{name}] {n}")

        try:
            result = TOOL_IMPL[name](ctx, **params)
        except Exception as exc:
            result = ToolResult(
                tool=name, tool_version=spec.version, status="error",
                message=f"{type(exc).__name__}: {exc}")
            ctx.warn(f"Tool '{name}' failed: {type(exc).__name__}: {exc}")
            if settings.offline_mode:
                traceback.print_exc()

        fact_keys = self.store.add_many(result.facts)
        self.store.add_provenance(result.provenance)
        art_ids = ctx.add_artifacts(result.artifacts)

        self._record(
            name, plan.task, result.status, message=result.message,
            params={**params, **result.parameters,
                    "registry_notes": notes,
                    "backend": spec.backend,
                    "adapted_on": spec.adapted_on},
            duration_ms=int((time.perf_counter() - t) * 1000),
            fact_keys=fact_keys, artifact_ids=art_ids,
            confidence=result.confidence, version=spec.version,
        )
        return result

    # -- orchestration ----------------------------------------------------
    def run(self) -> QueryResponse:
        plan = self.parse()

        question = self.validate()
        if self.archive_range_error:
            return self._finish(
                status="no_data",
                answer="The required data is unavailable for this request.",
                explanation=explain.no_data_explanation(plan, self.archive_range_error),
                plan=plan)
        if question:
            return self._finish(
                status="needs_clarification", answer=question,
                explanation=("The question is missing a parameter the pipeline requires, so no "
                             "data was retrieved and no result was produced."),
                plan=plan)

        try:
            ctx = self.acquire()
        except acquisition.AcquisitionError as exc:
            self._record("data_acquisition", plan.task, "no_data", message=str(exc),
                         params={"detail": exc.detail})
            return self._finish(
                status="no_data",
                answer="The required data is unavailable for this request.",
                explanation=explain.no_data_explanation(plan, str(exc), exc.detail),
                plan=plan)
        except Exception as exc:
            self._record("data_acquisition", plan.task, "error", message=str(exc))
            return self._finish(
                status="error", answer=None,
                explanation=(f"Data retrieval failed: {exc}. No result is reported because no "
                             "measurement was obtained."),
                plan=plan)

        self.select()

        answer: str | None = None
        confidences: list[float] = []
        produced = 0
        for name in self.selected:
            res = self.execute_one(name)
            if res.status == "ok":
                produced += 1
                if res.confidence is not None:
                    confidences.append(res.confidence)
                if res.answer:
                    answer = res.answer

        if produced == 0:
            return self._finish(
                status="no_data", answer=None,
                explanation=("Every selected tool reported that it could not produce a "
                             "measurement from the retrieved data. No figure is reported. "
                             + " ".join(c.message or "" for c in self.trace[-3:])),
                plan=plan)

        # ---- grounding + narration -------------------------------------
        t = time.perf_counter()
        text, report = explain.narrate(ctx, use_llm=self.req.use_llm)
        self._record(
            "grounding_verifier", plan.task, "ok" if report.passed else "error",
            message=report.explanation,
            params={"narrator": report.narrator, "strict_mode": report.strict_mode,
                    "claims_checked": report.claims_checked,
                    "claims_verified": report.claims_verified,
                    "rejected": [c.text for c in report.rejected_claims],
                    "all_sources_real": report.all_sources_real},
            duration_ms=int((time.perf_counter() - t) * 1000),
        )

        conf = round(sum(confidences) / len(confidences), 3) if confidences else None
        return self._finish(status="ok", answer=answer, explanation=text, plan=plan,
                            grounding=report, confidence=conf)

    def _scene_meta(self) -> dict:
        """Summary of the scene the analysis actually ran on, for the digest."""
        ctx = self.ctx
        if ctx is None:
            return {}
        scene = ctx.get("primary", "after", "optical", "sar", "before")
        if scene is None:
            return {}
        return {
            "width": scene.shape[1],
            "height": scene.shape[0],
            "bands": sorted(scene.bands.keys()),
            "bbox": scene.bbox,
            "spatial_reference": "georeferenced" if scene.bbox else "pixel_space",
            # An uploaded file carries its own geometry, so a place name parsed
            # out of the question is unverified and must not be shown as its
            # location.
            "is_upload": bool(self.req.scene_id or self.req.scene_ids),
            "capabilities": {
                "band_basis": (
                    "multispectral" if all(b in scene.bands for b in ("nir", "red"))
                    else "rgb" if all(b in scene.bands for b in ("red", "green", "blue"))
                    else "single_band"),
            },
            "metadata": scene.metadata,
        }

    def _finish(self, status: str, answer: str | None, explanation: str, plan: QueryPlan,
                grounding: GroundingReport | None = None,
                confidence: float | None = None) -> QueryResponse:
        ctx = self.ctx
        # Acquisition may have moved the dates - a requested day with no clear
        # acquisition resolves to the nearest usable one - so the restatement is
        # refreshed here to describe what was actually analysed rather than what
        # was originally asked for.
        from . import intent
        plan.interpretation = intent.restate(
            plan.task, plan.aoi_name, plan.dates,
            intent.detect_event(self.effective_query), plan.indices,
            on_upload=self.has_scene)

        try:
            digest = summary.build_summary(
                plan=plan, store=self.store, status=status, grounding=grounding,
                warnings=(ctx.warnings if ctx else []), confidence=confidence,
                scene_meta=self._scene_meta(), answer=answer,
                tools_run=[c.tool for c in self.trace
                           if c.status == "ok" and c.tool in summary.TOOL_SUMMARY_LABEL],
            )
        except Exception as exc:  # the digest must never break a good result
            digest = []
            if ctx is not None:
                ctx.warn(f"Summary card could not be built: {type(exc).__name__}: {exc}")
        return QueryResponse(
            request_id=self.request_id,
            query=self.effective_query,
            status=status,  # type: ignore[arg-type]
            plan=plan,
            execution_trace=self.trace,
            facts=self.store.as_list(),
            artifacts=(ctx.artifacts if ctx else []),
            provenance=self.store.provenance,
            answer=answer,
            explanation=explanation,
            summary=digest,
            grounding=grounding or GroundingReport(
                narrator="template", strict_mode=settings.strict_grounding,
                fact_count=len(self.store.facts),
                all_sources_real=self.store.all_real,
                passed=True,
                explanation="No narration was generated for this outcome."),
            confidence=confidence,
            warnings=(ctx.warnings if ctx else []),
            total_duration_ms=self._elapsed(),
        )


def run_query(req: QueryRequest) -> QueryResponse:
    return Controller(req).run()


# --------------------------------------------------------------------------
# Streaming variant - drives the live pipeline view in the UI
# --------------------------------------------------------------------------
def run_query_streaming(req: QueryRequest) -> Iterator[dict]:
    """Yield a dict per pipeline stage, then the full result.

    The timings reported are the real ones; nothing is simulated for effect.
    """
    c = Controller(req)
    yield {"event": "start", "request_id": c.request_id, "query": req.query,
           "stages": list(STAGES)}

    try:
        plan = c.parse()
        yield {"event": "stage", "stage": "parse", "status": "ok",
               "detail": c.trace[-1].model_dump(mode="json"),
               "plan": plan.model_dump(mode="json")}

        question = c.validate()
        yield {"event": "stage", "stage": "validate",
               "status": "ok" if (question is None and not c.archive_range_error)
                         else ("no_data" if c.archive_range_error else "needs_clarification"),
               "detail": c.trace[-1].model_dump(mode="json")}
        if c.archive_range_error:
            resp = c._finish(
                status="no_data",
                answer="The required data is unavailable for this request.",
                explanation=explain.no_data_explanation(plan, c.archive_range_error),
                plan=plan)
            yield {"event": "result", "result": resp.model_dump(mode="json")}
            return
        if question:
            resp = c._finish(
                status="needs_clarification", answer=question,
                explanation=("The question is missing a parameter the pipeline requires, so no "
                             "data was retrieved and no result was produced."),
                plan=plan)
            yield {"event": "result", "result": resp.model_dump(mode="json")}
            return

        try:
            ctx = c.acquire()
            yield {"event": "stage", "stage": "acquire", "status": "ok",
                   "detail": c.trace[-1].model_dump(mode="json")}
        except acquisition.AcquisitionError as exc:
            c._record("data_acquisition", plan.task, "no_data", message=str(exc),
                      params={"detail": exc.detail})
            yield {"event": "stage", "stage": "acquire", "status": "no_data",
                   "detail": c.trace[-1].model_dump(mode="json")}
            resp = c._finish(status="no_data",
                             answer="The required data is unavailable for this request.",
                             explanation=explain.no_data_explanation(plan, str(exc), exc.detail),
                             plan=plan)
            yield {"event": "result", "result": resp.model_dump(mode="json")}
            return

        c.select()
        yield {"event": "stage", "stage": "select", "status": "ok",
               "detail": c.trace[-1].model_dump(mode="json")}

        answer, confidences, produced = None, [], 0
        for name in c.selected:
            res = c.execute_one(name)
            if res.status == "ok":
                produced += 1
                if res.confidence is not None:
                    confidences.append(res.confidence)
                if res.answer:
                    answer = res.answer
            yield {"event": "tool", "stage": "execute", "tool": name, "status": res.status,
                   "detail": c.trace[-1].model_dump(mode="json")}

        if produced == 0:
            resp = c._finish(status="no_data", answer=None,
                             explanation=("Every selected tool reported that it could not "
                                          "produce a measurement from the retrieved data."),
                             plan=plan)
            yield {"event": "result", "result": resp.model_dump(mode="json")}
            return

        text, report = explain.narrate(ctx, use_llm=req.use_llm)
        c._record("grounding_verifier", plan.task, "ok" if report.passed else "error",
                  message=report.explanation,
                  params={"narrator": report.narrator,
                          "claims_checked": report.claims_checked,
                          "claims_verified": report.claims_verified,
                          "rejected": [x.text for x in report.rejected_claims]})
        yield {"event": "stage", "stage": "ground", "status": "ok",
               "detail": c.trace[-1].model_dump(mode="json")}

        conf = round(sum(confidences) / len(confidences), 3) if confidences else None
        resp = c._finish(status="ok", answer=answer, explanation=text, plan=plan,
                         grounding=report, confidence=conf)
        yield {"event": "stage", "stage": "narrate", "status": "ok",
               "detail": {"narrator": report.narrator}}
        yield {"event": "result", "result": resp.model_dump(mode="json")}

    except Exception as exc:  # never leave the client hanging
        yield {"event": "error", "message": f"{type(exc).__name__}: {exc}",
               "traceback": traceback.format_exc()[-1500:]}
