"""Shared state passed between the controller and every specialist tool."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..datasources.gazetteer import bbox_area_km2
from ..schemas import Artifact, Provenance, QueryPlan
from .grounding import FactStore


@dataclass
class SceneData:
    """One analysable raster inside a request, whatever its origin."""

    role: str                       # primary | before | after | optical | sar
    label: str                      # human-facing, e.g. "MODIS Terra 2025-10-14"
    rgb: np.ndarray                 # (H, W, 3) uint8 display rendering
    bands: dict[str, np.ndarray]    # semantic band -> float 0..1
    valid: np.ndarray               # (H, W) bool
    modality: str
    provenance: Provenance
    bbox: list[float] | None = None
    date: str | None = None
    scene_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, int]:
        return self.rgb.shape[0], self.rgb.shape[1]

    @property
    def valid_fraction(self) -> float:
        return float(self.valid.mean())


@dataclass
class RunContext:
    """Everything a tool may read, plus where it writes results."""

    plan: QueryPlan
    store: FactStore
    scenes: dict[str, SceneData] = field(default_factory=dict)
    artifacts: list[Artifact] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Derived products shared between tools so nothing is computed twice.
    cache: dict[str, Any] = field(default_factory=dict)
    compatibility: dict[str, Any] = field(default_factory=dict)

    # -- geometry ---------------------------------------------------------
    @property
    def bbox(self) -> list[float] | None:
        """Where the analysed pixels actually are, or None.

        When a scene is loaded, **the scene is the only authority on location**.
        The plan's bbox comes from a place name parsed out of the question, and
        for an uploaded image that place has nothing to do with the pixels: the
        phrase "highlight the water body" once geocoded "body" to a real town
        and the uploaded photograph was then reported with areas in km² and
        coordinates in France. An image that carries no georeferencing must stay
        in pixel space no matter what the sentence mentioned.

        The plan's bbox is used only when no scene is loaded at all, which is
        the archive-retrieval path where it is the correct source.
        """
        if self.scenes:
            for s in self.scenes.values():
                if s.bbox:
                    return s.bbox
            return None
        return self.plan.bbox or None

    @property
    def shape(self) -> tuple[int, int]:
        for s in self.scenes.values():
            return s.shape
        return (0, 0)

    @property
    def scene_area_km2(self) -> float:
        bb = self.bbox
        return bbox_area_km2(tuple(bb)) if bb else 0.0

    @property
    def pixel_area_km2(self) -> float:
        h, w = self.shape
        n = h * w
        return (self.scene_area_km2 / n) if (n and self.bbox) else 0.0

    @property
    def georeferenced(self) -> bool:
        return self.bbox is not None

    @property
    def is_upload(self) -> bool:
        """True when the analysed pixels came from a file the user supplied."""
        return any(s.scene_id for s in self.scenes.values())

    def place_label(self) -> str:
        """How to name the analysed area in prose.

        For an uploaded image the place name the parser extracted describes a
        word in the question, not the image - "highlight the water body" once
        yielded "over Body". The file is the subject, so say so.
        """
        if self.is_upload:
            return "this image"
        return self.plan.aoi_name or "the requested area"

    # -- scene access -----------------------------------------------------
    def get(self, *roles: str) -> SceneData | None:
        for r in roles:
            if r in self.scenes:
                return self.scenes[r]
        return None

    def require(self, *roles: str) -> SceneData:
        s = self.get(*roles)
        if s is None:
            raise KeyError(f"No scene available for role(s) {roles}; have {sorted(self.scenes)}")
        return s

    def add_scene(self, scene: SceneData) -> None:
        self.scenes[scene.role] = scene
        self.store.add_provenance([scene.provenance])

    def add_artifacts(self, arts: list[Artifact]) -> list[str]:
        self.artifacts.extend(arts)
        return [a.id for a in arts]

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    # -- unit helpers -----------------------------------------------------
    def area_of(self, pixels: int) -> float | None:
        """Convert a pixel count to km², or None when not georeferenced."""
        return round(pixels * self.pixel_area_km2, 4) if self.georeferenced else None

    def area_unit(self) -> str:
        return "km2" if self.georeferenced else "pixels"
