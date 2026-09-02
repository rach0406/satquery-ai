# Limitations and assumptions

SatQuery AI · SIH26167 · Team Avengers

Every limitation here is also surfaced **inside the running application** — as a warning on the result, a caveat attached to the fact, or a note in the provenance record. Nothing in this file is hidden from the user.

---

## 1. Imagery is byte-scaled, not calibrated reflectance

**What.** NASA GIBS serves Corrected Reflectance as an 8-bit composite with a non-linear stretch designed for *visualisation*. It is real measured data from a real sensor, but it is not Level-2 surface reflectance.

**Consequence.** Index values are compressed toward zero. A mangrove canopy that reads NDVI ≈ 0.6 in Level-2 reflectance can read ≈ 0.26 here. Absolute index values should be read as **indicative**, and comparisons are only valid *within* the same product.

**What we did.** Segmentation thresholds are scene-adaptive rather than the literature constants, because applying constants defined on calibrated reflectance to a stretched product silently reclassifies healthy forest as bare soil. Every threshold used is reported in the result. The caveat travels in each `Provenance.notes`.

**Path to removing it.** Copernicus Data Space (Sentinel-2 L2A) or NASA AppEEARS provide calibrated reflectance; both require registration. The `datasources/` layer is a small interface — adding a credentialed connector does not touch the agent, the tools or the grounding.

---

## 2. The EuroSAT classifier is out of domain on coarse archive imagery

**What.** The classifier is genuinely adapted to remote sensing — trained here on 27,000 labelled Sentinel-2 patches, **85.91%** held-out accuracy, macro-F1 **0.858**. But EuroSAT is 10 m data: a 64×64 patch covers 640 m. MODIS through GIBS is ~200 m/px, so the same patch covers ~12.7 km — about 20× coarser than anything the model was trained on.

**Consequence.** Applied blind to MODIS it produces confident nonsense; it labelled the Sundarbans "Industrial" with 0.79 mean confidence.

**What we did.** The tool computes the scene's effective ground sample distance and, above 40 m/px:

- labels the fact `[out-of-domain indication]` so the caveat cannot be separated from the value;
- multiplies confidence by 0.35;
- **excludes it from the narration and the caption entirely**;
- raises a user-visible warning stating the exact scale mismatch;
- treats the resolution-independent index segmentation as authoritative.

Uploaded high-resolution imagery takes the full-confidence path. The classifier is fully valid on the domain it was trained for.

**Path to removing it.** Train a second head on coarse-resolution labelled data (e.g. MCD12Q1 land cover), or feed the system 10 m Sentinel-2 imagery, for which the existing model is already in domain.

---

## 3. Built-up detection from optical indices is refused, not guessed

**What.** NDBI cannot separate urban fabric from salt crust or dry sand at 250 m — all three are bright in SWIR.

**Consequence.** Naive Otsu thresholding reported the Rann of Kutch salt desert as **32% built-up**.

**What we did.** The built-up split requires the NDBI histogram to be genuinely bimodal (separability η ≥ 0.82, above the 2/π ≈ 0.637 analytic floor for a unimodal Gaussian) **and** the two sub-populations to be ≥ 0.18 NDBI apart. When the test fails, those pixels are reported as `bare_soil` and a warning explains why, pointing at SAR double-bounce as the appropriate discriminator.

**Consequence of the fix, stated plainly.** Dense urban areas such as Delhi are reported as "bare soil" when only optical data is available. That is a deliberate under-claim: the honest statement is *"these pixels are non-vegetated; this sensor cannot tell you more"*.

**Path to removing it.** Ask a cross-modal question — SAR is the right instrument, and `sar_analyzer` provides a built-up ranking when a radar scene is present.

---

## 4. SAR built-up is a heuristic, not a validated classifier

**What.** `sar_analyzer` ranks land pixels by a 50/50 blend of stretched backscatter and local texture and takes the top 20%.

**Consequence.** It is a relative ranking within one scene. It is not a certified land-cover product and the absolute fraction is not calibrated.

**What we did.** It is reported at confidence 0.45, the caveat is attached to the fact and becomes a user-visible warning, and the fact label says "likelihood". Note that SAR **water** detection is a different matter — specular reflection off smooth water is unambiguous physics and Otsu separates it cleanly, so that result is reported at 0.85.

---

## 5. SAR backscatter is relative, not decibels

OPERA RTC through GIBS is a byte-rendered γ⁰ composite. We report backscatter on a relative 0–1 scale and never claim calibrated dB. Removing this needs the OPERA RTC GeoTIFFs from ASF DAAC (free, but requires an Earthdata login).

---

## 6. Sentinel-1 coverage is sparse and lagging in places

**What.** OPERA RTC is published per orbital track and its global rollout is staged. Chennai had granules on 2025-10-02/14/26 but nothing in the 150 days before 2026-08-27.

**Consequence.** A cross-modal query may return a SAR scene weeks or months from the requested date.

**What we did.** Two-phase search (12-day repeat cycle, then a ±150-day sweep at 3-day steps). When the chosen acquisition is >20 days off, a warning states the exact offset and explains that genuine surface change across the gap will appear as sensor disagreement rather than sensor error. If nothing is found, the result is `no_data` listing every date probed — never a substituted scene.

AOIs with dense recent coverage: **Sundarbans, Chennai, Dubai, California, Aral Sea**.

---

## 7. Cloud is a hard physical limit

Optical sensors cannot see through cloud. During the Indian monsoon many AOIs are fully clouded for weeks.

**What we did.** Candidate dates are ranked by `coverage × (1 − cloud) × (1 − dark)`; the cloud fraction is measured and reported as a class; when the clearest available date is still heavily clouded the system says so and recommends SAR. Statistics are always computed over valid pixels only, and the valid fraction is a published fact.

**One subtle trap worth naming:** an *empty* archive tile contains no cloud, so ranking on clarity alone actively prefers no-data over real data. This produced a scene where every band was ≈ 0.02 and every index degenerated to ≈ 0 — presented as a confident measurement. The `dark_fraction` term and a mean-brightness floor in `fetch_raster` are the fix.

---

## 8. Land-cover classes are index-derived, not a certified product

The six classes come from spectral thresholds, not from a validated land-cover map. They carry no formal accuracy figure and no ground-truth validation. `Sparse vegetation / cropland` in particular mixes several real categories.

For an operational product you would validate against Bhuvan LULC or ESA WorldCover. The value here is that the method, the thresholds and the pixel counts are fully reported, so any number can be recomputed and checked.

---

## 9. Turbid and sediment-laden water is under-detected

In deltas such as the Sundarbans, suspended sediment raises reflectance across all bands, weakening both the MNDWI signal and the NIR-absorption confirmation. Some open water is therefore classified as bare soil, and mangrove fraction reads low during the monsoon. This is a genuine physical limitation of coarse optical data over turbid water; SAR handles it far better, which is exactly what the cross-modal path is for.

---

## 10. Place resolution

The built-in gazetteer holds 48 curated AOIs with hand-checked bounding boxes. Anything else goes to OpenStreetMap Nominatim, which is rate-limited and returns a single best guess.

**Note a real hazard we hit:** Nominatim matches almost any string — there is a place called "There!" and another called "Trend", so *"How much water is there?"* silently resolved to a real bounding box and reported confident statistics for a location nobody asked about. A stopword filter now refuses to geocode text with no plausible place token, and the controller asks for clarification instead. Refusing to geocode is the correct behaviour.

---

## 11. Archive time bounds

| Source | Earliest |
|---|---|
| MODIS Terra | 2000-02-24 |
| MODIS Aqua | 2002-07-04 |
| VIIRS SNPP | 2015-11-24 |
| Sentinel-1 OPERA RTC | 2023-12-15 |

Requests before these dates return `no_data` naming each start date. Nothing is extrapolated backwards.

---

## 12. Not implemented

Stated plainly rather than implied:

- **No fine-tuned vision-language transformer.** The problem statement permits "fine-tuned or otherwise adapted"; we adapted a classifier on EuroSAT with measured metrics rather than shipping an unadapted VLM. A RemoteCLIP/GeoChat-class model would need a GPU and hours of training, and would not have been honestly evaluable in the time available.
- **No VRSBench / RSVQA / CDVQA benchmark scores.** The evaluation harness is not built; those benchmarks need their annotation files. The tool interfaces match the task definitions, so a harness is additive.
- **No PostGIS.** Results are computed per request and cached as files. Nothing in the current feature set needs a spatial database; the proposal's PostGIS layer is deferred rather than faked.
- **No user accounts, no multi-tenancy, no rate limiting.** It is a demonstration console, not a deployed service.
- **Single-node only.** No distributed tiling for very large rasters; the analysis grid is capped at a configurable square (512 px by default).

---

## 13. Assumptions

1. The demo machine has internet access. If it does not, `SATQUERY_OFFLINE=true` serves the 14-day disk cache — run each demo query once beforehand and every one replays instantly, correctly badged *Cached satellite*.
2. NASA GIBS remains publicly available without credentials (it has been for over a decade).
3. Uploaded GeoTIFF pairs intended for change analysis are already co-registered; the system checks and refuses incompatible pairs rather than resampling them.
4. Analysis is performed in EPSG:4326. Areas are computed geodesically with a cosine-latitude correction, which is accurate to well under 1% at the AOI sizes used here.
