"""Category-standard spec blocks for grounding measurements.

Instead of letting the vision model invent every point of measure from a flat
sketch, each garment category has a standard POM block (industry-typical names,
how-to-measure descriptions, size-M baseline targets, and tolerances). The
block is the baseline; AI output only *adjusts* it, and adjustments that fall
outside a plausibility window are rejected back to the standard value and
flagged for review.

Targets are body-flat garment measurements in inches at the size-M baseline and
are intentionally middle-of-the-road: a technical designer overrides them per
brand block. Sample sizes other than M are projected with the same default
grade rules used by the grading preview.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from mock_data import DEFAULT_SIZE_RUN, _grade_rule_for_pom

STANDARD_SOURCE = "inferred_from_standard_practice"

# Reject an AI target when it deviates from the standard block by more than
# this fraction — a 2D sketch cannot justify e.g. a 40% smaller chest.
PLAUSIBILITY_WINDOW = 0.35


def _m(pom: str, description: str, target: float, tol: float = 0.25, notes: str = "") -> dict[str, Any]:
    return {
        "pom": pom,
        "description": description,
        "target": f"{target:g}",
        "tolerance_plus": f"{tol:g}",
        "tolerance_minus": f"{tol:g}",
        "source": STANDARD_SOURCE,
        "notes": notes,
    }


def _c(zone: str, note: str, stitch: str = "", seam: str = "", spi: str = "") -> dict[str, Any]:
    return {
        "zone": zone,
        "note": note,
        "stitch_type": stitch,
        "seam_class": seam,
        "spi": spi,
        "source": STANDARD_SOURCE,
    }


def _b(component: str, material: str, placement: str, notes: str = "") -> dict[str, Any]:
    return {
        "component": component,
        "material": material,
        "placement": placement,
        "notes": notes,
        "source": STANDARD_SOURCE,
    }


_GENERIC_BOM: list[dict[str, Any]] = [
    _b("Self fabric", "Per style spec", "Body", "Confirm content, weight, and mill"),
    _b("Sewing thread", "Poly-core spun, DTM", "All seams", ""),
    _b("Main label", "Woven label", "CB neck / CB waist", "Brand standard"),
    _b("Care + content label", "Printed satin", "Wearer's left side seam", "Per destination-market regulations"),
    _b("Hangtag", "Brand standard", "Attached at label", ""),
]

_GENERIC_CONSTRUCTION: list[dict[str, Any]] = [
    _c("(general)", "All seams secured; no raw edges exposed on finished garment"),
    _c("(general)", "Press garment per category standard before packing"),
]

SPEC_BLOCKS: dict[str, dict[str, Any]] = {
    "tee": {
        "label": "T-shirt / knit top",
        "keywords": ["tee", "t-shirt", "tshirt", "t shirt", "crewneck", "crew neck", "v-neck", "knit top"],
        "measurements": [
            _m("Chest Width", "1\" below armhole, straight across, flat", 21),
            _m("Body Length from HPS", "High point shoulder to bottom hem edge", 28.5, 0.5),
            _m("Shoulder Width", "Seam to seam across back", 18),
            _m("Sleeve Length", "From shoulder seam to sleeve hem edge", 8.5),
            _m("Sleeve Opening", "Sleeve hem edge, flat", 7, 0.125),
            _m("Armhole Depth", "Straight, HPS to 1\" below armhole point", 9.5),
            _m("Neck Width", "Seam to seam, inside collar", 7.25, 0.125),
            _m("Front Neck Drop", "HPS to top of front neck seam", 3.5, 0.125),
            _m("Back Neck Drop", "HPS to top of back neck seam", 1, 0.125),
            _m("Neck Rib Height", "Height of neck trim, finished", 0.75, 0.125),
            _m("Bottom Hem Opening", "Bottom hem edge, flat", 20.5, 0.5),
        ],
        "construction": [
            _c("Neckline", "Neck rib set with 4-thread safety stitch; twin-needle coverstitch topstitch", "406 — Coverstitch", "1.01.01 — Superimposed (plain seam)", "10-12"),
            _c("Shoulder seam", "Shoulder seams overlocked with clear elastic or self-fabric tape stay", "504 — 3-thread overlock", "1.01.01 — Superimposed (plain seam)", "10-12"),
            _c("Sleeve hem", "1\" coverstitch hem", "406 — Coverstitch", "6.02.01 — Edge finish", "10-12"),
            _c("Body hem", "1\" coverstitch hem", "406 — Coverstitch", "6.02.01 — Edge finish", "10-12"),
            _c("Side seam", "4-thread safety stitch", "514 — 4-thread safety stitch", "1.01.01 — Superimposed (plain seam)", "10-12"),
        ],
        "bom": _GENERIC_BOM + [_b("Neck rib", "1x1 rib, self color", "Neckline", "Match body content")],
    },
    "polo": {
        "label": "Polo shirt",
        "keywords": ["polo"],
        "measurements": [
            _m("Chest Width", "1\" below armhole, straight across, flat", 21),
            _m("Body Length from HPS", "High point shoulder to bottom hem edge", 29, 0.5),
            _m("Shoulder Width", "Seam to seam across back", 17.75),
            _m("Sleeve Length", "From shoulder seam to sleeve hem edge", 8.75),
            _m("Sleeve Opening", "Sleeve hem edge, flat", 6.5, 0.125),
            _m("Armhole Depth", "Straight, HPS to 1\" below armhole point", 9.75),
            _m("Collar Height at CB", "Finished collar height at center back", 3, 0.125),
            _m("Placket Length", "From neck seam to bottom of placket", 7, 0.125),
            _m("Placket Width", "Finished placket width", 1.25, 0.125),
        ],
        "construction": _GENERIC_CONSTRUCTION + [
            _c("Placket", "Clean-finished placket, boxed at bottom; buttonholes vertical", "301 — Lockstitch", "1.01.01 — Superimposed (plain seam)", "12-14"),
        ],
        "bom": _GENERIC_BOM + [
            _b("Collar + cuffs", "Flat-knit rib, self color", "Collar, sleeve hems", ""),
            _b("Buttons", "18L 4-hole, DTM", "Placket x3", "Plus 1 spare at care label"),
        ],
    },
    "sweatshirt": {
        "label": "Sweatshirt / hoodie",
        "keywords": ["hoodie", "sweatshirt", "fleece", "pullover", "crewneck fleece", "sweat"],
        "measurements": [
            _m("Chest Width", "1\" below armhole, straight across, flat", 23),
            _m("Body Length from HPS", "High point shoulder to bottom rib edge", 27.5, 0.5),
            _m("Shoulder Width", "Seam to seam across back", 19),
            _m("Sleeve Length", "From shoulder seam to end of cuff", 25.5, 0.5),
            _m("Cuff Opening", "Cuff edge, flat, relaxed", 4, 0.125),
            _m("Cuff Height", "Finished rib cuff height", 2.5, 0.125),
            _m("Bottom Rib Height", "Finished bottom rib height", 2.5, 0.125),
            _m("Armhole Depth", "Straight, HPS to 1\" below armhole point", 10.5),
            _m("Hood Height", "From neck seam at CB to top of hood, flat", 13.5, 0.25, "Hooded styles only — delete for crewnecks"),
            _m("Hood Width", "Across hood at widest point, flat", 11, 0.25, "Hooded styles only — delete for crewnecks"),
        ],
        "construction": [
            _c("Hood", "Double-layer hood, faced with self; eyelets reinforced", "301 — Lockstitch", "1.01.01 — Superimposed (plain seam)", "10-12"),
            _c("Armhole", "Set-in sleeve, 4-thread safety stitch", "514 — 4-thread safety stitch", "1.01.01 — Superimposed (plain seam)", "10-12"),
            _c("Cuff", "Rib cuff attached with overlock, coverstitch topstitch", "406 — Coverstitch", "1.01.01 — Superimposed (plain seam)", "10-12"),
            _c("Body hem", "Rib waistband attached with overlock, coverstitch topstitch", "406 — Coverstitch", "1.01.01 — Superimposed (plain seam)", "10-12"),
        ],
        "bom": _GENERIC_BOM + [
            _b("Rib trim", "2x2 rib, self color", "Cuffs, bottom band", "Match body content"),
            _b("Drawcord", "Flat woven cord, DTM", "Hood", "Hooded styles only"),
            _b("Eyelets", "Metal eyelet, antique finish", "Hood x2", "Hooded styles only"),
        ],
    },
    "woven_shirt": {
        "label": "Woven shirt / blouse",
        "keywords": ["shirt", "button-up", "button up", "button-down", "button down", "oxford", "blouse", "overshirt"],
        "measurements": [
            _m("Chest Width", "1\" below armhole, straight across, flat", 22),
            _m("Body Length from HPS", "High point shoulder to bottom hem edge", 30, 0.5),
            _m("Shoulder Width", "Seam to seam across back", 18.5),
            _m("Sleeve Length from CB", "Center back neck over shoulder to cuff edge", 34.5, 0.5),
            _m("Cuff Opening", "Cuff edge buttoned, flat", 4.5, 0.125),
            _m("Armhole Depth", "Curved, along armhole seam", 10),
            _m("Collar Length", "Buttonhole to button, along band", 16, 0.125),
            _m("Collar Band Height", "Finished band height at CB", 1.25, 0.125),
            _m("Yoke Width", "Across back yoke seam to seam", 18, 0.25),
        ],
        "construction": _GENERIC_CONSTRUCTION + [
            _c("Side seam", "Flat-felled side seams", "401 — 2-thread chainstitch", "2.02.03 — Lapped (flat-felled)", "14-16"),
            _c("Placket", "Front placket topstitched 1/16\"; buttonholes vertical", "301 — Lockstitch", "1.01.01 — Superimposed (plain seam)", "14-16"),
        ],
        "bom": _GENERIC_BOM + [
            _b("Buttons", "18L 4-hole, DTM", "CF placket x7, cuffs x2", "Plus spares at care label"),
            _b("Interlining", "Fusible woven, per weight", "Collar, band, cuffs, placket", ""),
        ],
    },
    "jacket": {
        "label": "Jacket / outerwear",
        "keywords": ["jacket", "coat", "blazer", "outerwear", "parka", "bomber", "windbreaker", "anorak"],
        "measurements": [
            _m("Chest Width", "1\" below armhole, straight across, flat", 23.5),
            _m("Body Length from CB", "Center back neck seam to bottom hem edge", 27, 0.5),
            _m("Shoulder Width", "Seam to seam across back", 19),
            _m("Sleeve Length", "From shoulder seam to cuff edge", 26, 0.5),
            _m("Cuff Opening", "Cuff edge, flat", 5.5, 0.25),
            _m("Armhole Depth", "Curved, along armhole seam", 11),
            _m("Bottom Opening", "Bottom hem edge, flat, relaxed", 22, 0.5),
            _m("Collar Height at CB", "Finished collar height at center back", 3, 0.125),
        ],
        "construction": _GENERIC_CONSTRUCTION + [
            _c("Zipper", "CF zipper set with even 1/4\" topstitch both sides; zipper garage at top", "301 — Lockstitch", "1.01.01 — Superimposed (plain seam)", "10-12"),
            _c("Lining", "Full lining bagged out; 2\" ease pleat at CB", "301 — Lockstitch", "1.01.01 — Superimposed (plain seam)", "10-12"),
        ],
        "bom": _GENERIC_BOM + [
            _b("CF zipper", "#5 metal, auto-lock slider", "Center front", "Confirm finish"),
            _b("Lining", "100% polyester taffeta", "Body + sleeves", ""),
        ],
    },
    "pants": {
        "label": "Pants / trousers",
        "keywords": ["pant", "trouser", "jean", "denim", "chino", "jogger", "slacks"],
        "measurements": [
            _m("Waist Width", "Along top of waistband, flat, relaxed", 16.5),
            _m("Hip Width", "8\" below waistband top, flat", 21.5),
            _m("Front Rise", "Crotch seam to top of waistband at CF", 11, 0.25),
            _m("Back Rise", "Crotch seam to top of waistband at CB", 15, 0.25),
            _m("Thigh Width", "1\" below crotch, flat", 12.5),
            _m("Knee Width", "13\" below crotch, flat", 8.5, 0.25),
            _m("Leg Opening", "Hem edge, flat", 7, 0.125),
            _m("Inseam", "Crotch seam to hem edge along inseam", 32, 0.5),
        ],
        "construction": _GENERIC_CONSTRUCTION + [
            _c("Waistband", "Clean-finished waistband; bar tacks at belt loops", "301 — Lockstitch", "1.01.01 — Superimposed (plain seam)", "10-12"),
            _c("Side seam", "Busted and pressed open (twill) / felled (denim)", "301 — Lockstitch", "1.01.01 — Superimposed (plain seam)", "10-12"),
        ],
        "bom": _GENERIC_BOM + [
            _b("Zipper", "#3 YKK or equivalent, DTM tape", "Fly", ""),
            _b("Main button", "17mm shank or 4-hole per style", "CF waistband", ""),
            _b("Pocketing", "65/35 poly-cotton twill", "Front + back pockets", ""),
        ],
    },
    "shorts": {
        "label": "Shorts",
        "keywords": ["short"],
        "measurements": [
            _m("Waist Width", "Along top of waistband, flat, relaxed", 16.5),
            _m("Hip Width", "8\" below waistband top, flat", 21.5),
            _m("Front Rise", "Crotch seam to top of waistband at CF", 11.5, 0.25),
            _m("Back Rise", "Crotch seam to top of waistband at CB", 15, 0.25),
            _m("Thigh Width", "1\" below crotch, flat", 12.5),
            _m("Leg Opening", "Hem edge, flat", 11, 0.25),
            _m("Inseam", "Crotch seam to hem edge along inseam", 7, 0.25),
        ],
        "construction": _GENERIC_CONSTRUCTION,
        "bom": _GENERIC_BOM,
    },
    "skirt": {
        "label": "Skirt",
        "keywords": ["skirt"],
        "measurements": [
            _m("Waist Width", "Along top of waistband, flat, relaxed", 15),
            _m("Hip Width", "8\" below waistband top, flat", 20),
            _m("Front Length", "Top of waistband to hem at CF", 22, 0.5),
            _m("Hem Sweep", "Along bottom hem edge, flat", 25, 0.5),
        ],
        "construction": _GENERIC_CONSTRUCTION,
        "bom": _GENERIC_BOM + [_b("Zipper", "Invisible zipper, DTM", "CB or side seam", "")],
    },
    "dress": {
        "label": "Dress",
        "keywords": ["dress", "gown", "jumper dress"],
        "measurements": [
            _m("Chest Width", "1\" below armhole, straight across, flat", 19.5),
            _m("Waist Width", "At natural waist position, flat", 17),
            _m("Hip Width", "8\" below natural waist, flat", 21.5),
            _m("Body Length from HPS", "High point shoulder to hem edge", 36, 0.5),
            _m("Shoulder Width", "Seam to seam across back", 15.5),
            _m("Armhole Depth", "Straight, HPS to 1\" below armhole point", 9),
            _m("Hem Sweep", "Along bottom hem edge, flat", 27, 0.5),
        ],
        "construction": _GENERIC_CONSTRUCTION + [
            _c("Zipper", "Invisible zipper at CB, ending 1/2\" above hem facing", "301 — Lockstitch", "1.01.01 — Superimposed (plain seam)", "12-14"),
        ],
        "bom": _GENERIC_BOM + [_b("Zipper", "Invisible zipper, DTM", "Center back", "")],
    },
    "tank": {
        "label": "Tank top",
        "keywords": ["tank", "camisole", "singlet", "cami"],
        "measurements": [
            _m("Chest Width", "1\" below armhole, straight across, flat", 20),
            _m("Body Length from HPS", "High point shoulder to bottom hem edge", 27, 0.5),
            _m("Strap Width", "Finished strap width at shoulder", 1.5, 0.125),
            _m("Armhole Drop", "Straight, HPS to bottom of armhole", 10),
            _m("Front Neck Drop", "HPS to top of front neck edge", 4.5, 0.125),
            _m("Bottom Hem Opening", "Bottom hem edge, flat", 20, 0.5),
        ],
        "construction": _GENERIC_CONSTRUCTION + [
            _c("Neckline", "Self binding on neck and armholes, coverstitched", "406 — Coverstitch", "4.03.03 — Bound (binding)", "10-12"),
        ],
        "bom": _GENERIC_BOM,
    },
    "default": {
        "label": "Generic garment",
        "keywords": [],
        "measurements": [
            _m("Chest Width", "1\" below armhole, straight across, flat", 21),
            _m("Body Length from HPS", "High point shoulder to bottom hem edge", 28, 0.5),
            _m("Shoulder Width", "Seam to seam across back", 18),
            _m("Armhole Depth", "Straight, HPS to 1\" below armhole point", 9.5),
            _m("Bottom Opening", "Bottom hem edge, flat", 21, 0.5),
        ],
        "construction": _GENERIC_CONSTRUCTION,
        "bom": _GENERIC_BOM,
    },
}


# ---------------------------------------------------------------------------
# Lookup + size projection
# ---------------------------------------------------------------------------


def match_category(garment_type: str) -> str:
    """Map a freeform garment type to a spec block key. Falls back to 'default'."""
    text = (garment_type or "").lower()
    # Longest keyword wins so "sweatshirt" beats "shirt", "t shirt" beats "shirt".
    best_key, best_len = "default", 0
    for key, block in SPEC_BLOCKS.items():
        for kw in block["keywords"]:
            if kw in text and len(kw) > best_len:
                best_key, best_len = key, len(kw)
    return best_key


def _project_to_size(measurements: list[dict[str, Any]], sample_size: str) -> list[dict[str, Any]]:
    """Shift size-M baseline targets to the requested sample size via grade rules."""
    sizes = DEFAULT_SIZE_RUN
    sample = (sample_size or "M").strip().upper()
    if sample not in sizes or sample == "M":
        return measurements
    steps = sizes.index(sample) - sizes.index("M")
    out = []
    for m in measurements:
        m = dict(m)
        try:
            base = float(m["target"])
        except (TypeError, ValueError):
            out.append(m)
            continue
        m["target"] = f"{base + steps * _grade_rule_for_pom(m['pom']):g}"
        out.append(m)
    return out


def get_spec_block(garment_type: str, sample_size: str = "M") -> dict[str, Any]:
    """Return a deep copy of the matched block with targets projected to sample size."""
    key = match_category(garment_type)
    block = copy.deepcopy(SPEC_BLOCKS[key])
    block["key"] = key
    block["measurements"] = _project_to_size(block["measurements"], sample_size)
    size_label = (sample_size or "M").strip().upper() or "M"
    for m in block["measurements"]:
        base_note = f"Category-standard block ({block['label']}), size {size_label} baseline"
        m["notes"] = f"{m['notes']} — {base_note}" if m["notes"] else base_note
    return block


# ---------------------------------------------------------------------------
# Grounding: merge AI-suggested measurements onto the standard block
# ---------------------------------------------------------------------------


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (name or "").lower()).strip()


def _find_match(pom: str, candidates: list[dict[str, Any]]) -> int | None:
    q = _norm(pom)
    if not q:
        return None
    for i, c in enumerate(candidates):
        if _norm(c.get("pom", "")) == q:
            return i
    for i, c in enumerate(candidates):
        name = _norm(c.get("pom", ""))
        if q in name or name in q:
            return i
    return None


def ground_measurements(
    ai_measurements: list[dict[str, Any]],
    garment_type: str,
    sample_size: str = "M",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Anchor AI-suggested measurements on the category-standard spec block.

    Returns (grounded_measurements, grounding_notes).

    Rules:
    - Every block POM is always present (never silently dropped by the model).
    - An AI target replaces the block target only when it is numeric and within
      PLAUSIBILITY_WINDOW of the standard value; otherwise the standard value is
      kept and the AI value is flagged for review.
    - AI POMs not in the block are appended; unless the model derived them from
      the input, they are downgraded to placeholder_for_review.
    """
    block = get_spec_block(garment_type, sample_size)
    ai_rows = [dict(m) for m in (ai_measurements or [])]
    notes: list[str] = []
    grounded: list[dict[str, Any]] = []
    used_ai: set[int] = set()

    for std in block["measurements"]:
        row = dict(std)
        idx = _find_match(std["pom"], ai_rows)
        if idx is not None:
            used_ai.add(idx)
            ai = ai_rows[idx]
            try:
                ai_target = float(str(ai.get("target", "")).strip())
                std_target = float(std["target"])
            except (TypeError, ValueError):
                ai_target = std_target = None  # type: ignore[assignment]
            if ai_target is not None and std_target:
                deviation = abs(ai_target - std_target) / std_target
                if deviation <= PLAUSIBILITY_WINDOW:
                    row["target"] = f"{ai_target:g}"
                    row["source"] = ai.get("source") or std["source"]
                    if ai.get("notes"):
                        row["notes"] = ai["notes"]
                    row["tolerance_plus"] = ai.get("tolerance_plus") or std["tolerance_plus"]
                    row["tolerance_minus"] = ai.get("tolerance_minus") or std["tolerance_minus"]
                else:
                    row["source"] = "placeholder_for_review"
                    row["notes"] = (
                        f"AI proposed {ai_target:g}\" — outside ±{PLAUSIBILITY_WINDOW:.0%} of the "
                        f"category standard ({std['target']}\"). Standard kept; review required."
                    )
                    notes.append(
                        f"{std['pom']}: AI value {ai_target:g}\" rejected as implausible vs "
                        f"standard {std['target']}\" — flagged for review."
                    )
        grounded.append(row)

    for i, ai in enumerate(ai_rows):
        if i in used_ai or not (ai.get("pom") or "").strip():
            continue
        extra = {
            "pom": ai.get("pom", ""),
            "description": ai.get("description", ""),
            "target": ai.get("target", ""),
            "tolerance_plus": ai.get("tolerance_plus", "0.25"),
            "tolerance_minus": ai.get("tolerance_minus", "0.25"),
            "source": ai.get("source", ""),
            "notes": ai.get("notes", ""),
        }
        if extra["source"] != "derived_from_input":
            extra["source"] = "placeholder_for_review"
            suffix = "Not in category-standard block — confirm before sampling."
            extra["notes"] = f"{extra['notes']} {suffix}".strip()
        grounded.append(extra)

    return grounded, notes


# ---------------------------------------------------------------------------
# Offline draft (demo mode / no API key)
# ---------------------------------------------------------------------------


def build_offline_draft(metadata: dict[str, Any]) -> dict[str, Any]:
    """Build an analysis-shaped draft purely from the category-standard block.

    Used for the "Load Demo Tech Pack" path and as the fallback when no
    OPENAI_API_KEY is configured. Same shape as gpt_service.analyze_sketch().
    """
    garment_type = metadata.get("garment_type") or ""
    sample_size = metadata.get("sample_size") or "M"
    block = get_spec_block(garment_type, sample_size)

    label = block["label"]
    fabric = metadata.get("fabric") or "TBD fabric"
    summary = (
        f"Draft {label.lower()} spec generated offline from the category-standard block "
        f"in {fabric}, sample size {(sample_size or 'M').upper()}. No sketch analysis was "
        "performed — every value is a standard-practice baseline for a technical designer to review."
    )

    return {
        "garment_summary": summary,
        "detected_features": [],
        "suggested_measurements": block["measurements"],
        "construction_notes": block["construction"],
        "bom_items": block["bom"],
        "assumptions": [
            f"Measurements are the {label} category-standard block projected to the sample size; "
            "no AI sketch analysis was used.",
            "Tolerances are category defaults — confirm against the brand tolerance standard.",
        ],
        "missing_information": [
            "Sketch not analyzed (offline draft) — visual design details are not reflected.",
            "Fabric weight/content, trims, and colorways must be confirmed by the designer.",
        ],
    }
