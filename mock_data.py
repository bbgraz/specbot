"""Realistic but static demo data for SpecBot preview tabs.

Everything here is intentionally non-functional. It populates the preview
tabs in the UI so a tech-designer audience sees the surface area we're
building toward. Each tab is clearly labeled "Preview" in the UI.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Sample stages — used as a label across the app (functional, not preview)
# ---------------------------------------------------------------------------

SAMPLE_STAGES: list[str] = [
    "Proto",
    "Fit 1",
    "Fit 2",
    "Fit 3",
    "SMS",       # Sales/Marketing Sample
    "TOP",       # Top of Production
    "PP",        # Pre-Production
    "Bulk",
]

DEFAULT_STAGE = "Proto"


# ---------------------------------------------------------------------------
# Construction reference (used to populate dropdowns; functional)
# ---------------------------------------------------------------------------

ISO_4915_STITCH_TYPES: list[str] = [
    "301 — Lockstitch",
    "401 — 2-thread chainstitch",
    "406 — Coverstitch",
    "504 — 3-thread overlock",
    "514 — 4-thread safety stitch",
    "605 — Flatlock",
    "103 — Blindstitch",
]

ISO_4916_SEAM_CLASSES: list[str] = [
    "1.01.01 — Superimposed (plain seam)",
    "1.06.02 — Superimposed (French seam)",
    "2.02.03 — Lapped (flat-felled)",
    "4.03.03 — Bound (binding)",
    "5.05.01 — Decorative ornamental",
    "6.02.01 — Edge finish",
]

CONSTRUCTION_ZONES: list[str] = [
    "(general)",
    "Neckline",
    "Shoulder seam",
    "Armhole",
    "Sleeve cap",
    "Sleeve hem",
    "Side seam",
    "Body hem",
    "Pocket",
    "Placket",
    "Waistband",
    "Cuff",
    "Hood",
    "Zipper",
    "Lining",
]


# ---------------------------------------------------------------------------
# Grading — preview. Returns a graded size run from a sample-size POM table.
# ---------------------------------------------------------------------------

# Default grade rules in inches between adjacent sizes.  Realistic-ish for
# tops; tech designer would override these per brand.
DEFAULT_GRADE_RULES: dict[str, float] = {
    "chest": 1.0,
    "waist": 1.0,
    "hip": 1.0,
    "body length": 0.5,
    "back length": 0.5,
    "shoulder": 0.25,
    "sleeve length": 0.25,
    "sleeve opening": 0.125,
    "neck width": 0.25,
    "neck drop": 0.125,
    "armhole": 0.25,
    "cuff opening": 0.125,
}

DEFAULT_SIZE_RUN: list[str] = ["XS", "S", "M", "L", "XL", "XXL"]


def _grade_rule_for_pom(
    pom_name: str,
    rule_overrides: dict[str, float] | None = None,
) -> float:
    """Resolve the grade rule for a POM.

    `rule_overrides` is an optional dict keyed on either the exact POM name
    (preferred) or a keyword substring (fallback to `DEFAULT_GRADE_RULES`).
    """
    name = (pom_name or "").lower().strip()
    if rule_overrides:
        if name in {k.lower() for k in rule_overrides}:
            for k, v in rule_overrides.items():
                if k.lower() == name:
                    return float(v)
        for keyword, rule in rule_overrides.items():
            if keyword and keyword.lower() in name:
                return float(rule)
    for keyword, rule in DEFAULT_GRADE_RULES.items():
        if keyword in name:
            return rule
    return 0.5  # fallback


def build_graded_table(
    measurements: list[dict[str, Any]],
    sample_size: str = "M",
    size_run: list[str] | None = None,
    rule_overrides: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Project the sample-size POMs across a full size run using grade rules.

    `rule_overrides` lets the brand replace the generic defaults with house rules,
    keyed by exact POM name (preferred) or by keyword.
    """
    sizes = size_run or DEFAULT_SIZE_RUN
    sample = (sample_size or "M").upper()
    if sample not in sizes:
        sample = "M" if "M" in sizes else sizes[len(sizes) // 2]
    sample_idx = sizes.index(sample)

    rows: list[dict[str, Any]] = []
    for m in measurements:
        try:
            base = float(m.get("target", "") or 0)
        except (TypeError, ValueError):
            base = 0.0
        rule = _grade_rule_for_pom(m.get("pom", ""), rule_overrides)
        row = {"POM": m.get("pom", ""), "Grade rule (in)": f"±{rule:g}"}
        for i, size in enumerate(sizes):
            offset = (i - sample_idx) * rule
            value = base + offset
            row[size] = f"{value:g}"
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Costing — preview. Static FOB rollup.
# ---------------------------------------------------------------------------

MOCK_COSTING_LINES: list[dict[str, Any]] = [
    {"category": "Material", "item": "Self fabric", "consumption": "1.65 yd", "rate": "$3.40 / yd", "cost_usd": 5.61},
    {"category": "Material", "item": "Rib trim", "consumption": "0.10 yd", "rate": "$2.10 / yd", "cost_usd": 0.21},
    {"category": "Trim", "item": "Main label (woven)", "consumption": "1 ea", "rate": "$0.05", "cost_usd": 0.05},
    {"category": "Trim", "item": "Care label", "consumption": "1 ea", "rate": "$0.02", "cost_usd": 0.02},
    {"category": "Trim", "item": "Hangtag + string", "consumption": "1 set", "rate": "$0.18", "cost_usd": 0.18},
    {"category": "Trim", "item": "Polybag + sticker", "consumption": "1 set", "rate": "$0.09", "cost_usd": 0.09},
    {"category": "Labor", "item": "CMT (cut/make/trim)", "consumption": "—", "rate": "—", "cost_usd": 2.85},
    {"category": "Labor", "item": "Wash & finish", "consumption": "—", "rate": "—", "cost_usd": 0.45},
    {"category": "Overhead", "item": "Factory overhead + margin", "consumption": "—", "rate": "—", "cost_usd": 1.10},
    {"category": "Logistics", "item": "Inland + handling", "consumption": "—", "rate": "—", "cost_usd": 0.32},
]

MOCK_COSTING_TOTAL_FOB: float = round(sum(line["cost_usd"] for line in MOCK_COSTING_LINES), 2)
MOCK_COSTING_TARGET_FOB: float = 9.50


# ---------------------------------------------------------------------------
# Colorways — preview. Pantone references + mock approval status.
# ---------------------------------------------------------------------------

MOCK_COLORWAYS: list[dict[str, Any]] = [
    {
        "colorway_code": "BLK-001",
        "color_name": "Caviar Black",
        "pantone": "19-4007 TCX",
        "hex": "#252727",
        "lab_dip": "Approved 2026-04-12",
        "strike_off": "N/A",
        "handloom": "N/A",
        "status": "PP approved",
    },
    {
        "colorway_code": "WHT-001",
        "color_name": "Bright White",
        "pantone": "11-0601 TCX",
        "hex": "#F4F5F0",
        "lab_dip": "Approved 2026-04-12",
        "strike_off": "N/A",
        "handloom": "N/A",
        "status": "PP approved",
    },
    {
        "colorway_code": "BLU-002",
        "color_name": "Cobalt",
        "pantone": "18-3949 TCX",
        "hex": "#3B4995",
        "lab_dip": "Round 2 — comments sent",
        "strike_off": "N/A",
        "handloom": "N/A",
        "status": "In review",
    },
    {
        "colorway_code": "GRN-003",
        "color_name": "Loden",
        "pantone": "19-0319 TCX",
        "hex": "#5A6048",
        "lab_dip": "Round 1 — pending",
        "strike_off": "N/A",
        "handloom": "N/A",
        "status": "Submitted",
    },
]


# ---------------------------------------------------------------------------
# Revisions — preview. Static revision history.
# ---------------------------------------------------------------------------

MOCK_REVISIONS: list[dict[str, Any]] = [
    {
        "rev": "Rev 0",
        "date": "2026-04-02",
        "author": "SpecBot",
        "stage": "Proto",
        "summary": "Initial AI-drafted tech pack from sketch.",
    },
    {
        "rev": "Rev 1",
        "date": "2026-04-09",
        "author": "T. Designer",
        "stage": "Fit 1",
        "summary": "Adjusted chest +0.25, neck width +0.125, added fitting notes from Fit 1.",
    },
    {
        "rev": "Rev 2",
        "date": "2026-04-21",
        "author": "T. Designer",
        "stage": "Fit 2",
        "summary": "Sleeve length -0.5, armhole drop +0.25, BOM revised: rib trim from 1x1 to 2x2.",
    },
    {
        "rev": "Rev 3",
        "date": "2026-04-29",
        "author": "Factory (Lotus)",
        "stage": "PP",
        "summary": "Factory comments: SPI from 12 to 11 at hem; care label position moved.",
    },
]


# ---------------------------------------------------------------------------
# Sketch annotations — preview. Numbered callouts on the sketch.
# ---------------------------------------------------------------------------

MOCK_SKETCH_ANNOTATIONS: list[dict[str, Any]] = [
    {"id": 1, "zone": "Neckline", "callout": "Self-fabric binding, 0.5\" finished"},
    {"id": 2, "zone": "Shoulder seam", "callout": "Tape reinforcement, 401 chainstitch"},
    {"id": 3, "zone": "Armhole", "callout": "504 overlock, no topstitch"},
    {"id": 4, "zone": "Side seam", "callout": "504 overlock + 301 single-needle topstitch"},
    {"id": 5, "zone": "Body hem", "callout": "1\" cover-stitched (406), 11 SPI"},
]


# ---------------------------------------------------------------------------
# Fitting Room — preview. Voice-driven fitting capture on iPad / phone.
# This is the home-run flow: voice + photo in the fitting room → structured
# tech pack updates + factory comments before the TD leaves the room.
# ---------------------------------------------------------------------------

MOCK_FITTING_TRANSCRIPT: str = """[Fit 2 — Style TST-001 Demo Tee — Model: size M, 0:00–1:48]

"Walking front view. Neckline is sitting flat, that's clean. Chest area
is binding — looks like about a centimeter under the bust line. Let's
open the chest by half an inch.

Side view now. Armhole is sitting too high — you can see it pulling
when she raises her arm. Drop the armhole by half an inch.

Sleeves — sleeve length is dragging on her watch, take it up by
three-quarters of an inch. Cuff opening looks fine.

Back. Back length is good. Hem sits where we want it. Side seam is
twisting forward maybe a quarter inch — flag for the pattern team,
might be a grain issue on the back panel.

Overall fit feels close. Photos coming through to Lotus tonight."
"""

MOCK_FITTING_STRUCTURED_UPDATES: list[dict[str, Any]] = [
    {
        "#": 1,
        "POM": "Chest Width",
        "Δ": '+0.5"',
        "Reason": "binding ~1 cm under bust",
        "Voice @": "0:14",
        "Confidence": "High",
    },
    {
        "#": 2,
        "POM": "Armhole Drop",
        "Δ": '+0.5"',
        "Reason": "pulling on raised arm",
        "Voice @": "0:38",
        "Confidence": "High",
    },
    {
        "#": 3,
        "POM": "Sleeve Length",
        "Δ": '-0.75"',
        "Reason": "covers watch on this model",
        "Voice @": "1:02",
        "Confidence": "High",
    },
    {
        "#": 4,
        "POM": "(pattern flag)",
        "Δ": "—",
        "Reason": 'side seam twist 0.25" — grain check on back panel',
        "Voice @": "1:31",
        "Confidence": "Flag for patternmaker",
    },
]

MOCK_FITTING_PINNED_PHOTOS: list[dict[str, Any]] = [
    {"#": 1, "zone": "Chest", "note": "Binding ~1 cm under bust line", "voice @": "0:18"},
    {"#": 2, "zone": "Armhole", "note": '0.5" lift when arm raised', "voice @": "0:42"},
    {"#": 3, "zone": "Sleeve hem", "note": "Length covering watch", "voice @": "1:05"},
    {"#": 4, "zone": "Side seam", "note": "Forward twist, grain check", "voice @": "1:32"},
]

MOCK_FITTING_DRAFT_SUBJECT: str = "[SpecBot] Fit 2 comments — TST-001 Demo Tee"

MOCK_FITTING_DRAFT_BODY: str = """Hi Linh,

Following Fit 2 today on size M, please see the attached revised tech pack
with photo callouts.

Key POM changes from Rev 2:
  • Chest Width: +0.5"  (binding ~1 cm under bust)
  • Armhole Drop: +0.5"  (pulling when arm raised)
  • Sleeve Length: -0.75"  (covers watch on this model)

Photos are pinned to construction zones in the PDF — each one anchored to
the voice-note timestamp from the session for context.

Pattern team: please review the side seam, the back panel grain looks ~0.25"
off. I've routed this to Sofia in the patternmaking channel as well.

Could we have Sample 3 ready to ship by 2026-05-12?

Thanks,
SpecBot AI Fitting Assistant
(drafted from Fit 2 voice + photo session, reviewed by T. Designer)
"""


# ---------------------------------------------------------------------------
# Brand Library — preview. The RAG layer that grounds every AI generation
# in this specific brand's data. SpecBot syncs from the brand's existing
# system of record (PLM, Drive, CSVs); it does not replace it.
# ---------------------------------------------------------------------------

MOCK_BRAND_NAME: str = "Demo Brand Co."

MOCK_BRAND_FABRICS: list[dict[str, Any]] = [
    {
        "code": "FBR-0001", "name": "180gsm Cotton Jersey", "weight": "180gsm",
        "composition": "100% cotton", "mill": "Premier Mills", "hand": "soft, smooth",
        "garment_types": "tees, polos", "lead_time_days": 35, "moq_yd": 500,
    },
    {
        "code": "FBR-0002", "name": "220gsm Slub Jersey", "weight": "220gsm",
        "composition": "100% cotton", "mill": "Premier Mills", "hand": "textured, vintage",
        "garment_types": "tees, henleys", "lead_time_days": 35, "moq_yd": 300,
    },
    {
        "code": "FBR-0014", "name": "350gsm French Terry", "weight": "350gsm",
        "composition": "80/20 cotton/poly", "mill": "Hanil Knit", "hand": "soft, lofty",
        "garment_types": "hoodies, sweatpants", "lead_time_days": 42, "moq_yd": 400,
    },
    {
        "code": "FBR-0023", "name": "11oz Selvedge Denim", "weight": "11oz",
        "composition": "100% cotton", "mill": "Cone Mills", "hand": "crisp, structured",
        "garment_types": "denim jackets, jeans", "lead_time_days": 60, "moq_yd": 800,
    },
    {
        "code": "FBR-0031", "name": "Cotton Pique", "weight": "200gsm",
        "composition": "100% cotton", "mill": "Premier Mills", "hand": "structured, breathable",
        "garment_types": "polos, button-downs", "lead_time_days": 35, "moq_yd": 400,
    },
    {
        "code": "FBR-0042", "name": "Loden Wool Melton", "weight": "550gsm",
        "composition": "70/30 wool/poly", "mill": "Boselli", "hand": "warm, dense",
        "garment_types": "outerwear", "lead_time_days": 55, "moq_yd": 200,
    },
]

MOCK_BRAND_TRIMS: list[dict[str, Any]] = [
    {
        "code": "TRM-LBL-001", "type": "Main label (woven)", "vendor": "Avery Dennison",
        "part_no": "AD-WOV-DBC", "spec": "Woven satin, 1×2in, brand logo black on white",
        "moq_ea": 2000,
    },
    {
        "code": "TRM-LBL-002", "type": "Care label", "vendor": "Avery Dennison",
        "part_no": "AD-CAR-STD", "spec": "Polyester, fold-over, multi-language",
        "moq_ea": 5000,
    },
    {
        "code": "TRM-DRC-001", "type": "Drawcord", "vendor": "YKK",
        "part_no": "DRC-FLAT-W12", "spec": "12mm flat woven cotton, brand colorways",
        "moq_ea": 1000,
    },
    {
        "code": "TRM-ZIP-001", "type": "Zipper", "vendor": "YKK",
        "part_no": "5VS-OPN-METAL", "spec": "5mm metal, open-end, antique brass",
        "moq_ea": 500,
    },
    {
        "code": "TRM-BTN-001", "type": "Button (4-hole)", "vendor": "Buttoneer",
        "part_no": "BT-COR-15-NAT", "spec": "15L corozo, natural finish, 4-hole",
        "moq_ea": 1000,
    },
    {
        "code": "TRM-HTG-001", "type": "Hangtag set", "vendor": "Avery Dennison",
        "part_no": "HT-KRAFT-SET", "spec": "Recycled kraft hangtag + cotton string + safety pin",
        "moq_ea": 1000,
    },
]

MOCK_BRAND_CONSTRUCTION_STANDARDS: list[dict[str, Any]] = [
    {
        "garment_type": "Tee (crewneck)", "zone": "Neckline",
        "stitch": "401 Chainstitch", "seam": "1.01.01 Plain", "spi": 12,
        "notes": "Self-fabric binding, 0.5in finished",
    },
    {
        "garment_type": "Tee (crewneck)", "zone": "Side seam",
        "stitch": "504 Overlock", "seam": "1.01.01 Plain", "spi": 12,
        "notes": "No topstitch on side",
    },
    {
        "garment_type": "Tee (crewneck)", "zone": "Hem",
        "stitch": "406 Coverstitch", "seam": "6.02.01 Edge", "spi": 11,
        "notes": "1in finished hem",
    },
    {
        "garment_type": "Hoodie", "zone": "Hood",
        "stitch": "504 Overlock + 301 topstitch", "seam": "1.06.02 French", "spi": 11,
        "notes": "Lined hood, drawcord-eyelet at center front",
    },
    {
        "garment_type": "Hoodie", "zone": "Pocket entry",
        "stitch": "301 Lockstitch + bartack", "seam": "2.02.03 Lapped", "spi": 11,
        "notes": "Bartack at top and bottom of kangaroo pocket",
    },
    {
        "garment_type": "Denim jacket", "zone": "All seams",
        "stitch": "401 Chainstitch double-needle", "seam": "2.02.03 Flat-felled", "spi": 8,
        "notes": "Contrast topstitch in tobacco gold thread",
    },
]

MOCK_BRAND_HISTORICAL_STYLES: list[dict[str, Any]] = [
    {
        "style_no": "TEE-2024-018", "name": "Classic Crew Tee",
        "garment_type": "Tee", "fabric_code": "FBR-0001", "season": "SS24",
        "factory": "Lotus Apparel Manufacturing",
        "fit_history": "3 fit rounds; chest let out +0.5 between Fit 1 and PP",
        "rating": "★★★★★ — bestseller",
    },
    {
        "style_no": "TEE-2024-031", "name": "Slub Pocket Tee",
        "garment_type": "Tee", "fabric_code": "FBR-0002", "season": "SS24",
        "factory": "Lotus Apparel Manufacturing",
        "fit_history": "2 fit rounds; sleeve length adjusted -0.25",
        "rating": "★★★★ — solid seller",
    },
    {
        "style_no": "HOO-2023-007", "name": "Heavyweight Hoodie",
        "garment_type": "Hoodie", "fabric_code": "FBR-0014", "season": "FW23",
        "factory": "Dhaka Knit House",
        "fit_history": "4 fit rounds; hood depth issues — final +0.75",
        "rating": "★★★★★ — bestseller",
    },
    {
        "style_no": "HOO-2024-012", "name": "Cropped Hoodie",
        "garment_type": "Hoodie", "fabric_code": "FBR-0014", "season": "SS24",
        "factory": "Lotus Apparel Manufacturing",
        "fit_history": "2 fit rounds; body length -2 inches from base hoodie block",
        "rating": "★★★ — slow seller",
    },
    {
        "style_no": "DJK-2023-001", "name": "Selvedge Trucker",
        "garment_type": "Denim jacket", "fabric_code": "FBR-0023", "season": "FW23",
        "factory": "Andes Denim Works",
        "fit_history": "5 fit rounds; complex grading",
        "rating": "★★★★ — capsule hit",
    },
]

MOCK_FACTORY_PROFILES: list[dict[str, Any]] = [
    {
        "factory": "Lotus Apparel Manufacturing", "country": "Vietnam",
        "specialty": "Knitwear, jersey tops",
        "preferred_fabrics": "FBR-0001, FBR-0002, FBR-0014",
        "moq_pcs": 300, "lead_time_days": 75,
        "house_quirks": "Prefers 401 chainstitch on knit hems; uses metric tolerances internally.",
    },
    {
        "factory": "Andes Denim Works", "country": "Peru",
        "specialty": "Denim, woven bottoms, washes",
        "preferred_fabrics": "FBR-0023",
        "moq_pcs": 500, "lead_time_days": 90,
        "house_quirks": "Wash recipes communicated by photo, not code; require lab dip approval pre-bulk.",
    },
    {
        "factory": "Istanbul Outerwear Co.", "country": "Turkey",
        "specialty": "Outerwear, technical jackets",
        "preferred_fabrics": "FBR-0042",
        "moq_pcs": 200, "lead_time_days": 100,
        "house_quirks": "Requires construction page in Turkish + English; pattern review before sample.",
    },
    {
        "factory": "Dhaka Knit House", "country": "Bangladesh",
        "specialty": "Cut-and-sew knit, basics, large MOQ",
        "preferred_fabrics": "FBR-0001, FBR-0014",
        "moq_pcs": 1000, "lead_time_days": 110,
        "house_quirks": "Best on >1k MOQ; comments come back as scanned PDFs, not structured.",
    },
    {
        "factory": "Porto Atelier", "country": "Portugal",
        "specialty": "Premium woven, shirting, small batch",
        "preferred_fabrics": "FBR-0031",
        "moq_pcs": 100, "lead_time_days": 60,
        "house_quirks": "Excellent on small runs; expects ISO 4915/4916 in spec; pattern team in-house.",
    },
]

# What the AI reports back when grounded against the brand library.
MOCK_GROUNDING_REPORTS: dict[str, dict[str, Any]] = {
    "tee": {
        "matched_fabric": "FBR-0001 — 180gsm Cotton Jersey (Premier Mills)",
        "similar_styles": [
            "TEE-2024-018 Classic Crew Tee (★★★★★)",
            "TEE-2024-031 Slub Pocket Tee (★★★★)",
        ],
        "applied_construction": [
            "Neckline: 401 chainstitch + self-fabric binding (house standard)",
            "Side seam: 504 overlock, no topstitch",
            "Hem: 406 coverstitch, 11 SPI, 1in finished",
        ],
        "factory_routing": "Lotus Apparel — preferred for jersey knits, MOQ-friendly, 75-day lead",
        "fit_history_signal": (
            "Last 3 tees averaged +0.4in chest let-out by PP — flagging as common adjustment."
        ),
    },
    "hoodie": {
        "matched_fabric": "FBR-0014 — 350gsm French Terry (Hanil Knit)",
        "similar_styles": [
            "HOO-2023-007 Heavyweight Hoodie (★★★★★)",
            "HOO-2024-012 Cropped Hoodie (★★★)",
        ],
        "applied_construction": [
            "Hood: 504 overlock + 301 topstitch, drawcord-eyelet at CF",
            "Pocket entry: 301 lockstitch + bartack top and bottom",
        ],
        "factory_routing": "Dhaka Knit House — bestseller history on this fabric, 110-day lead",
        "fit_history_signal": (
            "Hood depth historically runs 0.75in deeper than draft. Suggest pre-emptive +0.5 adjustment."
        ),
    },
    "denim_jacket": {
        "matched_fabric": "FBR-0023 — 11oz Selvedge Denim (Cone Mills)",
        "similar_styles": ["DJK-2023-001 Selvedge Trucker (★★★★)"],
        "applied_construction": [
            "All seams: 401 chainstitch double-needle, flat-felled, 8 SPI",
            "Topstitch: tobacco gold thread (house standard)",
        ],
        "factory_routing": "Andes Denim Works — only factory currently approved on this fabric",
        "fit_history_signal": "Denim trucker historically needs 5 fit rounds — block 9 weeks for development.",
    },
    "default": {
        "matched_fabric": "(no exact match in brand library — flagging for sourcing review)",
        "similar_styles": ["(no close matches found)"],
        "applied_construction": ["Generic industry construction applied — review required."],
        "factory_routing": "(no factory pre-routed — designer to assign)",
        "fit_history_signal": "No comparable history. Add to assumptions and review during Fit 1.",
    },
}


def get_grounding_report(garment_type: str) -> dict[str, Any]:
    """Match a freeform garment type to a mock grounding report."""
    g = (garment_type or "").lower()
    if "tee" in g or "t-shirt" in g or "polo" in g:
        return MOCK_GROUNDING_REPORTS["tee"]
    if "hood" in g or "sweatshirt" in g:
        return MOCK_GROUNDING_REPORTS["hoodie"]
    if "denim" in g or "jean" in g or "trucker" in g:
        return MOCK_GROUNDING_REPORTS["denim_jacket"]
    return MOCK_GROUNDING_REPORTS["default"]


# ---------------------------------------------------------------------------
# Feature roadmap — drives the sidebar status panel.
# ---------------------------------------------------------------------------

FEATURE_ROADMAP: list[dict[str, str]] = [
    {"feature": "AI sketch → tech pack", "status": "live"},
    {"feature": "Brand library grounding (fabrics, trims, construction)", "status": "live"},
    {"feature": "Editable measurement table", "status": "live"},
    {"feature": "Construction notes", "status": "live"},
    {"feature": "BOM table", "status": "live"},
    {"feature": "Excel export (multi-sheet)", "status": "live"},
    {"feature": "Fitting-note → POM updates", "status": "live"},
    {"feature": "Voice transcription (Whisper)", "status": "live"},
    {"feature": "Fit photos pinned to construction zones", "status": "live"},
    {"feature": "AI-drafted factory email from fit session", "status": "live"},
    {"feature": "Change log", "status": "live"},
    {"feature": "Sample stage tracking", "status": "live"},
    {"feature": "Send to factory (test mode)", "status": "live"},
    {"feature": "WIP dashboard", "status": "live"},
    {"feature": "ISO 4915 / 4916 stitch & seam codes", "status": "live"},
    {"feature": "Grading across full size run", "status": "live"},
    {"feature": "Sketch annotations / callouts", "status": "live"},
    {"feature": "Tech-pack persistence (resume work across sessions)", "status": "live"},
    {"feature": "Costing rollup → target FOB", "status": "preview"},
    {"feature": "Colorways & Pantone tracking", "status": "preview"},
    {"feature": "Lab dip / strike-off / handloom approvals", "status": "preview"},
    {"feature": "Drag-to-pin annotations on sketch", "status": "preview"},
    {"feature": "Revision history & diff", "status": "preview"},
    {"feature": "Live in-browser mic capture", "status": "preview"},
    {"feature": "PLM sync (Centric / Backbone / FlexPLM)", "status": "preview"},
    {"feature": "CSV / Drive folder ingest", "status": "preview"},
    {"feature": "Factory reply intake", "status": "preview"},
]
