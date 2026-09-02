"""Curated demo queries.

Each one exercises a different mandatory capability from problem statement
SIH26167, and each targets an area/date range verified to have real archive
coverage, so a live demo does not depend on luck.
"""
from __future__ import annotations

SAMPLE_QUERIES: list[dict] = [
    # ---- single-image VQA (mandatory baseline) --------------------------
    {
        "id": "vqa_water_chilika",
        "category": "Single-image VQA",
        "capability": "vqa",
        "query": "How much of Chilika Lake is covered by water right now?",
        "why": "Mandatory single-image visual question answering. The answer is looked up "
               "in the fact store, never generated.",
        "expects": "Water fraction and area in km², measured from an MNDWI segmentation.",
        "icon": "droplet",
        "eta_seconds": 8,
    },
    {
        "id": "vqa_ndvi_western_ghats",
        "category": "Single-image VQA",
        "capability": "vqa",
        "query": "What is the mean NDVI over the Western Ghats?",
        "why": "Named-index question routed to the spectral index engine.",
        "expects": "NDVI mean, median and percentile spread with a distribution histogram.",
        "icon": "leaf",
        "eta_seconds": 8,
    },

    # ---- captioning / scene description ---------------------------------
    {
        "id": "caption_sundarbans",
        "category": "Scene description",
        "capability": "caption",
        "query": "Describe the land cover and major features visible over the Sundarbans.",
        "why": "The problem statement's representative captioning query. Every noun and "
               "number traces to a measured class fraction.",
        "expects": "Composition breakdown, EuroSAT class distribution, index statistics.",
        "icon": "file-text",
        "eta_seconds": 12,
    },
    {
        "id": "caption_rann",
        "category": "Scene description",
        "capability": "caption",
        "query": "Describe what is visible over the Rann of Kutch.",
        "why": "A very different biome - checks that the segmenter is not tuned to one scene.",
        "expects": "Bare soil and salt-flat dominated composition.",
        "icon": "sun",
        "eta_seconds": 12,
    },

    # ---- text-guided grounding ------------------------------------------
    {
        "id": "ground_water_vembanad",
        "category": "Text-guided grounding",
        "capability": "grounding",
        "query": "Highlight the water body referred to in Vembanad Lake.",
        "why": "The problem statement's representative grounding query. Resolves a phrase "
               "to a mask, then to geo-referenced boxes.",
        "expects": "Ranked water regions with real areas, centroids and bounding boxes.",
        "icon": "crosshair",
        "eta_seconds": 8,
    },
    {
        "id": "ground_urban_hyderabad",
        "category": "Text-guided grounding",
        "capability": "grounding",
        "query": "Locate the built-up areas around Hyderabad.",
        "why": "Grounding a different target class through the same pipeline.",
        "expects": "Built-up regions delineated via NDBI, ranked by area.",
        "icon": "building",
        "eta_seconds": 8,
    },

    # ---- bi-temporal change (mandatory) ---------------------------------
    {
        "id": "change_chennai",
        "category": "Bi-temporal change",
        "capability": "change_detection",
        "query": "What changed around Chennai between January 2025 and October 2025, "
                 "and where did the change occur?",
        "why": "The problem statement's representative change query. Mandatory "
               "multi-image change analysis.",
        "expects": "CVA change map, land-cover transition matrix, ranked change regions.",
        "icon": "git-compare",
        "eta_seconds": 15,
    },
    {
        "id": "change_aral",
        "category": "Bi-temporal change",
        "capability": "change_detection",
        "query": "Compare the Aral Sea between 2015 and 2025 and tell me how the water "
                 "extent changed.",
        "why": "A decade-scale change with a known, dramatic ground truth - a good "
               "sanity check in front of judges.",
        "expects": "Large measured decrease in water area with a transition matrix.",
        "icon": "waves",
        "eta_seconds": 15,
    },
    {
        "id": "changevqa_vegetation",
        "category": "Bi-temporal change",
        "capability": "change_vqa",
        "query": "Has the vegetation cover in Kaziranga increased or decreased since 2023?",
        "why": "Change-based VQA: a directional question answered from a signed measured delta.",
        "expects": "A direction plus the magnitude in km² and percent.",
        "icon": "trending-up",
        "eta_seconds": 15,
    },

    # ---- optical-SAR cross-modal (mandatory) ----------------------------
    {
        "id": "fusion_sundarbans",
        "category": "Optical + SAR fusion",
        "capability": "optical_sar_fusion",
        "query": "Use the optical and SAR images together to identify built-up and "
                 "water-covered regions in the Sundarbans.",
        "why": "The problem statement's representative cross-modal query. Mandatory "
               "co-registered optical-SAR joint analysis.",
        "expects": "Co-registration proof, per-sensor water extents, agreement IoU, and "
                   "the area radar recovered from under cloud.",
        "icon": "layers",
        "eta_seconds": 25,
    },
    {
        "id": "fusion_chennai",
        "category": "Optical + SAR fusion",
        "capability": "optical_sar_fusion",
        "query": "Combine radar and optical data to map surface water near Chennai.",
        "why": "Shows SAR seeing through cloud where the optical sensor cannot.",
        "expects": "Fused water mask with each sensor's unique detections separated.",
        "icon": "radar",
        "eta_seconds": 25,
    },

    # ---- land cover / classification ------------------------------------
    {
        "id": "landcover_kolkata",
        "category": "Land-cover analysis",
        "capability": "landcover",
        "query": "Give me a land cover classification breakdown for Kolkata.",
        "why": "Runs the EuroSAT-adapted classifier alongside the index segmenter, so "
               "two independent methods can be compared.",
        "expects": "Class percentages, areas, and the classifier's own held-out accuracy.",
        "icon": "grid",
        "eta_seconds": 14,
    },

    # ---- index analysis --------------------------------------------------
    {
        "id": "index_burn",
        "category": "Index analysis",
        "capability": "index_analysis",
        "query": "Compute the normalised burn ratio over California.",
        "why": "Fire-severity index on a region where burn scars are common.",
        "expects": "NBR statistics, map and histogram.",
        "icon": "flame",
        "eta_seconds": 10,
    },

    # ---- time series -----------------------------------------------------
    {
        "id": "ts_ndvi_ghats",
        "category": "Time series",
        "capability": "time_series",
        "query": "Show me the NDVI trend over the Western Ghats over the last 8 months.",
        "why": "Multi-date retrieval with an ordinary-least-squares trend and honest "
               "accounting of dates that had no usable observation.",
        "expects": "Time-series chart, per-year slope, R², and a per-date coverage table.",
        "icon": "activity",
        "eta_seconds": 25,
    },

    # ---- the honest-failure demo ----------------------------------------
    {
        "id": "nodata_demo",
        "category": "No-data handling",
        "capability": "no_data",
        "query": "What was the NDVI over the Sundarbans in 1985?",
        "why": "Deliberately unanswerable: MODIS began observing in February 2000, so no "
               "satellite measured this. Shows the system refusing to invent a figure.",
        "expects": "An explicit unavailability message naming each sensor's start date - "
                   "no estimated value, no retrieval attempted.",
        "icon": "alert-triangle",
        "eta_seconds": 10,
    },
    {
        "id": "clarify_demo",
        "category": "No-data handling",
        "capability": "clarification",
        "query": "How much water is there?",
        "why": "Ambiguous by design: no area of interest. The controller asks rather "
               "than guessing a location.",
        "expects": "A clarification request, with no data retrieved.",
        "icon": "help-circle",
        "eta_seconds": 1,
    },

    # ---- search-box phrasing --------------------------------------------
    # Nobody types a full sentence into a search box. These are here because
    # the intent layer has to read keyword phrasing as well as it reads prose,
    # and the shortest ones are the strictest test of that.
    {
        "id": "short_kerala_flood",
        "category": "Short queries",
        "capability": "grounding",
        "query": "Kerala floods 2025",
        "why": "Three words, no verb. The intent layer reads the place, the phenomenon "
               "and the year, and selects flood mapping rather than a generic description.",
        "expects": "Surface-water extent over Kerala with MNDWI, water regions outlined.",
        "icon": "droplet",
        "eta_seconds": 10,
    },
    {
        "id": "short_hyderabad_change",
        "category": "Short queries",
        "capability": "change_detection",
        "query": "Hyderabad land change",
        "why": "No dates at all. Recognised as urban land-use change and run as a "
               "bi-temporal comparison against the same date a year earlier.",
        "expects": "Built-up change map with the km² gained or lost.",
        "icon": "building",
        "eta_seconds": 20,
    },
    {
        "id": "short_amazon_forest",
        "category": "Short queries",
        "capability": "change_detection",
        "query": "forest loss Amazon",
        "why": "Place last, phenomenon first. Word order does not matter to the parser.",
        "expects": "NDVI-based forest-cover comparison over the Amazon.",
        "icon": "leaf",
        "eta_seconds": 20,
    },
    {
        "id": "short_out_of_scope",
        "category": "Short queries",
        "capability": "scope",
        "query": "Delhi air pollution",
        "why": "Asks for something these sensors cannot measure. The system says so "
               "plainly, then reports the surface observation it can make - rather "
               "than quietly answering a different question.",
        "expects": "An explicit out-of-scope note naming Sentinel-5P, plus the real "
                   "surface land-cover analysis for Delhi.",
        "icon": "alert-triangle",
        "eta_seconds": 12,
    },
]
