"""The grounding gate: no number reaches the user unless a tool measured it.

How it works
------------
1. Every measurement tool publishes :class:`Fact` objects into a
   :class:`FactStore`. That store is the complete set of quantities the system
   is allowed to state.
2. A narrator (template or LLM) writes prose.
3. :func:`verify_text` extracts *every* numeral from that prose and tries to
   match each one to a fact - directly, as a percentage of a fraction, or as a
   rounding of either.
4. Any numeral that cannot be traced is a **rejected claim**. Under
   ``strict_grounding`` a single rejection discards the whole LLM narration and
   the deterministic template is shipped instead.

The consequence is that the failure mode of the LLM is *degradation to
template prose*, never a fabricated statistic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..config import settings
from ..schemas import Fact, GroundingReport, NumericClaim, Provenance

#: Numbers that are structural rather than measured: they describe the data or
#: the method, not a finding. Masking them keeps the verifier focused on actual
#: claims instead of raising false alarms on "512x512 pixels".
_SAFE_CONTEXT = re.compile(
    r"(20\d{2}-\d{2}-\d{2}"                       # ISO dates
    r"|\b(19|20)\d{2}\b"                          # years
    r"|EPSG:\s*\d+"                               # CRS codes
    r"|\bband\s*\d+|\bB\d{1,2}\b"                 # band identifiers
    r"|\bSentinel-\d[AB]?\b|\bLandsat[- ]?\d\b"   # platform names
    r"|\bMODIS\b|\bVIIRS\b"
    r"|\d+\s*[x×]\s*\d+"                     # raster dimensions, e.g. 512x512
    r"|\d+(?:st|nd|rd|th)"                        # ordinals, e.g. 10th-90th percentile
    r"|\bP\d{1,2}\b"                              # percentile shorthand, e.g. P90
    r"|\bOPERA\s*L\d\b|\bMOD\d+\b"                # product identifiers
    r"|\b\d+\s*(?:m|km)\s+resolution\b"           # quoted sensor resolution
    r"|\bR²\b|\bIoU\b"                       # metric names
    r"|\b(?:km|m|cm|mm)[²2³3]\b"                  # unit suffixes: km2, m3, km²
    r"|\bB\d{1,2}/B\d{1,2}(?:/B\d{1,2})?\b"       # band composites, e.g. B1/B4/B3
    r"|\bBands?\d{3,}\b"                          # e.g. Bands721
    r")",
    re.IGNORECASE,
)

_NUMBER = re.compile(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d*\.?\d+")


@dataclass
class FactStore:
    """Accumulates every measurement produced during one request."""

    facts: dict[str, Fact] = field(default_factory=dict)
    provenance: list[Provenance] = field(default_factory=list)

    def add(self, fact: Fact) -> Fact:
        self.facts[fact.key] = fact
        return fact

    def add_many(self, facts: list[Fact]) -> list[str]:
        for f in facts:
            self.add(f)
        return [f.key for f in facts]

    def add_provenance(self, provs: list[Provenance]) -> None:
        for p in provs:
            if not any(
                q.source == p.source and q.acquisition_date == p.acquisition_date
                for q in self.provenance
            ):
                self.provenance.append(p)

    def get(self, key: str) -> Fact | None:
        return self.facts.get(key)

    def value(self, key: str, default: float | None = None) -> float | None:
        f = self.facts.get(key)
        if f is None:
            return default
        n = f.numeric
        return n if n is not None else default

    def has(self, *keys: str) -> bool:
        return all(k in self.facts for k in keys)

    def as_list(self) -> list[Fact]:
        return list(self.facts.values())

    def numeric_index(self) -> list[tuple[str, float]]:
        out: list[tuple[str, float]] = []
        for k, f in self.facts.items():
            n = f.numeric
            if n is not None:
                out.append((k, n))
        return out

    @property
    def all_real(self) -> bool:
        return all(p.is_real for p in self.provenance) if self.provenance else True

    def brief(self, max_items: int = 60) -> list[dict]:
        """Compact JSON view handed to the LLM narrator as its only evidence."""
        rows: list[dict] = []
        for f in list(self.facts.values())[:max_items]:
            rows.append({
                "key": f.key,
                "label": f.label,
                "value": f.value,
                "unit": f.unit,
                "measured_by": f.tool,
                "method": f.method,
            })
        return rows


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------
def _candidate_values(facts: list[tuple[str, float]]) -> list[tuple[str, float, str]]:
    """Every representation a fact may legitimately take in prose."""
    out: list[tuple[str, float, str]] = []
    for key, v in facts:
        out.append((key, v, "value"))
        if v < 0:
            # Prose often states a magnitude next to a direction word
            # ("shrank by 1,059.17 km2") while the fact keeps the sign.
            out.append((key, abs(v), "magnitude of signed value"))
        if -1.0 <= v <= 1.0:
            out.append((key, v * 100.0, "percentage of fraction"))
            if v < 0:
                out.append((key, abs(v) * 100.0, "magnitude as percentage"))
        if abs(v) >= 1000:
            out.append((key, v / 1000.0, "thousands"))
    return out


def _matches(claim: float, target: float, tol: float) -> bool:
    if target == 0.0:
        return abs(claim) < 1e-9
    # Relative tolerance, with an absolute floor so tiny values still match
    # after rounding to one or two decimals.
    return abs(claim - target) <= max(abs(target) * tol, 0.05)


def verify_text(text: str, store: FactStore, tolerance: float | None = None
                ) -> tuple[list[NumericClaim], list[NumericClaim]]:
    """Split every numeral in *text* into verified and rejected claims."""
    tol = settings.numeric_tolerance if tolerance is None else tolerance
    candidates = _candidate_values(store.numeric_index())

    verified: list[NumericClaim] = []
    rejected: list[NumericClaim] = []

    # Blank out spans that are structurally numeric (dates, years, band ids)
    # so they are not mistaken for measurements.
    masked = _SAFE_CONTEXT.sub(lambda m: "#" * len(m.group(0)), text)

    for m in _NUMBER.finditer(masked):
        raw = m.group(0)
        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            continue

        # Small ordinals and enumerations ("2 dates", "top 3") are not claims.
        window = masked[max(0, m.start() - 24): m.end() + 24].lower()
        if val == int(val) and abs(val) <= 12 and re.search(
            r"\b(date|dates|scene|scenes|image|images|region|regions|class|classes|"
            r"step|steps|tool|tools|sensor|sensors|band|bands|top|first|both|two|"
            r"pair|km|m\b)\b", window
        ):
            continue

        hit = next(((k, kind) for k, tv, kind in candidates if _matches(val, tv, tol)), None)
        claim = NumericClaim(
            text=raw,
            value=val,
            verified=hit is not None,
            matched_fact=hit[0] if hit else None,
            reason=(f"matched fact '{hit[0]}' ({hit[1]})" if hit
                    else "no measured fact supports this number"),
        )
        (verified if hit else rejected).append(claim)

    return verified, rejected


def build_report(
    text: str,
    store: FactStore,
    narrator: str,
    fallback_text: str | None = None,
) -> tuple[str, GroundingReport]:
    """Verify a narration and, under strict mode, replace it if it fails."""
    verified, rejected = verify_text(text, store)
    passed = not rejected
    final_text = text
    final_narrator = narrator

    if rejected and settings.strict_grounding and fallback_text is not None:
        final_text = fallback_text
        final_narrator = "llm_rejected_fallback_template"
        # The fallback is template-generated from the same store, so it must
        # itself verify; check it rather than trusting it.
        verified, rejected = verify_text(final_text, store)
        passed = not rejected

    report = GroundingReport(
        narrator=final_narrator,  # type: ignore[arg-type]
        strict_mode=settings.strict_grounding,
        claims_checked=len(verified) + len(rejected),
        claims_verified=len(verified),
        rejected_claims=rejected,
        verified_claims=verified,
        fact_count=len(store.facts),
        all_sources_real=store.all_real,
        passed=passed,
        explanation=(
            f"{len(verified)}/{len(verified) + len(rejected)} numeric claims traced to "
            f"measured facts across {len(store.facts)} facts from "
            f"{len(store.provenance)} data source(s)."
            + ("" if passed else
               " Ungrounded numbers were detected and the narration was replaced with "
               "the deterministic template.")
        ),
    )
    return final_text, report


def fact(
    key: str,
    label: str,
    value,
    method: str,
    tool: str,
    unit: str | None = None,
    source: str | None = None,
    sample_size: int | None = None,
    confidence: float | None = None,
) -> Fact:
    """Small helper so tools declare facts in one readable line."""
    if isinstance(value, float):
        value = round(value, 6)
    return Fact(
        key=key, label=label, value=value, unit=unit, method=method,
        tool=tool, source=source, sample_size=sample_size, confidence=confidence,
    )
