# Architecture

SatQuery AI · SIH26167 · Team Avengers

---

## 1. The problem this design solves

A general LLM asked *"how much of Chilika Lake is under water?"* will produce a confident, fluent, **fabricated** percentage. It has no pixels. The number will look exactly like a real one.

The problem statement calls for an "evidence-grounded response". We took that literally and made fabrication *structurally impossible* rather than discouraged:

> **A number can only reach the user if a deterministic tool measured it from retrieved pixels.**

Everything below exists to enforce that sentence.

---

## 2. The pipeline

```
                    natural-language question
                              │
   ┌──────────────────────────▼──────────────────────────┐
   │ 1. PARSE      rule parser (always) ⊕ LLM parser     │  → QueryPlan
   │               task · AOI · dates · classes · indices │
   ├─────────────────────────────────────────────────────┤
   │ 2. VALIDATE   AOI resolvable? dates in archive?      │  → clarify / no_data
   │               indices supported?                     │
   ├─────────────────────────────────────────────────────┤
   │ 3. ACQUIRE    probe what the sensors ACTUALLY saw    │  → co-registered
   │               coverage · darkness · cloud            │     Scenes + probe log
   │               compatibility asserted, not assumed    │
   ├─────────────────────────────────────────────────────┤
   │ 4. SELECT     closed registry → eligible specialists │  → tool list + reasons
   │               task ∩ input config ∩ modality         │     for each rejection
   ├─────────────────────────────────────────────────────┤
   │ 5. EXECUTE    only declared parameters reach a tool  │  → Facts + Artifacts
   │               each tool publishes Facts              │     + ToolCall trace
   ├─────────────────────────────────────────────────────┤
   │ 6. GROUND     narrate, then verify EVERY numeral     │  → GroundingReport
   │               untraceable number ⇒ narration dropped │
   ├─────────────────────────────────────────────────────┤
   │ 7. RESPOND    answer · explanation · map · charts ·  │
   │               tables · trace · provenance · report   │
   └─────────────────────────────────────────────────────┘
```

Each stage emits a `ToolCall` into the trace — **including stages that are skipped, and why**. The trace is a deliverable, not a debug log.

---

## 3. The grounding mechanism

### 3.1 Facts are the only currency

```python
Fact(
    key="water_fraction",
    label="Water share",
    value=0.2841,
    unit="fraction",
    method="74,489 of 262,144 valid pixels; Otsu-adaptive MNDWI water cut at +0.118, "
           "NIR-confirmed below 0.087",
    tool="landcover_segmenter",
    source="NASA GIBS / MODIS Terra True Colour",
    sample_size=262144,
)
```

`method` is not decoration. It is the audit trail: which pixels, which threshold, which rule. The UI renders it in the fact table, so a judge can ask *"where does 28.41% come from?"* and get a complete answer on screen.

### 3.2 The LLM is fenced in

The language model is used for two things and is structurally prevented from doing more:

| Stage | What it receives | What it may return |
|---|---|---|
| **Parsing** | The question text and today's date | A typed `QueryPlan` via **strict tool calling** — enum-constrained task, place string, ISO dates. No prose path exists. |
| **Narration** | The **fact list as JSON**. Never an image, never an array, never a pixel. | 3–6 sentences of prose |

Its parse output is then **re-validated field by field** — the place must resolve, dates must parse and fall inside the archive, indices must exist. Anything failing validation falls back to the rule parser's value.

### 3.3 The verifier

```python
verify_text(narration, fact_store) -> (verified_claims, rejected_claims)
```

1. Mask spans that are structurally numeric, not measurements: ISO dates, years, `EPSG:4326`, band ids (`B1/B4/B3`, `Bands721`), raster dimensions (`512×512`), ordinals (`10th–90th`), unit suffixes (`km²`, `km2`), metric names.
2. Extract every remaining numeral.
3. Match each against every legitimate representation of every fact: the exact value, a fraction rendered as a percentage, the magnitude of a signed value (prose says *"shrank by 1,059.17 km²"*; the fact stores `−1059.17`), and thousands.
4. Anything unmatched is a **rejected claim**.

Under `SATQUERY_STRICT_GROUNDING` (default on) **one** rejection discards the entire LLM narration and ships the deterministic template instead — which is then itself verified rather than trusted.

**The LLM's worst-case failure mode is therefore degraded prose, never a fabricated statistic.**

### 3.4 Refusing is a first-class outcome

| Situation | Response |
|---|---|
| No place in the question | `needs_clarification` — asks which area |
| Date before 2000-02-24 | `no_data` — names each sensor's start date |
| Sensor never observed the AOI | `no_data` + the probe log of every date checked |
| Archive slot exists but holds no imagery | Rejected at fetch; the date search moves on |
| Every tool produced nothing | `no_data` — no figure reported |
| No fact answers the question | The VQA tool lists what *was* measured instead |

---

## 4. The agentic controller

### 4.1 Registry, not free choice

Ten specialists, each declaring what it serves and exactly which parameters it accepts:

| Tool | Backend | Tasks | Needs |
|---|---|---|---|
| `rs_scene_classifier` | sklearn, **EuroSAT-adapted** | landcover, caption, vqa, fusion | optical |
| `spectral_index` | deterministic | index, vqa, caption, landcover, grounding, fusion | optical |
| `landcover_segmenter` | deterministic | landcover, caption, vqa, grounding, index, fusion | optical |
| `region_grounder` | deterministic | grounding, vqa | optical |
| `change_analyzer` | deterministic | change_detection, change_vqa | optical, bi-temporal |
| `sar_analyzer` | deterministic | fusion, vqa, caption, landcover, grounding | **sar** |
| `optical_sar_fusion` | deterministic | fusion | **optical + sar** |
| `timeseries_analyzer` | deterministic | time_series | optical |
| `vqa_resolver` | deterministic | vqa, change_vqa, grounding, index, ts, fusion, change | — |
| `scene_captioner` | deterministic | caption | — |

Selection is the intersection of **task ∩ input configuration ∩ available modality**. Every rejection is recorded with its reason — the trace shows both what ran and what did not.

### 4.2 Parameter enforcement

`validate_parameters()` is a hard boundary. An undeclared key is dropped and logged; an out-of-range value is clamped and logged; an unknown enum member is removed and logged. A tool cannot be reached with a parameter it never declared.

```
"registry_notes": [
  "rejected parameter 'secret_backdoor': not permitted for spectral_index",
  "clamped 'max_regions' 9999 -> 20 (above permitted maximum)"
]
```

---

## 5. Data acquisition — the hard part

Getting real pixels is easy. Getting *usable* real pixels, and knowing when you have not, is the engineering.

### 5.1 Three failure modes that must not be conflated

| Mode | Signature | Wrong conflation |
|---|---|---|
| **Not covered** | transparent tile | — |
| **Empty** | opaque, near-black tile | Reads as *perfectly cloud-free*. Every band ≈ 0, every index degenerates to ~0, and the system reports a confident measurement of nothing. |
| **Clouded** | real imagery, surface hidden | Reads as land cover. A monsoon cloud deck gets segmented and reported. |

`probe_scene_quality()` measures all three and ranks candidate dates by

```
usable = coverage × (1 − cloud_fraction) × (1 − dark_fraction)
```

Ranking on clarity alone actively **prefers** empty tiles — this was a real bug caught in testing, and the dark term is the fix. `fetch_raster()` additionally rejects any scene whose mean brightness falls below 0.035 as an unpublished archive slot.

### 5.2 Co-registration by construction, verified anyway

Optical and SAR are requested from GIBS with an **identical** `BBOX/WIDTH/HEIGHT`, so GIBS reprojects both onto the same grid — they are pixel-aligned by construction. The problem statement asks the controller to *check* compatibility, so `check_coregistration()` asserts identical shape and extent post-fetch and reports the max corner offset in degrees. An assertion that actually runs beats an assumption.

### 5.3 Sentinel-1 availability search

OPERA RTC is published per orbital track and its global rollout is staged: an AOI may have a granule every 12 days for months, then nothing for a season. Two phases:

1. the nominal 12-day repeat cycle ±4 cycles, plus the 6-day complementary track;
2. if empty, a sweep every 3 days across ±150 days.

If the chosen acquisition is more than 20 days from what was asked, the system **says so** rather than presenting a non-simultaneous pair as simultaneous.

---

## 6. Measurement layer

### 6.1 The 5-band cube from credential-free imagery

| GIBS composite | R | G | B |
|---|---|---|---|
| `CorrectedReflectance_TrueColor` | B1 red | B4 green | B3 blue |
| `CorrectedReflectance_Bands721` | B7 SWIR2 | B2 NIR | B1 red |

Same grid ⇒ stack ⇒ **blue, green, red, NIR, SWIR2**. That unlocks NDVI, NDWI, MNDWI, NBR, NDBI, BSI and VARI from imagery that needs no login.

### 6.2 Why thresholds are adaptive

The literature constants (NDVI 0.35 closed canopy, 0.15 sparse) are defined on **calibrated surface reflectance**. GIBS applies a non-linear visualisation stretch, which compresses NDVI toward zero: a mangrove canopy reading 0.6 in Level-2 can read ~0.26 here. Applying the textbook constant silently reclassifies healthy forest as bare soil.

So the vegetation split is placed by Otsu on the scene's own land-pixel NDVI distribution, bounded, and **reported** in `thresholds` and in the method string.

### 6.3 The bimodality gate — refusing to invent a split

Otsu always returns a cut, even for a perfectly unimodal population. It will happily bisect a uniform salt flat and call half of it built-up.

The separability measure

```
η = σ²_between / σ²_total   ∈ [0, 1]
```

says whether the cut corresponds to a real gap. **Critically**, Otsu applied to a single Gaussian cuts at the mean and yields exactly

```
η = 2/π ≈ 0.637
```

so any gate at or below 0.637 can never reject a unimodal population. This was found by a unit test — the original gate was 0.55 and was therefore inert. The gates now sit above the analytic floor:

| Split | Gate | Rationale |
|---|---|---|
| water, vegetation | `η ≥ 0.75` | above the 2/π unimodal floor with margin |
| **built-up** | `η ≥ 0.82` **and** class gap ≥ 0.18 NDBI | at 250 m, salt crust, dry sand and urban fabric all read as high NDBI |

When the gate refuses, the pixels stay `bare_soil` and a **note becomes a user-visible warning** explaining why — and pointing at SAR double-bounce as the appropriate discriminator.

### 6.4 Water needs physics, not just a ratio

A normalised index is a ratio, so haze — which lifts green reflectance across a whole scene — shifts the entire MNDWI distribution upward and can push dry land above any absolute cut. A hazy Kolkata scene measured **82% water** on MNDWI alone.

Liquid water absorbs NIR almost completely under every illumination and stretch, so the dark NIR mode is the most transferable water signature available. Water now requires **both** the index evidence and NIR confirmation. Kolkata fell to a plausible 33%, the Thar Desert to 0%, and the Sahara reports 98% bare soil.

### 6.5 Cross-modal fusion

| Physics | Consequence |
|---|---|
| Smooth water reflects radar away (specular) | very dark → Otsu-separable, highly reliable |
| Urban corner reflectors double-bounce | bright **and** rough → heuristic, reported as such |
| Vegetation volume-scatters | intermediate |

Fusion rule, deliberately explainable: SAR wins wherever the optical view is cloud-obstructed; elsewhere the two are OR-ed. Reported: per-sensor extent, agreement IoU, each sensor's unique detections, and **the area radar recovered from under cloud** — the concrete operational value of the pair.

---

## 7. Remote-sensing adaptation

The problem statement requires a visual component adapted to remote-sensing imagery. `app/ml/train_eurosat.py` downloads **EuroSAT** — 27,000 labelled Sentinel-2 patches, 10 land-use classes — extracts a 196-dimensional RS representation (spectral moments, RGB vegetation/soil indices, multi-scale texture via a summed-area-table local σ, colour histograms, 3×3 spatial layout, anisotropy) and fits a gradient-boosted classifier.

**Measured on a stratified held-out split the model never saw:**

| Metric | Value |
|---|---|
| Accuracy | **85.91%** |
| Macro-F1 | **0.858** |
| Best classes | SeaLake 0.98 · Forest 0.95 · Residential 0.91 · Industrial 0.91 |
| Weakest | Highway 0.67 (the known-hardest EuroSAT class) |
| Train / test | 6,750 / 2,250 |
| Fit time | 23.8 s, CPU only |

The API serves those numbers verbatim from the training report. Nothing about model performance is asserted from memory.

### 7.1 Knowing when the model does not apply

EuroSAT is 10 m Sentinel-2: a 64×64 patch covers 640 m. MODIS via GIBS is ~200 m/px, so the same patch covers **12.7 km** — roughly 20× coarser than anything the model saw. Applied blind it returns confident nonsense (it labelled the Sundarbans "Industrial").

The tool therefore computes the scene's effective GSD and, when it exceeds 40 m:

- labels the fact `[out-of-domain indication]`, so the caveat is inseparable from the value;
- scales confidence by 0.35;
- **excludes it from the narration and the caption entirely**;
- raises a user-visible warning explaining the scale mismatch;
- defers to the resolution-independent index segmentation as authoritative.

Uploaded high-resolution imagery takes the full-confidence path. A system that knows the limits of its own model is worth more than one that does not.

---

## 8. Frontend

React 18 + Vite + Tailwind, with Leaflet for georeferenced overlays and Plotly bundled locally (nothing fetched at demo time).

The **live pipeline view** is driven by real Server-Sent Events from the controller — the timings shown are the actual measured ones. No stage is delayed for effect.

Five result tabs: **Map** (raster overlays with opacity, basemap switch, legend, clickable region boxes) · **Charts** · **Data** (tool tables + the complete fact store) · **Grounding** (verification rate, traced numbers, rejected claims, provenance with the exact request URLs) · **Trace** (every step, expandable to full parameter JSON).

### Chart colour

Categorical slots were validated with a CVD/contrast checker on the dark chart surface: all pass the lightness band, chroma floor, adjacent CVD separation (worst ΔE 8.4), the normal-vision floor (worst ΔE 19.3) and 3:1 contrast.

Composition charts deliberately use a **single hue** — the class name is already on the category axis, so colour there would be redundant, and a six-way categorical split cannot clear the all-pairs CVD floor.

The thematic land-cover palette spreads **lightness** across classes rather than holding a uniform band. That is a documented deviation: uniform lightness collapsed the worst normal-vision pair to ΔE 10.6, while the lightness-spread version reaches ΔE 22.0 and lands CVD in the 6–8 band — legal because every class map and legend ships the class name and its measured value beside the swatch. Lightness also survives all three CVD simulations, so it is the channel doing the real work.

---

## 9. Failure behaviour

| Failure | Behaviour |
|---|---|
| No `ANTHROPIC_API_KEY` | Rule parser + template narrator. Full pipeline, zero degradation in correctness. |
| LLM call fails or times out | Silently falls back to the template |
| LLM invents a number | Verifier catches it; narration replaced; rejection shown in the UI |
| `rasterio` absent | TIFFs load via Pillow; system reports georeferencing unavailable |
| RS classifier untrained | That tool reports itself unavailable; others proceed |
| Basemap tiles blocked | Map warns; analysis overlays unaffected |
| SSE blocked by a proxy | Client falls back to `POST /api/query` |
| Network down | `SATQUERY_OFFLINE=true` serves the 14-day disk cache; uncached queries return `no_data` |
| A tool raises | Caught, recorded as `error` in the trace, pipeline continues |

**No path fabricates a number.** Every degradation is visible.

---

## 10. Mapping to the problem statement

| SIH26167 requirement | Where |
|---|---|
| Interpret the query, classify the task | `agent/nlu.py` → `QueryPlan` |
| Check number, modality, format, metadata, compatibility | `agent/acquisition.py`, `datasources/imagery_io.py` |
| Select from a predefined registry | `agent/registry.py` |
| Configure only permitted parameters | `registry.validate_parameters()` |
| Combine textual and spatial outputs | `Fact` + `Artifact` merged in `RunContext` |
| Estimate confidence | Per-tool, plus out-of-domain down-weighting |
| Return visual evidence | Overlays, boxes, charts, tables |
| Auditable execution summary | `execution_trace` — task, tools, versions, parameters, timings |
| Single-image VQA (mandatory) | `tools/answer.py::run_vqa_resolver` |
| One additional single-image task | **Both** captioning and grounding implemented |
| Multi-image change analysis (mandatory) | `tools/temporal.py` + `processing/change.py` |
| Cross-modal optical–SAR (mandatory) | `tools/radar.py` + `processing/sar.py` |
| RS fine-tuning / domain adaptation | `ml/train_eurosat.py` — 85.91% held-out |
| Downloadable reports | `POST /api/report`, plus one-click JSON export |
