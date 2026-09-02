# SatQuery AI

**An agentic vision-language assistant for multimodal remote-sensing analysis through natural-language queries.**

> Smart India Hackathon 2026 · Problem Statement **SIH26167** · Indian Space Research Organisation (ISRO), Department of Space · Theme: Space Technology · Category: Software
> **Team Avengers**

Ask a question in plain English about anywhere on Earth. SatQuery AI classifies the task, checks which satellites actually observed that area, retrieves the real pixels, routes them through specialist models, and answers using **only what it measured**.

```
"What changed around Chennai between January 2025 and October 2025?"
        │
        ▼
  parse ─► validate ─► retrieve ─► select tools ─► measure ─► verify ─► explain
        │                                                        │
        │                                                        └─ every number traced
        ▼                                                           back to a measurement
  map · charts · tables · grounded explanation · auditable trace · downloadable report
```

---

## The one rule

**Every number this system reports was measured from real satellite pixels.**

This is enforced structurally, not by prompt engineering:

1. Only deterministic image-processing tools may create a number. Each one publishes a `Fact` carrying its value, unit, the method that produced it, the sample size, and the source.
2. The language model — when configured — does exactly two things: parse the question into a typed plan, and phrase the final narration. It is never shown imagery or raw arrays, only the fact list.
3. Before display, a verifier extracts **every numeral** in the narration and matches each back to a fact. Any number it cannot trace is a **rejected claim**, and under strict mode a single rejection discards the whole narration in favour of the deterministic template.
4. If the archive has no usable observation, the API returns `status: "no_data"` with the dates it checked. It does not estimate.

The Grounding tab in the UI shows this happening live: claims checked, claims traced, and which fact backed each one.

---

## Quick start

### Windows

```powershell
cd "Avengers_SatQueryAI"
.\start.ps1
```

### macOS / Linux

```bash
cd Avengers_SatQueryAI
./start.sh
```

The launcher creates a virtualenv, installs both dependency sets, adapts the remote-sensing classifier on EuroSAT (~95 MB download, ~3 min, one time), starts the API on `:8000` and the console on `:5173`, and opens a browser.

**No API keys are required.** NASA GIBS serves the imagery over open WMS with no credentials.

### Manual start

```bash
# backend
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && python -m app.ml.train_eurosat --limit-per-class 900   # optional
python -m uvicorn app.main:app --port 8000

# frontend, in a second terminal
cd frontend && npm install && npm run dev
```

| URL | What |
|---|---|
| http://localhost:5173 | Analysis console |
| http://127.0.0.1:8000/docs | Interactive API reference |
| http://127.0.0.1:8000/api/health | System status |

**Requirements:** Python 3.10+, Node 18+, an internet connection for live imagery.

---

## What it does

Everything the problem statement makes mandatory, plus the geospatial-query layer from our proposal.

| Capability | How it is implemented | Status |
|---|---|---|
| **Single-image VQA** *(mandatory)* | Question resolved against the measured fact store; refuses when no fact covers it | ✅ |
| **Scene captioning** *(one additional single-image task required)* | Description composed only from measured class fractions, index statistics and classifier output | ✅ |
| **Text-guided region grounding** *(the other option — both are implemented)* | Phrase → class mask → cleaned connected components → geo-referenced boxes with real areas | ✅ |
| **Bi-temporal change analysis** *(mandatory)* | Change Vector Analysis + Otsu cut, per-index delta maps, class transition matrix, ranked change regions | ✅ |
| **Change-based VQA** *(mandatory)* | Directional questions answered from a signed measured delta | ✅ |
| **Optical–SAR cross-modal analysis** *(mandatory)* | Real Sentinel-1 RTC + MODIS/VIIRS on an identical grid; co-registration asserted; agreement IoU; area radar recovers from under cloud | ✅ |
| **Remote-sensing model adaptation** *(mandatory)* | Classifier trained here on **EuroSAT** (27,000 labelled Sentinel-2 patches) over a 196-D RS feature representation | ✅ **85.91%** held-out accuracy, macro-F1 **0.858** |
| **Agentic orchestration** *(mandatory)* | Closed registry of 10 specialists; task/modality-based selection; only declared parameters reach a tool | ✅ |
| **Input compatibility checking** | Format, band mapping, georeferencing, grid, extent, modality and pair compatibility all asserted, not assumed | ✅ |
| **Auditable execution summary** | Every stage — including skipped ones and *why* — with parameters, timings, facts and artefacts | ✅ |
| **Confidence estimation** | Per-tool confidence; out-of-domain model use is detected and down-weighted | ✅ |
| **Downloadable report** | Complete evidence record: plan, trace, facts, provenance, grounding verdict | ✅ |
| **Index time series** | Multi-date retrieval with an OLS trend, R², and explicit accounting of dates with no usable observation | ✅ |

---

## Data sources — all real, all credential-free

| Source | Instrument | Resolution | Used for |
|---|---|---|---|
| **NASA GIBS** MODIS Terra/Aqua Corrected Reflectance | MODIS | 250 m | True colour + SWIR/NIR/Red → 5-band multispectral cube |
| **NASA GIBS** VIIRS SNPP Corrected Reflectance | VIIRS | 375 m | Sharper alternative optical stack |
| **NASA GIBS** OPERA L2 RTC | **Sentinel-1 C-SAR** | 30 m | Cloud-penetrating radar backscatter |
| **NASA GIBS** OPERA L3 DSWx | Sentinel-1 | 30 m | Operational surface-water extent |
| **NASA GIBS** MOD13 NDVI, MOD11 LST, SST | MODIS | 250 m – 4 km | Additional derived layers |
| **OpenStreetMap Nominatim** | — | — | Optional place-name resolution beyond the built-in gazetteer |
| **EuroSAT** (Helber et al., 2019) | Sentinel-2 | 10 m | Training data for the RS-adapted classifier |

### How the multispectral cube is built

GIBS renders `TrueColor` (B1 red / B4 green / B3 blue) and `Bands721` (B7 SWIR2 / B2 NIR / B1 red) onto the **same** EPSG:4326 grid for an identical BBOX/WIDTH/HEIGHT request. Stacking the two responses yields a genuine, pixel-aligned 5-band cube — blue, green, red, NIR, SWIR2 — without touching a single credential-gated archive. The same trick makes optical and SAR co-registered **by construction**, which the system then verifies rather than assumes.

**Stated honestly everywhere it matters:** GIBS Corrected Reflectance is byte-scaled with a non-linear stretch for visualisation. Indices derived from it are *indicative*, not calibrated Level-2 surface reflectance. This is why the segmentation thresholds are scene-adaptive rather than the textbook constants — see [LIMITATIONS.md](LIMITATIONS.md).

---

## Demo queries

Twenty curated queries ship behind the **Suggested queries** panel in the workspace, each exercising a different mandatory capability against an area/date verified to have real coverage. Four of them are deliberately search-box short ("Kerala floods 2025") to exercise the intent layer. Full walkthrough in **[DEMO_SCRIPT.md](DEMO_SCRIPT.md)**.

```
How much of Chilika Lake is covered by water right now?
Describe the land cover and major features visible over the Sundarbans.
Highlight the water body referred to in Vembanad Lake.
What changed around Chennai between January 2025 and October 2025, and where?
Compare the Aral Sea between 2015 and 2025 and tell me how the water extent changed.
Has the vegetation cover in Kaziranga increased or decreased since 2023?
Use the optical and SAR images together to identify built-up and water-covered
    regions in the Sundarbans.
Show me the NDVI trend over the Western Ghats over the last 8 months.

What was the NDVI over the Sundarbans in 1985?   ← refuses: archive starts 2000
How much water is there?                          ← asks which area, does not guess
```

The last two matter as much as the rest. **Show them to the judges.**

---

## Architecture

```
Avengers_SatQueryAI/
├── backend/
│   └── app/
│       ├── main.py              FastAPI application
│       ├── config.py            environment-driven settings
│       ├── schemas.py           Fact / Provenance / QueryPlan / ToolCall contracts
│       ├── agent/
│       │   ├── controller.py    the agentic orchestrator + SSE streaming
│       │   ├── nlu.py           rule parser (always) + LLM parser (optional)
│       │   ├── registry.py      closed tool registry + parameter enforcement
│       │   ├── acquisition.py   archive availability search, compatibility checks
│       │   ├── grounding.py     the fact store and the numeric verifier
│       │   ├── explain.py       template + LLM narrators
│       │   └── context.py       per-request shared state
│       ├── tools/               10 specialists: optical / temporal / radar / answer
│       ├── processing/          indices, change, SAR, regions  (pure numpy)
│       ├── datasources/         GIBS client, gazetteer, image I/O
│       ├── ml/                  EuroSAT feature extractor, trainer, inference
│       └── api/                 routes + curated demo queries
├── frontend/                    React 18 + Vite + Tailwind + Leaflet + Plotly
├── data/                        cache, models, uploads, reports  (regenerated)
└── docs/
```

Full design rationale, the pipeline contract, and the grounding proof: **[ARCHITECTURE.md](ARCHITECTURE.md)**.

### Technology choices

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.10+ / FastAPI | Typed request/response models, automatic OpenAPI, native SSE |
| Processing | NumPy / SciPy / Pillow | Deterministic, fast, and installs everywhere — no GDAL build required |
| ML | scikit-learn `HistGradientBoosting` over a hand-built RS feature space | Trains in ~25 s on CPU, loads instantly, no GPU or 2 GB wheel at demo time |
| Frontend | React + Vite + Tailwind | Fast HMR, small app shell, no runtime CSS cost |
| Maps | Leaflet | Image overlays with geographic bounds — exactly what raster results need |
| Charts | Plotly (bundled, not CDN) | Zoom/pan on scientific distributions, and nothing to fetch at demo time |
| LLM | Anthropic Claude, **optional** | Strict tool calling for typed plans; never a source of numbers |

`rasterio`, `torch` and `anthropic` are all **optional** and auto-detected. Their absence degrades one feature gracefully and says so — it never breaks the pipeline.

---

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/query` | Run the full pipeline, return the complete evidence record |
| `POST` | `/api/query/stream` | Same, as Server-Sent Events — one message per stage (drives the live pipeline view) |
| `POST` | `/api/parse` | NLU stage alone: show intent + parameter extraction |
| `GET` | `/api/locate?q=` | Resolve just the place named in a query — cheap enough to call while typing |
| `POST` | `/api/auth/signup` · `/api/auth/login` | Create an account / sign in (username **or** email) |
| `POST` | `/api/auth/check-username` | Is this username free? |
| `GET` | `/api/auth/me` · `POST /api/auth/logout` | Current session / discard it |
| `GET` | `/api/health` | Status, LLM availability, RS model metrics |
| `GET` | `/api/catalog` | Layers, indices, classes, resolvable places, data policy |
| `GET` | `/api/registry` | The tool registry and per-task workflows |
| `GET` | `/api/model` | Full model card, incl. confusion matrix |
| `GET` | `/api/samples` | The 20 demo queries |
| `POST` | `/api/scenes/upload` | Ingest GeoTIFF/TIFF/PNG/JPEG + compatibility report |
| `GET` | `/api/scenes` | Loaded scenes |
| `POST` | `/api/report` · `GET /api/report/{id}` | Persist / fetch an analysis record |

```bash
curl -X POST http://127.0.0.1:8000/api/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"How much of Chilika Lake is covered by water right now?"}'
```

---

## Using your own imagery

Upload a **GeoTIFF/TIFF** (geospatial) or **PNG/JPEG** (benchmark chips) under **Analyse an image** in the workspace - no text query required, since handing over a scene is itself the request. On ingest the system reports what it actually found — driver, dtype, band count, band mapping and whether that mapping came from file metadata or was inferred, nodata value, CRS, transform, derived WGS84 bounds, and valid-pixel fraction.

Select two scenes and it checks pair compatibility — identical grid, identical extent, shared bands, modality — and classifies the pair as **bi-temporal** or **cross-modal** automatically. Incompatible pairs are refused with the specific reason.

Install `rasterio` (`pip install rasterio`) for full GeoTIFF georeferencing and per-band metadata. Without it, TIFFs still load through Pillow and the system reports that georeferencing was unavailable rather than inventing a transform.

---

## Testing

```bash
cd backend && python -m pytest -q          # 51 tests, ~1 s
```

Coverage includes: index formulas against their definitions; segmentation against a synthetic scene with a known answer; the bimodality gate refusing to split a uniform scene; change detection finding a planted change; SAR water detection; fusion cloud-recovery accounting; registry parameter rejection and clamping; and — most importantly — the grounding verifier accepting legitimate reformulations while rejecting invented numbers.

---

## Configuration

Everything is optional; see [`.env.example`](.env.example). The most useful:

| Variable | Default | Effect |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Enables the LLM parser and narrator. Without it, rules + template. |
| `SATQUERY_STRICT_GROUNDING` | `true` | Discard any narration containing an untraceable number |
| `SATQUERY_RASTER_SIZE` | `512` | Analysis grid side in pixels |
| `SATQUERY_OFFLINE` | `false` | Serve only from cache — a safety net if venue Wi-Fi fails |

**Offline safety net:** every retrieved tile is cached on disk for 14 days. Run each demo query once beforehand and they will all replay from cache in well under a second, with the badge correctly reading *Cached satellite* rather than *Live satellite*.

---

## Known limitations

Documented honestly and in full in **[LIMITATIONS.md](LIMITATIONS.md)**. The headlines:

- GIBS imagery is byte-scaled for visualisation, so index values are indicative rather than calibrated reflectance.
- The EuroSAT classifier is trained at 10 m; on 250 m MODIS it is **automatically detected as out-of-domain**, down-weighted, excluded from the narration, and flagged in the UI.
- Optical built-up detection is refused when NDBI is not genuinely bimodal — salt crust, sand and urban fabric are not separable by index alone at 250 m.
- OPERA RTC Sentinel-1 coverage is track-based and its global rollout is staged, so some areas have multi-month gaps. The system searches ±150 days and states the temporal offset.

---

## Credits

**Team Avengers** — Smart India Hackathon 2026, problem statement SIH26167 (ISRO / Department of Space).

Imagery courtesy of NASA EOSDIS GIBS. EuroSAT: Helber, Bischke, Dengel & Borth, *IEEE JSTARS*, 2019. Methods: Otsu 1979; Rouse 1974; McFeeters 1996; Xu 2006; Key & Benson 2006; Zha 2003; Malila 1980 (CVA); Lee 1980 (speckle filter).

Licensed MIT.
