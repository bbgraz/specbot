"""SpecBot AI Technical Designer — single-page Streamlit demo."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from brand_library import build_grounding, grounding_for_prompt, grounding_report
from email_sender import send_factory_email
from excel_exporter import export_tech_pack_to_excel
from fit_update_service import apply_fitting_notes
from mock_data import (
    CONSTRUCTION_ZONES,
    DEFAULT_GRADE_RULES,
    DEFAULT_SIZE_RUN,
    DEFAULT_STAGE,
    FEATURE_ROADMAP,
    ISO_4915_STITCH_TYPES,
    ISO_4916_SEAM_CLASSES,
    MOCK_BRAND_CONSTRUCTION_STANDARDS,
    MOCK_BRAND_FABRICS,
    MOCK_BRAND_HISTORICAL_STYLES,
    MOCK_BRAND_NAME,
    MOCK_BRAND_TRIMS,
    MOCK_COLORWAYS,
    MOCK_COSTING_LINES,
    MOCK_COSTING_TARGET_FOB,
    MOCK_COSTING_TOTAL_FOB,
    MOCK_FACTORY_PROFILES,
    MOCK_FITTING_TRANSCRIPT,
    MOCK_REVISIONS,
    SAMPLE_STAGES,
    build_graded_table,
)
from tech_pack_store import (
    delete_tech_pack,
    list_tech_packs,
    load_tech_pack,
    save_tech_pack,
)
from spec_blocks import build_offline_draft
from wip_store import add_or_update_wip_record, load_wip_records

load_dotenv()

_DEFAULT_FACTORY_PATH = Path(__file__).resolve().parent / "factory_contacts.json"
FACTORY_PATH = Path(os.getenv("SPECBOT_FACTORY_PATH") or _DEFAULT_FACTORY_PATH)

PREVIEW_BADGE = "🔒 Preview"
LIVE_BADGE = "✅ Live"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def load_factories() -> list[dict[str, Any]]:
    if not FACTORY_PATH.is_file():
        return []
    with FACTORY_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _empty_tech_pack() -> dict[str, Any]:
    return {
        "style_number": "",
        "style_name": "",
        "garment_type": "",
        "fabric": "",
        "sample_size": "",
        "sample_stage": DEFAULT_STAGE,
        "garment_summary": "",
        "detected_features": [],
        "measurements": [],
        "construction_notes": [],
        "bom": [],
        "change_log": [],
        "assumptions": [],
        "missing_information": [],
        "annotations": [],
        "grade_rules": dict(DEFAULT_GRADE_RULES),
        "grounding_report": {},
        "fit_photos": [],
    }


def _normalize_construction(notes: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in notes or []:
        if isinstance(item, dict):
            out.append(
                {
                    "note": item.get("note", ""),
                    "zone": item.get("zone", "(general)"),
                    "stitch_type": item.get("stitch_type", ""),
                    "seam_class": item.get("seam_class", ""),
                    "spi": item.get("spi", ""),
                    "source": item.get("source", ""),
                }
            )
        else:
            out.append(
                {
                    "note": str(item),
                    "zone": "(general)",
                    "stitch_type": "",
                    "seam_class": "",
                    "spi": "",
                    "source": "",
                }
            )
    return out


def _to_tech_pack(analysis: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Map the GPT analysis blob to our internal tech_pack shape."""
    construction = _normalize_construction(analysis.get("construction_notes", []) or [])

    bom = []
    for item in analysis.get("bom_items", []) or []:
        bom.append(
            {
                "component": item.get("component", ""),
                "material": item.get("material", ""),
                "placement": item.get("placement", ""),
                "notes": item.get("notes", ""),
                "source": item.get("source", ""),
            }
        )

    measurements = []
    for m in analysis.get("suggested_measurements", []) or []:
        measurements.append(
            {
                "pom": m.get("pom", ""),
                "description": m.get("description", ""),
                "target": m.get("target", ""),
                "tolerance_plus": m.get("tolerance_plus", ""),
                "tolerance_minus": m.get("tolerance_minus", ""),
                "source": m.get("source", ""),
                "notes": m.get("notes", ""),
            }
        )

    tp = {
        **_empty_tech_pack(),
        **metadata,
        "garment_summary": analysis.get("garment_summary", ""),
        "detected_features": analysis.get("detected_features", []) or [],
        "measurements": measurements,
        "construction_notes": construction,
        "bom": bom,
        "assumptions": analysis.get("assumptions", []) or [],
        "missing_information": analysis.get("missing_information", []) or [],
    }
    grounding_payload = analysis.get("grounding_report")
    if grounding_payload:
        tp["grounding_report"] = grounding_payload
    return tp


def _measurements_df(tech_pack: dict[str, Any]) -> pd.DataFrame:
    rows = tech_pack.get("measurements", [])
    if not rows:
        return pd.DataFrame(
            columns=[
                "pom",
                "description",
                "target",
                "tolerance_plus",
                "tolerance_minus",
                "source",
                "notes",
            ]
        )
    return pd.DataFrame(rows)


def _bom_df(tech_pack: dict[str, Any]) -> pd.DataFrame:
    rows = tech_pack.get("bom", [])
    if not rows:
        return pd.DataFrame(columns=["component", "material", "placement", "notes", "source"])
    return pd.DataFrame(rows)


def _construction_df(tech_pack: dict[str, Any]) -> pd.DataFrame:
    rows = _normalize_construction(tech_pack.get("construction_notes", []))
    if not rows:
        return pd.DataFrame(columns=["note", "zone", "stitch_type", "seam_class", "spi", "source"])
    return pd.DataFrame(rows)


def _change_log_df(tech_pack: dict[str, Any]) -> pd.DataFrame:
    rows = tech_pack.get("change_log", [])
    if not rows:
        return pd.DataFrame(
            columns=["timestamp", "pom", "field", "old_value", "new_value", "reason"]
        )
    return pd.DataFrame(rows)


def _df_to_measurements(df: pd.DataFrame) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        out.append(
            {
                "pom": str(row.get("pom", "")),
                "description": str(row.get("description", "")),
                "target": str(row.get("target", "")),
                "tolerance_plus": str(row.get("tolerance_plus", "")),
                "tolerance_minus": str(row.get("tolerance_minus", "")),
                "source": str(row.get("source", "")),
                "notes": str(row.get("notes", "")),
            }
        )
    return out


def _df_to_construction(df: pd.DataFrame) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        out.append(
            {
                "note": str(row.get("note", "")),
                "zone": str(row.get("zone", "(general)")),
                "stitch_type": str(row.get("stitch_type", "")),
                "seam_class": str(row.get("seam_class", "")),
                "spi": str(row.get("spi", "")),
                "source": str(row.get("source", "")),
            }
        )
    return out


def _preview_banner(text: str) -> None:
    st.info(f"{PREVIEW_BADGE} — {text}", icon="🔒")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _from_b64(s: str) -> bytes:
    if not s:
        return b""
    try:
        return base64.b64decode(s.encode("ascii"))
    except (ValueError, TypeError):
        return b""


def _persist_current_tech_pack() -> None:
    """Save the currently-loaded tech pack to disk; swallow errors quietly."""
    tp = st.session_state.get("tech_pack") or {}
    if not tp.get("style_number"):
        return
    try:
        save_tech_pack(tp)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def _init_state() -> None:
    st.session_state.setdefault("tech_pack", _empty_tech_pack())
    st.session_state.setdefault("export_path", None)
    st.session_state.setdefault("last_email_result", None)
    st.session_state.setdefault("last_fitting_summary", None)
    st.session_state.setdefault("uploaded_sketch_bytes", None)
    st.session_state.setdefault("uploaded_sketch_mime", None)
    st.session_state.setdefault("fitting_demo_played", False)
    st.session_state.setdefault("fitting_transcript", "")
    st.session_state.setdefault("fitting_change_count", 0)
    st.session_state.setdefault("fitting_draft_subject", "")
    st.session_state.setdefault("fitting_draft_body", "")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


def _sidebar_saved_styles() -> None:
    saved = list_tech_packs()
    st.markdown("### Saved styles")
    if not saved:
        st.caption("No saved tech packs yet. Generate a style to populate this list.")
        return

    options = ["—"] + [
        f"{s['style_number']} · {s['style_name'] or '(no name)'} · {s['sample_stage']}"
        for s in saved
    ]
    choice = st.selectbox(
        "Open a saved style",
        options=options,
        index=0,
        key="sidebar_open_saved",
    )
    if choice and choice != "—":
        idx = options.index(choice) - 1
        target = saved[idx]
        cols = st.columns(2)
        if cols[0].button("Load", key="sidebar_load_btn", use_container_width=True):
            loaded = load_tech_pack(target["style_number"])
            if loaded:
                st.session_state.tech_pack = {**_empty_tech_pack(), **loaded}
                st.session_state.export_path = None
                st.session_state.uploaded_sketch_bytes = None
                st.session_state.uploaded_sketch_mime = None
                st.success(f"Loaded {target['style_number']}.")
                st.rerun()
            else:
                st.error("Could not load that tech pack.")
        if cols[1].button("Delete", key="sidebar_delete_btn", use_container_width=True):
            if delete_tech_pack(target["style_number"]):
                st.success(f"Deleted {target['style_number']}.")
                st.rerun()
            else:
                st.error("Delete failed.")


def sidebar() -> None:
    tech_pack = st.session_state.tech_pack
    with st.sidebar:
        st.markdown("### Current style")
        if tech_pack.get("style_number"):
            st.markdown(
                f"**{tech_pack.get('style_number')}** · {tech_pack.get('style_name') or '(no name)'}"
            )
            st.caption(
                f"Stage: **{tech_pack.get('sample_stage', DEFAULT_STAGE)}**  ·  "
                f"Type: {tech_pack.get('garment_type') or '—'}  ·  "
                f"Sample size: {tech_pack.get('sample_size') or '—'}"
            )
        else:
            st.caption("No style loaded yet.")

        st.divider()
        _sidebar_saved_styles()

        st.divider()
        st.markdown("### Roadmap")
        live = [r for r in FEATURE_ROADMAP if r["status"] == "live"]
        preview = [r for r in FEATURE_ROADMAP if r["status"] == "preview"]
        st.markdown(f"**{LIVE_BADGE} ({len(live)})**")
        for r in live:
            st.markdown(f"- {r['feature']}")
        st.markdown(f"**{PREVIEW_BADGE} ({len(preview)})**")
        for r in preview:
            st.markdown(f"- {r['feature']}")

        st.divider()
        st.caption(
            "Demo only. Outbound emails are forced to `TEST_EMAIL_RECIPIENT`. "
            "Tech-pack values must be reviewed by a technical designer."
        )


# ---------------------------------------------------------------------------
# UI sections
# ---------------------------------------------------------------------------


def _inject_css() -> None:
    """One-shot CSS to tighten Streamlit's default chrome and brand the surface."""
    st.markdown(
        """
        <style>
        /* Hide Streamlit's default toolbar + footer for a cleaner product feel. */
        [data-testid="stToolbar"], #MainMenu, footer { visibility: hidden; height: 0; }
        header[data-testid="stHeader"] { background: transparent; height: 0; }

        /* Tighter top/bottom padding on the main canvas. */
        .block-container { padding-top: 1.25rem; padding-bottom: 2rem; max-width: 1400px; }

        /* Top-level tab strip — make it feel like real navigation. */
        div[data-testid="stTabs"] > div[role="tablist"] {
            gap: 0.25rem;
            border-bottom: 1px solid rgba(148, 163, 184, 0.18);
            padding-bottom: 0;
            margin-bottom: 1.25rem;
        }
        div[data-testid="stTabs"] > div[role="tablist"] button[role="tab"] {
            padding: 0.55rem 1rem;
            border-radius: 6px 6px 0 0;
            font-weight: 500;
            color: rgba(148, 163, 184, 0.95);
            border-bottom: 2px solid transparent;
            transition: color 120ms, border-color 120ms;
        }
        div[data-testid="stTabs"] > div[role="tablist"] button[role="tab"]:hover {
            color: white;
        }
        div[data-testid="stTabs"] > div[role="tablist"] button[role="tab"][aria-selected="true"] {
            color: white;
            border-bottom-color: #6366F1;
        }

        /* Compact hero. */
        .specbot-hero h1 {
            font-size: 1.85rem;
            margin-bottom: 0.15rem;
            letter-spacing: -0.02em;
        }
        .specbot-hero p.specbot-tagline {
            color: rgba(148, 163, 184, 0.95);
            margin: 0;
            font-size: 1rem;
        }

        /* Status strip showing the loaded style. */
        .specbot-status-strip {
            display: flex;
            gap: 1.25rem;
            padding: 0.65rem 1rem;
            margin: 0.75rem 0 1rem;
            background: rgba(99, 102, 241, 0.08);
            border: 1px solid rgba(99, 102, 241, 0.25);
            border-radius: 8px;
            font-size: 0.92rem;
        }
        .specbot-status-strip .pill { font-weight: 600; color: white; }
        .specbot-status-strip .label { color: rgba(148, 163, 184, 0.95); margin-right: 0.35rem; }

        /* Subheader rhythm inside tabs. */
        h2 { font-size: 1.4rem; margin-top: 0.25rem; }
        h3 { font-size: 1.1rem; }

        /* Metric polish. */
        [data-testid="stMetric"] {
            background: rgba(148, 163, 184, 0.06);
            border: 1px solid rgba(148, 163, 184, 0.15);
            border-radius: 8px;
            padding: 0.65rem 0.85rem;
        }

        /* Sidebar tightening. */
        [data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }
        [data-testid="stSidebar"] hr { margin: 0.6rem 0; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _hero() -> None:
    st.markdown(
        """
        <div class="specbot-hero">
          <h1>SpecBot — AI Technical Designer</h1>
          <p class="specbot-tagline">From sketch and fitting notes to factory-ready tech packs, grounded in your brand library.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not os.getenv("OPENAI_API_KEY"):
        st.warning(
            "OPENAI_API_KEY is not set. Tech-pack generation will fail; fitting-note "
            "updates will fall back to a small rule-based parser.",
            icon="⚠️",
        )


def _status_strip() -> None:
    tech_pack = st.session_state.tech_pack
    if not tech_pack.get("style_number"):
        return
    style_no = tech_pack.get("style_number") or "(no #)"
    style_name = tech_pack.get("style_name") or "(no name)"
    stage = tech_pack.get("sample_stage", DEFAULT_STAGE)
    garment = tech_pack.get("garment_type") or "—"
    sample_size = tech_pack.get("sample_size") or "—"
    st.markdown(
        f"""
        <div class="specbot-status-strip">
          <div><span class="label">Style</span><span class="pill">{style_no}</span></div>
          <div><span class="label">Name</span><span class="pill">{style_name}</span></div>
          <div><span class="label">Type</span><span class="pill">{garment}</span></div>
          <div><span class="label">Sample size</span><span class="pill">{sample_size}</span></div>
          <div><span class="label">Stage</span><span class="pill">{stage}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_header() -> None:
    """Backwards-compatible shim for the old call site."""
    _hero()


def section_brand_library() -> None:
    st.markdown(
        f"**This is what the AI knows about {MOCK_BRAND_NAME}.** Every tech pack you "
        "generate is grounded against this library — fabric codes, trim codes, and house "
        "construction standards are pulled from here, not invented. SpecBot syncs from the "
        "brand's existing system of record (PLM, Drive folders, CSV exports). "
        "**We don't replace the system of record. We're the AI layer that sits on top of it.**"
    )
    st.success(
        "✅ Live grounding: the entries below are read by the GPT prompt every time you "
        "generate a tech pack. Edit `mock_data.py` to swap them out for your own data, or "
        "wire up a sync via the Sync tab (preview).",
        icon="✅",
    )

    fabrics_count = len(MOCK_BRAND_FABRICS)
    trims_count = len(MOCK_BRAND_TRIMS)
    history_count = len(MOCK_BRAND_HISTORICAL_STYLES)
    factories_count = len(MOCK_FACTORY_PROFILES)
    cstd_count = len(MOCK_BRAND_CONSTRUCTION_STANDARDS)


    cols = st.columns(5)
    cols[0].metric("Fabrics", fabrics_count)
    cols[1].metric("Trims", trims_count)
    cols[2].metric("Construction standards", cstd_count)
    cols[3].metric("Historical tech packs", history_count)
    cols[4].metric("Factory profiles", factories_count)

    tabs = st.tabs(
        [
            "Fabrics",
            "Trims",
            "Construction standards",
            "Historical styles",
            "Factory profiles",
            f"Sync  {PREVIEW_BADGE}",
        ]
    )
    with tabs[0]:
        st.dataframe(
            pd.DataFrame(MOCK_BRAND_FABRICS), use_container_width=True, hide_index=True
        )
        st.caption(
            "Each row is grounded to a real mill, code, lead time, and MOQ. "
            "When the AI drafts a tech pack, it picks from this list — never inventing a fabric."
        )
    with tabs[1]:
        st.dataframe(
            pd.DataFrame(MOCK_BRAND_TRIMS), use_container_width=True, hide_index=True
        )
        st.caption(
            "Trim library with vendor + part number. The BOM auto-populates from here, "
            "instead of the AI inventing generic trim names."
        )
    with tabs[2]:
        st.dataframe(
            pd.DataFrame(MOCK_BRAND_CONSTRUCTION_STANDARDS),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "House construction spec per garment type and zone. Drives the construction tab "
            "and the Excel construction sheet. Edited by the senior TD; applied automatically."
        )
    with tabs[3]:
        st.dataframe(
            pd.DataFrame(MOCK_BRAND_HISTORICAL_STYLES),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "Past tech packs vector-indexed for similarity search. New styles inherit fit-history "
            "signals — e.g. 'last 3 tees averaged +0.4in chest let-out by PP'."
        )
    with tabs[4]:
        st.dataframe(
            pd.DataFrame(MOCK_FACTORY_PROFILES),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "Factory profiles with capabilities, MOQ, lead time, and house quirks. "
            "Routes new styles to the right factory automatically."
        )
    with tabs[5]:
        _preview_banner(
            "Connect the brand's system of record. SpecBot is read-only by default — "
            "the brand keeps owning their data."
        )
        st.markdown("**One-click connectors**")
        c = st.columns(4)
        c[0].button("Centric PLM", disabled=True, key="conn_centric")
        c[1].button("Backbone PLM", disabled=True, key="conn_backbone")
        c[2].button("PTC FlexPLM", disabled=True, key="conn_flexplm")
        c[3].button("Bamboo Rose", disabled=True, key="conn_bamboo")
        c2 = st.columns(4)
        c2[0].button("NGC Andromeda", disabled=True, key="conn_ngc")
        c2[1].button("Lectra Kubix", disabled=True, key="conn_lectra")
        c2[2].button("Google Drive", disabled=True, key="conn_drive")
        c2[3].button("SharePoint", disabled=True, key="conn_sharepoint")

        st.markdown("**Or upload exports**")
        st.file_uploader(
            "CSV: fabric library", type=["csv"], disabled=True, key="up_fabric"
        )
        st.file_uploader(
            "CSV: trim library", type=["csv"], disabled=True, key="up_trim"
        )
        st.file_uploader(
            "ZIP: historical tech packs (Excel/PDF)",
            type=["zip"],
            disabled=True,
            key="up_history",
        )


def _load_demo_tech_pack() -> None:
    """Populate the session with a fully offline demo style (no API key needed)."""
    metadata = {
        "style_name": "Demo Tee",
        "style_number": "TST-001",
        "garment_type": "crewneck tee",
        "fabric": "180gsm cotton jersey",
        "sample_size": "M",
        "sample_stage": DEFAULT_STAGE,
    }
    analysis = build_offline_draft(metadata)
    st.session_state.tech_pack = _to_tech_pack(analysis, metadata)
    st.session_state.export_path = None
    st.session_state.uploaded_sketch_bytes = None
    st.session_state.uploaded_sketch_mime = None


def section_style_setup() -> None:
    st.markdown("Drop a sketch and a few fields. Output appears in the **Tech Pack** tab.")
    with st.form("style_setup_form", clear_on_submit=False):
        upload = st.file_uploader(
            "Upload sketch (PDF, JPG, PNG)",
            type=["pdf", "jpg", "jpeg", "png"],
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            style_name = st.text_input("Style name", key="form_style_name")
            style_number = st.text_input("Style number", key="form_style_number")
        with col2:
            garment_type = st.text_input(
                "Garment type",
                placeholder="e.g. crewneck tee, denim jacket",
                key="form_garment_type",
            )
            fabric = st.text_input(
                "Fabric", placeholder="e.g. 180gsm cotton jersey", key="form_fabric"
            )
        with col3:
            sample_size = st.text_input(
                "Sample size", placeholder="e.g. M", key="form_sample_size"
            )
            sample_stage = st.selectbox(
                "Sample stage", options=SAMPLE_STAGES, index=0, key="form_sample_stage"
            )

        submitted = st.form_submit_button("Generate Tech Pack", type="primary")

    demo_col, demo_help_col = st.columns([1, 3])
    with demo_col:
        demo_clicked = st.button("Load Demo Tech Pack", key="load_demo_btn")
    with demo_help_col:
        st.caption(
            "No API key or sketch needed — loads a sample style built from the "
            "category-standard spec block so every tab is populated."
        )
    if demo_clicked:
        _load_demo_tech_pack()
        st.success(
            "Demo tech pack loaded (offline draft from the category-standard spec block). "
            "Review it in the Tech Pack tab, then try fitting notes and export."
        )
        return

    if not submitted:
        return

    if not (style_name and style_number and garment_type):
        st.error("Style name, style number, and garment type are required.")
        return

    metadata = {
        "style_name": style_name,
        "style_number": style_number,
        "garment_type": garment_type,
        "fabric": fabric,
        "sample_size": sample_size,
        "sample_stage": sample_stage,
    }

    if upload is not None:
        try:
            st.session_state.uploaded_sketch_bytes = upload.getvalue()
            st.session_state.uploaded_sketch_mime = getattr(upload, "type", None)
        except Exception:  # noqa: BLE001
            st.session_state.uploaded_sketch_bytes = None
            st.session_state.uploaded_sketch_mime = None

    if not os.getenv("OPENAI_API_KEY"):
        analysis = build_offline_draft(metadata)
        st.session_state.tech_pack = _to_tech_pack(analysis, metadata)
        st.session_state.export_path = None
        st.warning(
            "No OPENAI_API_KEY configured — generated an offline draft from the "
            "category-standard spec block instead. The sketch was NOT analyzed. "
            "Add an API key to .env for AI sketch analysis."
        )
        return

    try:
        from gpt_service import analyze_sketch
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not import GPT service: {exc}")
        return

    grounding = build_grounding(garment_type, fabric)
    grounding_block = grounding_for_prompt(grounding)
    report = grounding_report(grounding)

    with st.spinner("Grounding against brand library and drafting tech pack…"):
        try:
            analysis = analyze_sketch(upload, metadata, grounding_block=grounding_block)
        except Exception as exc:  # noqa: BLE001
            analysis = build_offline_draft(metadata)
            st.warning(
                f"GPT call failed ({exc}). Generated an offline draft from the "
                "category-standard spec block instead — the sketch was NOT analyzed."
            )

    analysis["grounding_report"] = report
    tech_pack = _to_tech_pack(analysis, metadata)
    st.session_state.tech_pack = tech_pack
    st.session_state.export_path = None
    try:
        save_tech_pack(tech_pack)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Generated, but local save failed: {exc}")
    st.success("Draft tech pack generated and grounded against the brand library. Review below.")


# ---- Tech pack preview ----------------------------------------------------


def _tab_overview(tech_pack: dict[str, Any]) -> None:
    col_left, col_right = st.columns([2, 1])
    with col_left:
        st.markdown("**Garment summary**")
        st.markdown(tech_pack.get("garment_summary") or "_No summary available._")

        detected = tech_pack.get("detected_features") or []
        if detected:
            st.markdown("**Detected features**")
            for f in detected:
                st.markdown(f"- {f}")

    with col_right:
        st.markdown("**Sketch**")
        sketch_bytes = st.session_state.get("uploaded_sketch_bytes")
        sketch_mime = (st.session_state.get("uploaded_sketch_mime") or "").lower()
        if sketch_bytes and sketch_mime.startswith("image/"):
            st.image(sketch_bytes, use_container_width=True)
        elif sketch_bytes and sketch_mime == "application/pdf":
            st.caption("PDF uploaded — preview not rendered.")
        else:
            st.caption("No sketch uploaded.")

    st.divider()
    _render_grounding_card(tech_pack)


def _render_grounding_card(tech_pack: dict[str, Any]) -> None:
    """Show the brand-library context the AI was actually given for this style."""
    report = tech_pack.get("grounding_report") or grounding_report(
        build_grounding(tech_pack.get("garment_type", ""), tech_pack.get("fabric", ""))
    )
    with st.container(border=True):
        st.markdown(f"#### Brand grounding report  {LIVE_BADGE}")
        st.caption(
            "Every AI generation is grounded against the brand library. This card shows the "
            "fabric, construction standards, similar past styles, and factory the model was "
            "given before drafting this tech pack."
        )
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"**Matched fabric**\n\n{report['matched_fabric']}")
            st.markdown("**Similar past styles**")
            for s in report["similar_styles"]:
                st.markdown(f"- {s}")
            st.markdown(f"**Factory routing**\n\n{report['factory_routing']}")
        with col_b:
            st.markdown("**Applied house construction standards**")
            for c in report["applied_construction"]:
                st.markdown(f"- {c}")
            st.markdown(f"**Fit-history signal**\n\n{report['fit_history_signal']}")


def _tab_measurements(tech_pack: dict[str, Any]) -> None:
    st.caption(
        f"{LIVE_BADGE}. Editable. Source values control whether a row is AI-derived, "
        "inferred, a placeholder for review, or a fitting-session update."
    )
    edited = st.data_editor(
        _measurements_df(tech_pack),
        num_rows="dynamic",
        use_container_width=True,
        key="measurements_editor",
        column_config={
            "source": st.column_config.SelectboxColumn(
                "source",
                options=[
                    "matched_from_brand_library",
                    "derived_from_input",
                    "inferred_from_standard_practice",
                    "placeholder_for_review",
                    "fitting_note",
                ],
            )
        },
    )
    new_rows = _df_to_measurements(edited)
    if new_rows != tech_pack.get("measurements"):
        tech_pack["measurements"] = new_rows
        _persist_current_tech_pack()


def _tab_grading(tech_pack: dict[str, Any]) -> None:
    st.caption(
        f"{LIVE_BADGE}. Editable per-POM rules. Sample size is the anchor row; "
        "every other size is computed as `target ± rule × steps`."
    )
    measurements = tech_pack.get("measurements", []) or []
    if not measurements:
        st.info("No measurements to grade yet. Add or edit rows in the Measurements tab first.")
        return

    sample_size = tech_pack.get("sample_size") or "M"
    rule_overrides: dict[str, float] = dict(tech_pack.get("grade_rules") or {})

    rule_rows: list[dict[str, Any]] = []
    for m in measurements:
        pom = m.get("pom", "")
        if not pom:
            continue
        current = rule_overrides.get(pom)
        if current is None:
            current = _resolve_default_rule(pom)
        rule_rows.append({"POM": pom, "Grade rule (in)": float(current)})

    st.markdown("**Grade rules (per POM, inches between adjacent sizes)**")
    edited = st.data_editor(
        pd.DataFrame(rule_rows),
        num_rows="fixed",
        use_container_width=True,
        hide_index=True,
        key="grading_rules_editor",
        column_config={
            "POM": st.column_config.TextColumn("POM", disabled=True),
            "Grade rule (in)": st.column_config.NumberColumn(
                "Grade rule (in)",
                min_value=0.0,
                max_value=4.0,
                step=0.125,
                format="%.3f",
            ),
        },
    )

    new_rules: dict[str, float] = {}
    for _, row in edited.iterrows():
        pom = str(row.get("POM", "")).strip()
        if not pom:
            continue
        try:
            new_rules[pom] = float(row.get("Grade rule (in)", 0))
        except (TypeError, ValueError):
            continue

    if new_rules != tech_pack.get("grade_rules"):
        tech_pack["grade_rules"] = new_rules
        _persist_current_tech_pack()

    st.markdown("**Graded size run**")
    rows = build_graded_table(
        measurements,
        sample_size=sample_size,
        size_run=DEFAULT_SIZE_RUN,
        rule_overrides=new_rules,
    )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(
        f"Sample size **{sample_size}** is the anchor row. "
        "Edits to the rule table above immediately re-grade and persist with the style."
    )


def _resolve_default_rule(pom: str) -> float:
    name = pom.lower()
    for keyword, rule in DEFAULT_GRADE_RULES.items():
        if keyword in name:
            return rule
    return 0.5


def _tab_construction(tech_pack: dict[str, Any]) -> None:
    st.caption(
        f"{LIVE_BADGE}. Add stitch (ISO 4915), seam class (ISO 4916), and SPI per construction zone."
    )
    df = _construction_df(tech_pack)
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        key="construction_editor",
        column_config={
            "zone": st.column_config.SelectboxColumn("zone", options=CONSTRUCTION_ZONES),
            "stitch_type": st.column_config.SelectboxColumn(
                "stitch (ISO 4915)", options=[""] + ISO_4915_STITCH_TYPES
            ),
            "seam_class": st.column_config.SelectboxColumn(
                "seam (ISO 4916)", options=[""] + ISO_4916_SEAM_CLASSES
            ),
            "spi": st.column_config.TextColumn("SPI", help="Stitches per inch"),
            "source": st.column_config.SelectboxColumn(
                "source",
                options=[
                    "",
                    "matched_from_brand_library",
                    "derived_from_input",
                    "inferred_from_standard_practice",
                    "placeholder_for_review",
                    "fitting_note",
                ],
            ),
        },
    )
    new_rows = _df_to_construction(edited)
    if new_rows != tech_pack.get("construction_notes"):
        tech_pack["construction_notes"] = new_rows
        _persist_current_tech_pack()


def _tab_bom(tech_pack: dict[str, Any]) -> None:
    st.caption(f"{LIVE_BADGE}. Self fabric, trims, labels, packaging.")
    st.dataframe(_bom_df(tech_pack), use_container_width=True, hide_index=True)


def _tab_costing(tech_pack: dict[str, Any]) -> None:
    _preview_banner(
        "Costing rollup pulls fabric consumption from the marker, trim costs from the BOM, "
        "and CMT from the factory quote. Today this tab shows static demo data."
    )
    df = pd.DataFrame(MOCK_COSTING_LINES)
    df["cost_usd"] = df["cost_usd"].apply(lambda v: f"${v:.2f}")
    st.dataframe(df, use_container_width=True, hide_index=True)

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Estimated FOB", f"${MOCK_COSTING_TOTAL_FOB:,.2f}")
    col_b.metric("Target FOB", f"${MOCK_COSTING_TARGET_FOB:,.2f}")
    delta = MOCK_COSTING_TOTAL_FOB - MOCK_COSTING_TARGET_FOB
    col_c.metric(
        "Variance",
        f"${delta:+.2f}",
        delta_color="inverse" if delta > 0 else "normal",
    )


def _tab_colorways(tech_pack: dict[str, Any]) -> None:
    _preview_banner(
        "Track colorways with Pantone references and lab-dip / strike-off / handloom approval status. "
        "Today this tab shows static demo data."
    )
    for cw in MOCK_COLORWAYS:
        with st.container(border=True):
            cols = st.columns([1, 4, 3, 3])
            with cols[0]:
                st.markdown(
                    f"<div style='width:48px;height:48px;border-radius:8px;border:1px solid #ccc;background:{cw['hex']};'></div>",
                    unsafe_allow_html=True,
                )
            with cols[1]:
                st.markdown(f"**{cw['color_name']}**  ·  `{cw['colorway_code']}`")
                st.caption(f"Pantone {cw['pantone']}  ·  {cw['hex']}")
            with cols[2]:
                st.caption(f"Lab dip: {cw['lab_dip']}")
                st.caption(f"Strike-off: {cw['strike_off']}")
                st.caption(f"Handloom: {cw['handloom']}")
            with cols[3]:
                st.markdown(f"**{cw['status']}**")


def _tab_annotations(tech_pack: dict[str, Any]) -> None:
    st.caption(
        f"{LIVE_BADGE}. Numbered callouts pinned to a construction zone. "
        "Drag-to-pin on the sketch is still on the roadmap; today this is text-driven."
    )
    annotations = list(tech_pack.get("annotations") or [])
    if not annotations:
        df = pd.DataFrame(columns=["#", "zone", "callout"])
    else:
        df = pd.DataFrame(
            [
                {"#": i + 1, "zone": a.get("zone", "(general)"), "callout": a.get("callout", "")}
                for i, a in enumerate(annotations)
            ]
        )

    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="annotations_editor",
        column_config={
            "#": st.column_config.NumberColumn("#", disabled=True),
            "zone": st.column_config.SelectboxColumn("zone", options=CONSTRUCTION_ZONES),
            "callout": st.column_config.TextColumn(
                "callout", help="What does this callout describe?"
            ),
        },
    )

    new_annotations: list[dict[str, Any]] = []
    for _, row in edited.iterrows():
        callout = str(row.get("callout", "")).strip()
        zone = str(row.get("zone", "")).strip() or "(general)"
        if not callout:
            continue
        new_annotations.append(
            {"id": len(new_annotations) + 1, "zone": zone, "callout": callout}
        )

    if new_annotations != tech_pack.get("annotations"):
        tech_pack["annotations"] = new_annotations
        _persist_current_tech_pack()


def _tab_revisions(tech_pack: dict[str, Any]) -> None:
    _preview_banner(
        "Full revision history with side-by-side diff (POMs, BOM, construction). "
        "Today this tab shows static demo revisions."
    )
    df = pd.DataFrame(MOCK_REVISIONS)
    df.columns = ["Rev", "Date", "Author", "Stage", "Summary"]
    st.dataframe(df, use_container_width=True, hide_index=True)
    cols = st.columns(2)
    cols[0].button("Compare Rev 2 ↔ Rev 3", disabled=True, help="Preview only.")
    cols[1].button("Restore Rev 1", disabled=True, help="Preview only.")


def _tab_assumptions(tech_pack: dict[str, Any]) -> None:
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Assumptions**")
        for a in tech_pack.get("assumptions", []) or ["_None recorded._"]:
            st.markdown(f"- {a}")
    with col_b:
        st.markdown("**Missing information**")
        for m in tech_pack.get("missing_information", []) or ["_None recorded._"]:
            st.markdown(f"- {m}")


def section_tech_pack_preview() -> None:
    tech_pack = st.session_state.tech_pack
    if not tech_pack.get("style_number") and not tech_pack.get("garment_summary"):
        st.info("Generate a tech pack to see the preview.", icon="ℹ️")
        return

    tab_labels = [
        "Overview",
        f"Measurements  {LIVE_BADGE}",
        f"Grading  {LIVE_BADGE}",
        f"Construction  {LIVE_BADGE}",
        f"BOM  {LIVE_BADGE}",
        f"Costing  {PREVIEW_BADGE}",
        f"Colorways  {PREVIEW_BADGE}",
        f"Annotations  {LIVE_BADGE}",
        f"Revisions  {PREVIEW_BADGE}",
        "Assumptions",
    ]
    tabs = st.tabs(tab_labels)
    with tabs[0]:
        _tab_overview(tech_pack)
    with tabs[1]:
        _tab_measurements(tech_pack)
    with tabs[2]:
        _tab_grading(tech_pack)
    with tabs[3]:
        _tab_construction(tech_pack)
    with tabs[4]:
        _tab_bom(tech_pack)
    with tabs[5]:
        _tab_costing(tech_pack)
    with tabs[6]:
        _tab_colorways(tech_pack)
    with tabs[7]:
        _tab_annotations(tech_pack)
    with tabs[8]:
        _tab_revisions(tech_pack)
    with tabs[9]:
        _tab_assumptions(tech_pack)

    st.divider()
    cols = st.columns([1, 1, 4])
    with cols[0]:
        if st.button("Export Excel", key="export_btn"):
            try:
                path = export_tech_pack_to_excel(tech_pack)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Excel export failed: {exc}")
                return
            st.session_state.export_path = path
            st.success(f"Excel exported: {Path(path).name}")
    with cols[1]:
        if st.session_state.export_path and Path(st.session_state.export_path).is_file():
            path = Path(st.session_state.export_path)
            with path.open("rb") as fh:
                st.download_button(
                    "Download Excel",
                    fh.read(),
                    file_name=path.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="download_excel_btn",
                )


# ---- Fitting -------------------------------------------------------------


def _render_fitting_room_live(tech_pack: dict[str, Any]) -> None:
    st.markdown(
        "**The home-run flow.** Voice + photo capture during the fit session, "
        "structured into POM updates, photo callouts, and a draft factory comment "
        "**before the TD leaves the room**. iPad-friendly: record into Voice Memos, "
        "drop the m4a here, snap photos and tag them by zone."
    )

    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    if not has_openai:
        st.warning(
            "OPENAI_API_KEY not set — voice transcription and AI email drafting are disabled. "
            "You can still upload photos and pin them to zones, and use the **Paste Notes** tab.",
            icon="⚠️",
        )

    st.markdown("##### 1 · Capture voice")
    cols = st.columns([2, 1])
    with cols[0]:
        audio_upload = st.file_uploader(
            "Voice recording (m4a / wav / mp3 / webm)",
            type=["m4a", "wav", "mp3", "webm", "mp4", "ogg"],
            key="fitting_audio_upload",
        )
    with cols[1]:
        load_demo = st.button("Load demo transcript", key="fitting_load_demo")

    if load_demo:
        st.session_state.fitting_transcript = MOCK_FITTING_TRANSCRIPT
        st.session_state.fitting_demo_played = True

    if audio_upload is not None and has_openai:
        if st.button("Transcribe recording", key="fitting_transcribe_btn"):
            with st.spinner("Transcribing with Whisper…"):
                try:
                    from gpt_service import transcribe_audio

                    transcript = transcribe_audio(
                        audio_upload.getvalue(),
                        filename=getattr(audio_upload, "name", "fitting.m4a"),
                    )
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Transcription failed: {exc}")
                    transcript = ""
            if transcript:
                st.session_state.fitting_transcript = transcript
                st.success("Transcript captured.")

    transcript_value = st.session_state.get("fitting_transcript", "")
    transcript = st.text_area(
        "Transcript (editable)",
        value=transcript_value,
        height=180,
        key="fitting_transcript_editor",
        placeholder="Voice will land here after transcription. You can also type / paste directly.",
    )
    st.session_state.fitting_transcript = transcript

    st.markdown("##### 2 · Pin photos to zones")
    photo_uploads = st.file_uploader(
        "Fit photos (multiple OK)",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        key="fitting_photo_upload",
    )
    pinned: list[dict[str, Any]] = list(tech_pack.get("fit_photos") or [])
    if photo_uploads:
        existing_names = {p.get("filename") for p in pinned}
        for up in photo_uploads:
            if up.name in existing_names:
                continue
            pinned.append(
                {
                    "filename": up.name,
                    "zone": "(general)",
                    "note": "",
                    "bytes_b64": _b64(up.getvalue()),
                }
            )
        tech_pack["fit_photos"] = pinned
        _persist_current_tech_pack()

    if pinned:
        for i, photo in enumerate(pinned):
            with st.container(border=True):
                pcols = st.columns([1, 2, 2, 1])
                with pcols[0]:
                    img_bytes = _from_b64(photo.get("bytes_b64", ""))
                    if img_bytes:
                        st.image(img_bytes, use_container_width=True)
                    else:
                        st.caption("(no image)")
                with pcols[1]:
                    st.markdown(f"**{photo.get('filename', f'photo {i+1}')}**")
                    new_zone = st.selectbox(
                        "Zone",
                        options=CONSTRUCTION_ZONES,
                        index=(
                            CONSTRUCTION_ZONES.index(photo["zone"])
                            if photo.get("zone") in CONSTRUCTION_ZONES
                            else 0
                        ),
                        key=f"fitphoto_zone_{i}",
                    )
                with pcols[2]:
                    new_note = st.text_input(
                        "Note", value=photo.get("note", ""), key=f"fitphoto_note_{i}"
                    )
                with pcols[3]:
                    if st.button("Remove", key=f"fitphoto_rm_{i}"):
                        pinned.pop(i)
                        tech_pack["fit_photos"] = pinned
                        _persist_current_tech_pack()
                        st.rerun()
                if new_zone != photo.get("zone") or new_note != photo.get("note"):
                    photo["zone"] = new_zone
                    photo["note"] = new_note
                    tech_pack["fit_photos"] = pinned
                    _persist_current_tech_pack()
    else:
        st.caption("No fit photos pinned yet.")

    st.markdown("##### 3 · Structure POM updates from transcript")
    if st.button("Extract POM updates", key="fitting_extract_btn"):
        if not transcript.strip():
            st.warning("Add a transcript first (record, transcribe, or paste).")
        else:
            with st.spinner("Reading the transcript…"):
                revised = apply_fitting_notes(tech_pack, transcript)
            new_entries = revised.get("change_log", [])[len(tech_pack.get("change_log", [])) :]
            for entry in new_entries:
                entry.setdefault("stage", tech_pack.get("sample_stage", DEFAULT_STAGE))
            revised["fit_photos"] = pinned
            st.session_state.tech_pack = revised
            st.session_state.fitting_change_count = len(new_entries)
            _persist_current_tech_pack()
            st.success(f"{len(new_entries)} change-log entries added from the transcript.")

    if st.session_state.get("fitting_change_count"):
        st.caption(
            f"{st.session_state['fitting_change_count']} updates applied from the most recent extraction. "
            "See the **Tech Pack → Measurements / Change Log** tabs for the full diff."
        )

    st.markdown("##### 4 · Draft factory email")
    factories = load_factories()
    if factories:
        fcols = st.columns(2)
        f_idx = fcols[0].selectbox(
            "Factory",
            options=range(len(factories)),
            format_func=lambda i: factories[i]["factory_name"],
            key="fitting_factory_select",
        )
        contact_options = factories[f_idx].get("contacts", [])
        c_idx = fcols[1].selectbox(
            "Contact",
            options=range(len(contact_options)) if contact_options else [0],
            format_func=lambda i: (
                contact_options[i]["name"] if contact_options else "(no contacts)"
            ),
            key="fitting_contact_select",
        )
        factory_name = factories[f_idx]["factory_name"]
        contact_name = contact_options[c_idx]["name"] if contact_options else ""
    else:
        factory_name = ""
        contact_name = ""

    if st.button("Draft email from this session", key="fitting_draft_btn", disabled=not has_openai):
        if not transcript.strip() and not pinned:
            st.warning("Capture a transcript or pin a photo first.")
        else:
            change_log = st.session_state.tech_pack.get("change_log", []) or []
            recent_updates = change_log[-10:]
            structured = [
                {
                    "pom": e.get("pom", ""),
                    "delta": e.get("new_value", ""),
                    "reason": e.get("reason", ""),
                }
                for e in recent_updates
            ]
            with st.spinner("Drafting…"):
                try:
                    from gpt_service import draft_fitting_email

                    draft = draft_fitting_email(
                        st.session_state.tech_pack,
                        transcript,
                        structured,
                        pinned,
                        factory_name=factory_name,
                        contact_name=contact_name,
                    )
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Drafting failed: {exc}")
                    draft = None
            if draft:
                st.session_state.fitting_draft_subject = draft["subject"]
                st.session_state.fitting_draft_body = draft["body"]

    if st.session_state.get("fitting_draft_subject") or st.session_state.get("fitting_draft_body"):
        st.text_input(
            "Subject",
            value=st.session_state.get("fitting_draft_subject", ""),
            key="fitting_draft_subject_field",
        )
        st.text_area(
            "Body",
            value=st.session_state.get("fitting_draft_body", ""),
            height=260,
            key="fitting_draft_body_field",
        )
        st.caption(
            "To send, head to **Send to Factory** — copy the subject/body across, and the "
            "test-mode redirect still applies."
        )


def _render_paste_notes_tab(tech_pack: dict[str, Any]) -> None:
    cols = st.columns([2, 1])
    with cols[0]:
        notes = st.text_area(
            "Paste fitting notes",
            placeholder=(
                "e.g. Raise armhole by 0.5. Increase chest by 0.25. "
                "Sleeve cuff is too tight, add 0.5."
            ),
            height=160,
            key="fitting_notes_input",
        )
    with cols[1]:
        current_stage = tech_pack.get("sample_stage", DEFAULT_STAGE)
        try:
            stage_idx = SAMPLE_STAGES.index(current_stage)
        except ValueError:
            stage_idx = 0
        new_stage = st.selectbox(
            "Stage at fitting",
            options=SAMPLE_STAGES,
            index=stage_idx,
            key="fitting_stage_select",
        )
        st.file_uploader(
            f"Fit photos  {PREVIEW_BADGE}",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True,
            disabled=True,
            help="Upload fit photos with markup. Roadmap.",
        )

    if st.button("Update Tech Pack", key="apply_fitting_btn"):
        if not notes.strip():
            st.warning("Enter fitting notes first.")
        else:
            with st.spinner("Applying fitting notes…"):
                revised = apply_fitting_notes(tech_pack, notes)
            revised["sample_stage"] = new_stage
            for entry in revised.get("change_log", [])[len(tech_pack.get("change_log", [])):]:
                entry.setdefault("stage", new_stage)
            st.session_state.tech_pack = revised
            st.session_state.last_fitting_summary = (
                f"{len(revised.get('change_log', [])) - len(tech_pack.get('change_log', []))} "
                f"change-log entries added (anchored to {new_stage})."
            )
            st.success(st.session_state.last_fitting_summary)
            st.session_state.export_path = None
            _persist_current_tech_pack()

    tech_pack = st.session_state.tech_pack

    st.subheader("Change log")
    st.dataframe(_change_log_df(tech_pack), use_container_width=True, hide_index=True)

    st.subheader("Revised measurements")
    st.dataframe(_measurements_df(tech_pack), use_container_width=True, hide_index=True)


def section_fitting_notes() -> None:
    tech_pack = st.session_state.tech_pack
    if not tech_pack.get("style_number"):
        st.info("Generate a tech pack first.", icon="ℹ️")
        return

    tabs = st.tabs([f"Fitting Room  {LIVE_BADGE}", f"Paste Notes  {LIVE_BADGE}"])
    with tabs[0]:
        _render_fitting_room_live(tech_pack)
    with tabs[1]:
        _render_paste_notes_tab(tech_pack)


def section_send_to_factory() -> None:
    tech_pack = st.session_state.tech_pack
    factories = load_factories()
    if not factories:
        st.error("No factories loaded — check factory_contacts.json.")
        return

    factory_names = [f["factory_name"] for f in factories]
    factory_idx = st.selectbox(
        "Factory",
        options=range(len(factory_names)),
        format_func=lambda i: factory_names[i],
        key="factory_select",
    )
    factory = factories[factory_idx]

    contact_options = factory.get("contacts", [])
    contact_idx = st.selectbox(
        "Contact",
        options=range(len(contact_options)),
        format_func=lambda i: f"{contact_options[i]['name']} — {contact_options[i]['title']}",
        key="contact_select",
    )
    contact = contact_options[contact_idx]
    st.caption(
        f"Intended recipient: **{contact['email']}** "
        f"(will be redirected to TEST_EMAIL_RECIPIENT)"
    )

    default_subject = (
        f"[SpecBot] {tech_pack.get('sample_stage', DEFAULT_STAGE)} tech pack — "
        f"{tech_pack.get('style_number') or 'DRAFT'} {tech_pack.get('style_name') or ''}"
    ).strip()
    default_body = (
        f"Hi {contact['name']},\n\n"
        f"Please find attached the tech pack for style "
        f"{tech_pack.get('style_number')} — {tech_pack.get('style_name')} "
        f"({tech_pack.get('sample_stage', DEFAULT_STAGE)} stage).\n\n"
        f"Garment type: {tech_pack.get('garment_type')}\n"
        f"Fabric: {tech_pack.get('fabric')}\n"
        f"Sample size: {tech_pack.get('sample_size')}\n\n"
        "Please review the measurement table and confirm sample lead time.\n\n"
        "Thanks,\nSpecBot demo"
    )

    fitting_draft_body = st.session_state.get("fitting_draft_body") or ""
    fitting_draft_subject = st.session_state.get("fitting_draft_subject") or ""
    if fitting_draft_body:
        if st.checkbox(
            "Use fitting-room draft as the email body",
            key="use_fitting_draft",
            value=False,
        ):
            default_subject = fitting_draft_subject or default_subject
            default_body = fitting_draft_body

    subject = st.text_input("Email subject", value=default_subject, key="email_subject")
    body = st.text_area("Email body", value=default_body, height=180, key="email_body")

    if st.button("Send Test Email", type="primary", key="send_email_btn"):
        if not tech_pack.get("style_number"):
            st.error("Generate a tech pack first.")
            return

        attachment = st.session_state.export_path
        if not attachment or not Path(attachment).is_file():
            with st.spinner("Exporting Excel before sending…"):
                try:
                    attachment = export_tech_pack_to_excel(tech_pack)
                    st.session_state.export_path = attachment
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Excel export failed: {exc}")
                    return

        with st.spinner("Sending test email…"):
            result = send_factory_email(
                to_email=contact["email"],
                subject=subject,
                body=body,
                attachment_path=attachment,
            )
        st.session_state.last_email_result = result

        if result.get("ok"):
            st.success(
                f"Test email sent via {result.get('transport')} to "
                f"{os.getenv('TEST_EMAIL_RECIPIENT')} (intended: {contact['email']})."
            )
            try:
                add_or_update_wip_record(
                    {
                        "style_number": tech_pack.get("style_number", ""),
                        "style_name": tech_pack.get("style_name", ""),
                        "sample_stage": tech_pack.get("sample_stage", DEFAULT_STAGE),
                        "factory_name": factory.get("factory_name", ""),
                        "contact_name": contact.get("name", ""),
                        "status": "Sent to Factory",
                        "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "tech_pack_file": Path(attachment).name if attachment else "",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                st.warning(f"Email sent but WIP record update failed: {exc}")
        else:
            st.error(f"Email failed: {result.get('error')}")

    with st.expander(f"Factory replies  {PREVIEW_BADGE}", expanded=False):
        _preview_banner(
            "Inbound factory comments will land here, threaded to the style + revision. "
            "Today this section is a placeholder."
        )


def section_wip_dashboard() -> None:
    records = load_wip_records()
    if not records:
        st.info("No WIP records yet. Send a tech pack to populate the dashboard.", icon="ℹ️")
        return

    df = pd.DataFrame(records)
    preferred = [
        "style_number",
        "style_name",
        "sample_stage",
        "factory_name",
        "contact_name",
        "status",
        "last_update",
        "tech_pack_file",
    ]
    columns = [c for c in preferred if c in df.columns] + [
        c for c in df.columns if c not in preferred
    ]
    st.dataframe(df[columns], use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title="SpecBot — AI Technical Designer",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _init_state()
    _inject_css()
    sidebar()
    _hero()
    _status_strip()

    nav = st.tabs(
        [
            f"Brand Library  {LIVE_BADGE}",
            "Style Setup",
            "Tech Pack",
            "Fitting",
            "Send to Factory",
            "WIP Dashboard",
        ]
    )
    with nav[0]:
        section_brand_library()
    with nav[1]:
        section_style_setup()
    with nav[2]:
        section_tech_pack_preview()
    with nav[3]:
        section_fitting_notes()
    with nav[4]:
        section_send_to_factory()
    with nav[5]:
        section_wip_dashboard()

    st.divider()
    st.caption(
        "Demo only — outbound emails are routed to TEST_EMAIL_RECIPIENT, not real factories. "
        "Generated measurements are draft suggestions and must be reviewed by a technical designer."
    )


if __name__ == "__main__":
    main()
