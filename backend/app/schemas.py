"""Typed contracts shared by the agent, the tools and the HTTP API.

Two ideas matter here:

*  :class:`Fact` is the *only* channel through which a number may reach the
   user. A tool that measures something must publish a Fact; the narrator may
   only reference Facts; the verifier rejects any narrated number that is not
   backed by one.
*  :class:`Provenance` travels with every artefact so the UI can always state
   where a pixel came from and whether it is real or simulated.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------
class DataOrigin(str, Enum):
    """How trustworthy is this byte of data? Rendered as a badge in the UI."""

    LIVE_SATELLITE = "live_satellite"      # fetched now from a real archive
    CACHED_SATELLITE = "cached_satellite"  # real archive, served from disk cache
    USER_UPLOAD = "user_upload"            # the analyst's own imagery
    BUNDLED_SAMPLE = "bundled_sample"      # real imagery shipped with the repo
    SYNTHETIC_DEMO = "synthetic_demo"      # NOT REAL - offline fallback only

    @property
    def is_real(self) -> bool:
        return self is not DataOrigin.SYNTHETIC_DEMO


class Provenance(BaseModel):
    origin: DataOrigin
    source: str = Field(description="Human readable archive / sensor name")
    source_url: str | None = None
    instrument: str | None = None
    platform: str | None = None
    modality: Literal["optical", "multispectral", "sar", "thermal", "derived", "tabular"] = "optical"
    acquisition_date: str | None = None
    resolution_m: float | None = None
    bbox: list[float] | None = Field(default=None, description="[west, south, east, north] EPSG:4326")
    crs: str = "EPSG:4326"
    retrieved_at: str | None = None
    license: str | None = None
    notes: str | None = None

    @property
    def is_real(self) -> bool:
        return self.origin.is_real


# --------------------------------------------------------------------------
# Facts - the grounding currency
# --------------------------------------------------------------------------
class Fact(BaseModel):
    """A single measured quantity, traceable to the pixels it came from."""

    key: str
    label: str
    value: float | int | str | bool
    unit: str | None = None
    method: str = Field(description="How the value was computed, e.g. mean(NDVI over 262144 px)")
    tool: str | None = None
    source: str | None = None
    sample_size: int | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @property
    def numeric(self) -> float | None:
        if isinstance(self.value, bool):
            return None
        if isinstance(self.value, (int, float)):
            return float(self.value)
        return None


class Artifact(BaseModel):
    """A visual output: raster overlay, chart spec, table, or bounding boxes."""

    id: str
    kind: Literal["image_overlay", "image", "chart", "table", "geojson", "boxes", "histogram"]
    title: str
    description: str | None = None
    url: str | None = None
    bbox: list[float] | None = None
    spec: dict[str, Any] | None = None
    provenance: Provenance | None = None
    colormap: str | None = None
    legend: list[dict[str, Any]] | None = None


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------
class TaskType(str, Enum):
    VQA = "vqa"
    CAPTION = "caption"
    GROUNDING = "grounding"
    CHANGE_DETECTION = "change_detection"
    CHANGE_VQA = "change_vqa"
    OPTICAL_SAR_FUSION = "optical_sar_fusion"
    LANDCOVER = "landcover"
    INDEX_ANALYSIS = "index_analysis"
    TIME_SERIES = "time_series"
    UNSUPPORTED = "unsupported"


class InputConfiguration(str, Enum):
    SINGLE = "single_image"
    BITEMPORAL = "bitemporal_pair"
    CROSS_MODAL = "cross_modal_pair"
    NONE = "no_image"


class QueryPlan(BaseModel):
    """Structured form of the natural-language question."""

    raw_query: str
    task: TaskType
    input_configuration: InputConfiguration
    aoi_name: str | None = None
    bbox: list[float] | None = None
    dates: list[str] = Field(default_factory=list)
    target_classes: list[str] = Field(default_factory=list, description="e.g. water, built_up")
    indices: list[str] = Field(default_factory=list, description="e.g. NDVI, NDWI")
    variables: list[str] = Field(default_factory=list, description="tabular variables for time series")
    modalities: list[str] = Field(default_factory=list)
    parser: Literal["llm", "rules", "hybrid"] = "rules"
    confidence: float = 0.0
    ambiguities: list[str] = Field(default_factory=list)
    clarification_needed: bool = False
    clarification_question: str | None = None
    notes: list[str] = Field(default_factory=list)

    #: The query restated in one plain sentence, so the user can check that the
    #: system read them correctly before trusting the numbers. Derived only
    #: from fields resolved above - it never adds information.
    interpretation: str | None = None
    #: Real-world phenomenon recognised in the query, e.g. "Flood / surface
    #: water". Selects *which* analysis to run; it never asserts the event
    #: happened.
    event: str | None = None
    #: Set when the question asks for a quantity these sensors cannot measure
    #: (air quality, surface temperature). The pipeline still analyses what it
    #: *can* observe and this explains the gap rather than hiding it.
    unsupported_aspect: str | None = None
    #: The query after conversational padding was removed.
    normalised_query: str | None = None


class ToolSpec(BaseModel):
    """Registry entry - what the controller is allowed to call and with what."""

    name: str
    version: str
    title: str
    description: str
    tasks: list[TaskType]
    input_configurations: list[InputConfiguration]
    required_modalities: list[str] = Field(default_factory=list)
    requires_georeferencing: bool = Field(
        default=False,
        description=("True when the tool cannot run without knowing where on Earth the "
                     "imagery is - e.g. anything that fetches matching imagery for "
                     "another date. Tools that merely *report* areas in km2 are not "
                     "listed here: they degrade to pixel units instead."),
    )
    permitted_parameters: dict[str, Any] = Field(default_factory=dict)
    backend: str = Field(default="deterministic", description="deterministic | sklearn | torch | llm")
    adapted_on: str | None = Field(default=None, description="RS dataset used for adaptation")
    citation: str | None = None


class ToolCall(BaseModel):
    """One line of the auditable execution trace."""

    step: int
    tool: str
    tool_version: str
    task: TaskType
    parameters: dict[str, Any] = Field(default_factory=dict)
    status: Literal["ok", "no_data", "error", "skipped"] = "ok"
    started_at: str | None = None
    duration_ms: int = 0
    message: str | None = None
    fact_keys: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None


class ToolResult(BaseModel):
    tool: str
    tool_version: str
    status: Literal["ok", "no_data", "error", "skipped"] = "ok"
    message: str | None = None
    facts: list[Fact] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)
    confidence: float | None = None
    answer: str | None = Field(default=None, description="Short direct answer for VQA-style tools")
    parameters: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Grounding report
# --------------------------------------------------------------------------
class NumericClaim(BaseModel):
    text: str
    value: float
    verified: bool
    matched_fact: str | None = None
    reason: str | None = None


class GroundingReport(BaseModel):
    narrator: Literal["llm", "template", "llm_rejected_fallback_template"] = "template"
    strict_mode: bool = True
    claims_checked: int = 0
    claims_verified: int = 0
    rejected_claims: list[NumericClaim] = Field(default_factory=list)
    verified_claims: list[NumericClaim] = Field(default_factory=list)
    fact_count: int = 0
    all_sources_real: bool = True
    passed: bool = True
    explanation: str = ""


# --------------------------------------------------------------------------
# API envelope
# --------------------------------------------------------------------------
class QueryRequest(BaseModel):
    #: May be empty **only** when a scene is supplied - uploading an image is
    #: itself a complete request ("analyse this"), and forcing the user to
    #: invent a sentence for it would be busywork. The controller substitutes a
    #: description request; :meth:`check` enforces the rest.
    query: str = Field(default="", max_length=2000)
    scene_id: str | None = Field(default=None, description="Bundled or uploaded scene identifier")
    scene_ids: list[str] = Field(default_factory=list, description="For explicit pair analysis")
    aoi_name: str | None = None
    bbox: list[float] | None = None
    dates: list[str] = Field(default_factory=list)
    use_llm: bool | None = None

    @model_validator(mode="after")
    def check(self) -> "QueryRequest":
        if not self.query.strip() and not (self.scene_id or self.scene_ids):
            raise ValueError(
                "Type a question, or upload an image to analyse on its own.")
        if self.bbox is not None and len(self.bbox) != 4:
            raise ValueError("bbox must be [west, south, east, north].")
        return self


class SummarySection(BaseModel):
    """One heading of the Query Analysis Summary card.

    Built by :mod:`app.agent.summary` from the facts that were measured. A
    section only exists when it has real content, so the UI can render every
    section it receives without checking for placeholders.
    """

    title: str
    points: list[str] = Field(default_factory=list)
    kind: str = Field(
        default="info",
        description="Hint for UI styling: query | location | geo | geo-none | image | "
                    "detected | findings | measure | quality | outcome | info",
    )


class QueryResponse(BaseModel):
    request_id: str
    query: str
    status: Literal["ok", "no_data", "needs_clarification", "unsupported", "error"] = "ok"
    plan: QueryPlan
    execution_trace: list[ToolCall] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)
    answer: str | None = None
    explanation: str = ""
    #: Short, sectioned digest of this response for the UI summary card. Derived
    #: entirely from the facts and plan above - it introduces no new numbers.
    summary: list[SummarySection] = Field(default_factory=list)
    grounding: GroundingReport = Field(default_factory=GroundingReport)
    confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)
    total_duration_ms: int = 0
    report_url: str | None = None
