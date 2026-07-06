"""Brand-library grounding layer.

Picks the relevant slice of the brand library (fabrics, trims, construction
standards, similar past styles, factory routing) for a given style and turns
it into a structured context blob the GPT prompt can consume — and a
display-ready grounding report the UI can render.

In production this would be backed by a vector store + nightly PLM sync; for
the demo it reads `mock_data.py`. The contract (`build_grounding`,
`grounding_for_prompt`) does not change between the two.
"""

from __future__ import annotations

from typing import Any

from mock_data import (
    MOCK_BRAND_CONSTRUCTION_STANDARDS,
    MOCK_BRAND_FABRICS,
    MOCK_BRAND_HISTORICAL_STYLES,
    MOCK_BRAND_NAME,
    MOCK_BRAND_TRIMS,
    MOCK_FACTORY_PROFILES,
)


# ---------------------------------------------------------------------------
# Garment-type taxonomy
# ---------------------------------------------------------------------------

_GARMENT_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Tee", ("tee", "t-shirt", "tshirt", "polo", "henley")),
    ("Hoodie", ("hood", "sweatshirt", "crewneck sweat", "sweat top")),
    ("Denim jacket", ("denim jacket", "trucker", "jean jacket")),
    ("Outerwear", ("coat", "parka", "anorak", "puffer", "outerwear")),
    ("Bottoms", ("pant", "jean", "trouser", "short", "skirt")),
    ("Shirt", ("shirt", "button-down", "button down", "button-up")),
]


def _normalize_garment_type(garment_type: str) -> str:
    g = (garment_type or "").lower()
    for canonical, keywords in _GARMENT_KEYWORDS:
        if any(k in g for k in keywords):
            return canonical
    return "Other"


# ---------------------------------------------------------------------------
# Matchers
# ---------------------------------------------------------------------------


def _match_fabrics(garment_type: str, fabric_hint: str) -> list[dict[str, Any]]:
    """Return fabrics relevant to this garment type, sorted by hint match."""
    canonical = _normalize_garment_type(garment_type).lower()
    hint = (fabric_hint or "").lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    for fab in MOCK_BRAND_FABRICS:
        score = 0
        garment_types = fab.get("garment_types", "").lower()
        if canonical in garment_types or any(g in garment_types for g in canonical.split()):
            score += 2
        if hint:
            for token in hint.split():
                if token and len(token) > 2 and token in fab.get("name", "").lower():
                    score += 3
                if token and token in fab.get("composition", "").lower():
                    score += 1
                if token and token in fab.get("weight", "").lower():
                    score += 2
        if score > 0:
            scored.append((score, fab))
    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored[:5]]


def _match_construction(garment_type: str) -> list[dict[str, Any]]:
    canonical = _normalize_garment_type(garment_type).lower()
    out: list[dict[str, Any]] = []
    for cstd in MOCK_BRAND_CONSTRUCTION_STANDARDS:
        gt = cstd.get("garment_type", "").lower()
        if canonical in gt or gt.startswith(canonical):
            out.append(cstd)
    return out


def _match_similar_styles(garment_type: str) -> list[dict[str, Any]]:
    canonical = _normalize_garment_type(garment_type).lower()
    out: list[dict[str, Any]] = []
    for style in MOCK_BRAND_HISTORICAL_STYLES:
        if canonical in style.get("garment_type", "").lower():
            out.append(style)
    return out[:5]


def _match_factory(garment_type: str, fabric_codes: list[str]) -> dict[str, Any] | None:
    """Pick a factory whose preferred_fabrics overlap the matched fabrics."""
    for factory in MOCK_FACTORY_PROFILES:
        prefs = factory.get("preferred_fabrics", "")
        if any(code in prefs for code in fabric_codes if code):
            return factory
    canonical = _normalize_garment_type(garment_type).lower()
    for factory in MOCK_FACTORY_PROFILES:
        if any(token in factory.get("specialty", "").lower() for token in canonical.split()):
            return factory
    return None


def _relevant_trims(garment_type: str) -> list[dict[str, Any]]:
    """Always include label/care label/hangtag; conditionally include zips/buttons/drawcord."""
    canonical = _normalize_garment_type(garment_type)
    base_types = {"Main label (woven)", "Care label", "Hangtag set"}
    extras: set[str] = set()
    if canonical == "Hoodie":
        extras.update({"Drawcord"})
    if canonical in {"Denim jacket", "Shirt", "Outerwear"}:
        extras.update({"Button (4-hole)"})
    if canonical in {"Outerwear", "Hoodie"}:
        extras.update({"Zipper"})
    wanted = base_types | extras
    return [t for t in MOCK_BRAND_TRIMS if t.get("type") in wanted]


def _fit_history_signal(similar: list[dict[str, Any]]) -> str:
    if not similar:
        return "No comparable history. Add to assumptions and review during Fit 1."
    snippets = [f"{s['style_no']}: {s['fit_history']}" for s in similar[:3]]
    return " | ".join(snippets)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_grounding(garment_type: str, fabric_hint: str = "") -> dict[str, Any]:
    """Return the full grounding bundle for a style.

    The bundle is consumed both by the GPT prompt builder and by the UI
    grounding card, so both stay in sync.
    """
    fabrics = _match_fabrics(garment_type, fabric_hint)
    fabric_codes = [f["code"] for f in fabrics]
    construction = _match_construction(garment_type)
    similar = _match_similar_styles(garment_type)
    trims = _relevant_trims(garment_type)
    factory = _match_factory(garment_type, fabric_codes)

    return {
        "brand_name": MOCK_BRAND_NAME,
        "canonical_garment_type": _normalize_garment_type(garment_type),
        "matched_fabrics": fabrics,
        "matched_trims": trims,
        "applied_construction_standards": construction,
        "similar_styles": similar,
        "factory_routing": factory,
        "fit_history_signal": _fit_history_signal(similar),
    }


def grounding_for_prompt(grounding: dict[str, Any]) -> str:
    """Render the grounding bundle as a compact prompt-ready text block."""
    lines: list[str] = []
    lines.append(f"BRAND LIBRARY CONTEXT — {grounding['brand_name']}")
    lines.append(f"Canonical garment type: {grounding['canonical_garment_type']}")

    lines.append("")
    lines.append("Available fabrics (pick the closest by code; never invent a code):")
    for f in grounding["matched_fabrics"] or []:
        lines.append(
            f"  - {f['code']} | {f['name']} | {f['weight']} | {f['composition']} "
            f"| mill: {f['mill']} | hand: {f['hand']}"
        )
    if not grounding["matched_fabrics"]:
        lines.append("  (no fabric in library matched — flag in missing_information)")

    lines.append("")
    lines.append("Available trims (use these for the BOM; never invent a part number):")
    for t in grounding["matched_trims"] or []:
        lines.append(
            f"  - {t['code']} | {t['type']} | {t['vendor']} {t['part_no']} | {t['spec']}"
        )

    lines.append("")
    lines.append("House construction standards (apply these unless the sketch contradicts them):")
    for c in grounding["applied_construction_standards"] or []:
        lines.append(
            f"  - {c['zone']}: {c['stitch']} / {c['seam']} / SPI {c['spi']} — {c['notes']}"
        )
    if not grounding["applied_construction_standards"]:
        lines.append("  (no house standards on file for this garment type)")

    lines.append("")
    lines.append("Similar past styles (inherit fit-history signals from these):")
    for s in grounding["similar_styles"] or []:
        lines.append(
            f"  - {s['style_no']} {s['name']} ({s['rating']}) — fit history: {s['fit_history']}"
        )

    factory = grounding.get("factory_routing")
    if factory:
        lines.append("")
        lines.append(
            f"Recommended factory: {factory['factory']} ({factory['country']}) — "
            f"{factory['specialty']}, MOQ {factory['moq_pcs']}, lead {factory['lead_time_days']}d. "
            f"House quirks: {factory['house_quirks']}"
        )

    lines.append("")
    lines.append("Grounding rules:")
    lines.append(
        "  - When you reference a fabric in the BOM or material fields, use the exact code "
        "above and label the source as 'matched_from_brand_library'."
    )
    lines.append(
        "  - When you reference a trim in the BOM, use the exact code and label the source "
        "as 'matched_from_brand_library'."
    )
    lines.append(
        "  - When you write a construction note that comes from the standards above, label "
        "the source as 'matched_from_brand_library' and reference the zone."
    )
    lines.append(
        "  - If nothing in the library matches, fall back to "
        "'inferred_from_standard_practice' or 'placeholder_for_review' as you would normally."
    )
    return "\n".join(lines)


def grounding_report(grounding: dict[str, Any]) -> dict[str, Any]:
    """Return a display-ready report for the UI grounding card.

    Uses the same bundle that the prompt sees, so the card can't drift from
    what the model was actually given.
    """
    fabrics = grounding.get("matched_fabrics") or []
    similar = grounding.get("similar_styles") or []
    construction = grounding.get("applied_construction_standards") or []
    factory = grounding.get("factory_routing")

    matched_fabric = (
        f"{fabrics[0]['code']} — {fabrics[0]['name']} ({fabrics[0]['mill']})"
        if fabrics
        else "(no exact match in brand library — flagging for sourcing review)"
    )
    similar_styles = (
        [f"{s['style_no']} {s['name']} ({s['rating']})" for s in similar[:3]]
        or ["(no close matches found)"]
    )
    applied = (
        [f"{c['zone']}: {c['stitch']} / {c['seam']} / SPI {c['spi']}" for c in construction]
        or ["Generic industry construction applied — review required."]
    )
    factory_routing = (
        f"{factory['factory']} ({factory['country']}) — {factory['specialty']}, "
        f"{factory['lead_time_days']}d lead"
        if factory
        else "(no factory pre-routed — designer to assign)"
    )

    return {
        "matched_fabric": matched_fabric,
        "similar_styles": similar_styles,
        "applied_construction": applied,
        "factory_routing": factory_routing,
        "fit_history_signal": grounding["fit_history_signal"],
    }
