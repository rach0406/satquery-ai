# Demo script — SIH 2026 internal round

SatQuery AI · SIH26167 · Team Avengers
**Target: 7 minutes + questions.**

---

## Before you walk in

```powershell
.\start.ps1
```

Then **run each query below once** while you still have good Wi-Fi. Every tile is cached for 14 days, so on stage each one replays in well under a second and the badge honestly reads *Cached satellite* instead of *Live satellite*. If the venue network dies entirely, set `SATQUERY_OFFLINE=true` and the whole demo still works.

**Pre-flight checklist**

- [ ] Reference drawer → Live status shows **Backend online**, **RS classifier 85.9% acc**, **Strict grounding on**
- [ ] Browser zoom 80–90% so the pipeline strip and result fit one screen
- [ ] Second tab open on `http://127.0.0.1:8000/docs`
- [ ] Warm the six queries below

---

## The 45-second opening

> "Ask a general AI how much of Chilika Lake is under water and it will give you a confident percentage. It has never seen a satellite image. The number is invented, and it looks exactly like a real one.
>
> SatQuery AI is built so that cannot happen. Every number you are about to see was measured from real satellite pixels, and the system can prove it for each one individually."

---

## 1 · The core loop (90 s)

**Query:** *How much of Chilika Lake is covered by water right now?*

Point at the pipeline strip as it runs — these are **real measured timings**, streamed from the backend over SSE.

> "Understand → validate → retrieve → select tools → measure → verify → explain.
>
> It parsed this as single-image VQA over Chilika Lake, then probed the NASA archive to find which dates MODIS actually observed and how cloudy each was. It picked the clearest one. Then it ran four specialists and answered."

**→ Map tab.** Real MODIS imagery, land-cover overlay, opacity slider, legend with measured percentages.

**→ Data tab, scroll to the fact store.**

> "This is the whole point. Every quantity, with the method that produced it. Water share came from 145,000 of 262,000 valid pixels, using an Otsu-adaptive MNDWI cut at this exact threshold, confirmed against near-infrared absorption. Nothing here is a model's opinion."

---

## 2 · The grounding proof — *the moment that wins it* (75 s)

**→ Grounding tab.**

> "Ten numeric claims in that explanation. Ten traced back to a specific measurement. Zero rejected.
>
> Here's the architecture that guarantees it. Only deterministic image-processing tools can create a number. The language model — when we give it a key — does two jobs: it parses your question into a typed plan, and it phrases the answer. It is **never shown an image**, only this fact list. Then a verifier pulls every numeral out of the generated text and matches it back. If even one number can't be traced, we throw away the whole narration and ship the deterministic version instead.
>
> So the worst thing our LLM can do is write duller prose. It cannot invent a statistic."

Scroll to **Provenance** — click *exact request URL used*.

> "And that's the actual NASA URL we called. A judge can paste it into a browser and see the same pixels."

---

## 3 · Refusing to answer (45 s) — **do not skip this**

**Query:** *What was the NDVI over the Sundarbans in 1985?*

> "MODIS launched in 1999. There is no observation. A chatbot would give you a plausible NDVI. This says no data, and names each sensor's start date."

**Query:** *How much water is there?*

> "No location. Rather than quietly picking somewhere and reporting a confident number for the wrong place, it asks.
>
> That one's more subtle than it looks — the geocoder we use will match almost any word. There's a village called 'There'. We caught that in testing and now refuse to geocode text with no real place name in it."

---

## 4 · Bi-temporal change — mandatory capability (75 s)

**Query:** *What changed around Chennai between January 2025 and October 2025, and where did the change occur?*

> "Two dates. For each, it searched for a genuinely clear acquisition — neither requested date was usable, so it used the nearest clear ones and told us so in the caveats."

**→ Map tab**, switch layers: Before → After → Change map.

> "Change Vector Analysis across all five bands, split by an Otsu threshold on the change magnitude. Blue is increase, red is decrease."

**→ Charts:** the transition bars, before/after composition, Δindex histograms.
**→ Data:** the land-cover transition matrix in km².

> "Not 'things changed'. **This** class became **that** class, over **this many** square kilometres, **here** — with geo-referenced boxes you can click."

---

## 5 · Optical + SAR fusion — the hardest requirement (90 s)

**Query:** *Use the optical and SAR images together to identify built-up and water-covered regions in the Sundarbans.*

> "This is the requirement most teams will skip. It needs co-registered optical and radar.
>
> Radar is an active sensor — it works through cloud and at night. During a monsoon flood the optical sensor returns a white cloud deck; the radar returns the flood."

**→ Data tab → Co-registration check table.**

> "We request both from GIBS with an identical bounding box and pixel grid, so they're aligned by construction — and then we assert it anyway. Same grid, same extent, zero corner offset. The problem statement asks the controller to *check* compatibility, so we actually check."

**→ Map → Optical → SAR → Fusion overlay.**

> "Teal is where both sensors agree. Amber is optical only. Magenta is SAR only. And this number" — cloud-recovered — "is water the radar found that cloud was hiding from the optical sensor. That's the operational value of the pair, in square kilometres."

---

## 6 · The agentic controller (60 s)

**→ Trace tab.** Expand `tool_selector`.

> "Ten specialists in a closed registry. For this task it selected six and rejected the rest — and it records *why* each one was rejected. `change_analyzer` needs a bi-temporal pair; this is cross-modal, so it's out.
>
> And parameters are enforced. A tool can only be called with parameters it declared. Out-of-range values are clamped and logged. There's no path to reach a tool with something it didn't advertise."

Expand any measurement tool → full parameter JSON.

> "That's the auditable execution summary the problem statement asks for. It's a deliverable, not a debug log."

**Click Report.**

> "One click exports the whole evidence record — plan, trace, every fact, provenance, grounding verdict."

---

## 7 · Close (30 s)

> "Real ISRO-relevant data, no credentials, nothing to expire on stage. A classifier we adapted ourselves on 27,000 labelled Sentinel-2 patches — 85.9% on a held-out split, and the system knows when that model is out of its depth and says so instead of guessing.
>
> Every mandatory capability in SIH26167: single-image VQA, captioning **and** grounding, bi-temporal change, change VQA, cross-modal optical–SAR, remote-sensing adaptation, agentic orchestration.
>
> And one number you can't get from a chatbot: zero fabricated statistics, enforced by construction."

---

## Anticipated questions

**"Is this really live data or canned?"**
Grounding → Provenance → click the request URL. Or change the place name to somewhere not in the demo list and run it live.

**"What if the LLM hallucinates?"**
It structurally can't reach a number. Show the Grounding tab — claims checked vs. traced. Set `SATQUERY_STRICT_GROUNDING` and explain that one bad number discards the entire narration.

**"Do you need an API key?"**
No. The whole demo you just watched ran with no key at all — rule-based parser, deterministic narrator. A key makes the prose nicer; it changes nothing about correctness.

**"How accurate is the land cover?"**
It's index-derived, not a certified product, and we say so. What we *can* defend is the method: every threshold used is reported, and the pixel counts are published so any number can be recomputed. Sanity checks: Sahara 98% bare soil, Amazon 45% dense vegetation, Chilika 52% water, Aral Sea only 13% water — which is correct, it has largely dried up.

**"Why not a fine-tuned VLM like GeoChat?"**
It needs a GPU and hours of training, and we couldn't have honestly evaluated it in the time. We chose a model we could train, measure and defend — and, crucially, one whose limits we could detect at runtime. That's in LIMITATIONS.md, section 12.

**"Delhi shows as bare soil — isn't that wrong?"**
It's a deliberate under-claim. NDBI can't separate urban fabric from salt crust or dry sand at 250 m; we tested it and a naive threshold reported the Rann of Kutch salt desert as 32% built-up. So we require the histogram to be genuinely bimodal before splitting, and refuse otherwise — with a warning saying SAR is the right instrument. Ask a cross-modal question and you get built-up properly.

**"What breaks if the internet dies?"**
Set `SATQUERY_OFFLINE=true`. Cached queries work identically and are badged *Cached satellite*. Uncached ones return `no_data` — the system never substitutes simulated data for real.

---

## Backup order if you're short on time

Cut sections 6 and 4 first. **Never cut sections 2 and 3** — the grounding proof and the refusals are the differentiator.
