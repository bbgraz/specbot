"""SpecBot AI Technical Designer — single-page Streamlit demo."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from email_sender import send_factory_email
from excel_exporter import export_tech_pack_to_excel
from fit_update_service import apply_fitting_notes
from mock_data import (
    CONSTRUCTION_ZONES,
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
    MOCK_FITTING_DRAFT_BODY,
    MOCK_FITTING_DRAFT_SUBJECT,
    MOCK_FITTING_PINNED_PHOTOS,
    MOCK_FITTING_STRUCTURED_UPDATES,
    MOCK_FITTING_TRANSCRIPT,
    MOCK_REVISIONS,
    MOCK_SKETCH_ANNOTATIONS,
    SAMPLE_STAGES,
    build_graded_table,
    get_grounding_report,
)
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

    return {
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


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


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


def section_header() -> None:
    st.title("SpecBot AI Technical Designer")
    st.caption(
        "Turn sketches and fitting notes into factory-ready tech packs in minutes."
    )
    if not os.getenv("OPENAI_API_KEY"):
        st.warning(
            "OPENAI_API_KEY is not set. Tech-pack generation will fail; fitting-note "
            "updates will fall back to a small rule-based parser.",
            icon="⚠️",
        )


def section_brand_library() -> None:
    st.header(f"1. Brand Library  {PREVIEW_BADGE}")
    st.markdown(
        f"**This is what the AI knows about {MOCK_BRAND_NAME}.** Without this layer, "
        "every tech pack is a generic guess. SpecBot syncs from the brand's existing "
        "system of record — PLM, Drive folders, CSV exports — and uses it to ground "
        "every AI generation. **We don't replace the system of record. We're the AI "
        "layer that sits on top of it.**"
    )
    _preview_banner(
        "Today this view shows static demo data. Production version syncs nightly from "
        "Centric / Backbone / FlexPLM, or from a Google Drive / SharePoint folder of CSVs. "
        "The brand never maintains the library inside SpecBot."
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


def section_style_setup() -> None:
    st.header("2. Style setup")
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

    try:
        from gpt_service import analyze_sketch
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not import GPT service: {exc}")
        return

    with st.spinner("Analyzing sketch and drafting tech pack…"):
        try:
            analysis = analyze_sketch(upload, metadata)
        except Exception as exc:  # noqa: BLE001
            st.error(f"GPT call failed: {exc}")
            return

    st.session_state.tech_pack = _to_tech_pack(analysis, metadata)
    st.session_state.export_path = None
    st.success("Draft tech pack generated. Review below.")


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
    """Show what the AI WOULD report if connected to the brand library."""
    report = get_grounding_report(tech_pack.get("garment_type", ""))
    with st.container(border=True):
        st.markdown(f"#### Brand grounding report  {PREVIEW_BADGE}")
        st.caption(
            "When the brand library is wired up, every AI generation produces this card. "
            "Below is what the report **would say** for this style, based on the demo brand library."
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
    tech_pack["measurements"] = _df_to_measurements(edited)


def _tab_grading(tech_pack: dict[str, Any]) -> None:
    _preview_banner(
        "Apply your brand's grade rules to fan a sample-size POM table out across the full size run. "
        "The table below uses generic default rules; replace with your house grade rules to enable."
    )
    measurements = tech_pack.get("measurements", []) or []
    if not measurements:
        st.caption("No measurements to grade yet.")
        return
    sample_size = tech_pack.get("sample_size") or "M"
    rows = build_graded_table(measurements, sample_size=sample_size, size_run=DEFAULT_SIZE_RUN)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(
        f"Grade rules below are defaults (chest 1.0\", body length 0.5\", sleeve 0.25\", etc.). "
        f"Sample size **{sample_size}** is the anchor row."
    )


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
    tech_pack["construction_notes"] = _df_to_construction(edited)


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
    _preview_banner(
        "Numbered callouts pinned to the sketch (like '1: French seam at side'). "
        "Drag-to-pin and freehand markup are on the roadmap. Today this tab shows static demo callouts."
    )
    df = pd.DataFrame(MOCK_SKETCH_ANNOTATIONS)
    df.columns = ["#", "Zone", "Callout"]
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.button("Add callout", disabled=True, help="Preview only.")


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
    st.header("3. Generated tech pack preview")
    tech_pack = st.session_state.tech_pack
    if not tech_pack.get("style_number") and not tech_pack.get("garment_summary"):
        st.info("Generate a tech pack to see the preview.", icon="ℹ️")
        return

    tab_labels = [
        "Overview",
        f"Measurements  {LIVE_BADGE}",
        f"Grading  {PREVIEW_BADGE}",
        f"Construction  {LIVE_BADGE}",
        f"BOM  {LIVE_BADGE}",
        f"Costing  {PREVIEW_BADGE}",
        f"Colorways  {PREVIEW_BADGE}",
        f"Annotations  {PREVIEW_BADGE}",
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


def _render_fitting_room_preview(tech_pack: dict[str, Any]) -> None:
    st.markdown(
        "**The home-run flow.** Voice + photo capture during the fit session, "
        "structured into POM updates, photo callouts, and a draft factory comment "
        "**before the TD leaves the room**. Designed mobile-first for iPad / phone."
    )
    _preview_banner(
        "Voice transcription, photo-to-zone pinning, and structured POM extraction "
        "are the next major build. Click 'Play demo session' below to see the experience."
    )

    cols = st.columns([1, 1, 1, 2])
    cols[0].button("● Record", disabled=True, help="Mic capture — preview only.")
    cols[1].button("📷 Pin photo", disabled=True, help="Photo-to-zone pinning — preview only.")
    play = cols[2].button("▶ Play demo session", key="play_fitting_demo")

    if play:
        st.session_state.fitting_demo_played = True
    if not st.session_state.get("fitting_demo_played"):
        st.caption(
            "Tap **Play demo session** to walk through the full Fit 2 capture: "
            "voice transcript → AI-structured POM updates → pinned photos → drafted factory comment."
        )
        return

    st.divider()
    st.markdown("##### 1 · Live transcript")
    st.code(MOCK_FITTING_TRANSCRIPT, language="text")

    st.markdown("##### 2 · AI-structured POM updates")
    st.dataframe(
        pd.DataFrame(MOCK_FITTING_STRUCTURED_UPDATES),
        use_container_width=True,
        hide_index=True,
    )
    cols_2 = st.columns([1, 1, 4])
    cols_2[0].button("Apply all to tech pack", disabled=True, help="Functional in next build.")
    cols_2[1].button("Edit before applying", disabled=True, help="Functional in next build.")

    st.markdown("##### 3 · Pinned photos (anchored to construction zones)")
    st.dataframe(
        pd.DataFrame(MOCK_FITTING_PINNED_PHOTOS),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("##### 4 · Drafted factory comment")
    st.text_input(
        "Subject",
        value=MOCK_FITTING_DRAFT_SUBJECT,
        key="fitting_draft_subject",
        disabled=True,
    )
    st.text_area(
        "Body",
        value=MOCK_FITTING_DRAFT_BODY,
        height=260,
        key="fitting_draft_body",
        disabled=True,
    )
    cols_3 = st.columns([1, 1, 4])
    cols_3[0].button("Send draft to factory", disabled=True, help="Functional in next build.")
    cols_3[1].button("Save as Rev 3", disabled=True, help="Functional in next build.")


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

    tech_pack = st.session_state.tech_pack

    st.subheader("Change log")
    st.dataframe(_change_log_df(tech_pack), use_container_width=True, hide_index=True)

    st.subheader("Revised measurements")
    st.dataframe(_measurements_df(tech_pack), use_container_width=True, hide_index=True)


def section_fitting_notes() -> None:
    st.header("4. Fitting")
    tech_pack = st.session_state.tech_pack
    if not tech_pack.get("style_number"):
        st.info("Generate a tech pack first.", icon="ℹ️")
        return

    tabs = st.tabs([f"Fitting Room  {PREVIEW_BADGE}", f"Paste Notes  {LIVE_BADGE}"])
    with tabs[0]:
        _render_fitting_room_preview(tech_pack)
    with tabs[1]:
        _render_paste_notes_tab(tech_pack)


def section_send_to_factory() -> None:
    st.header("5. Send to factory")
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
    st.header("6. WIP dashboard")
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
    st.set_page_config(page_title="SpecBot AI Technical Designer", layout="wide")
    _init_state()
    sidebar()
    section_header()
    section_brand_library()
    section_style_setup()
    section_tech_pack_preview()
    section_fitting_notes()
    section_send_to_factory()
    section_wip_dashboard()
    st.divider()
    st.caption(
        "Demo only — outbound emails are routed to TEST_EMAIL_RECIPIENT, not real factories. "
        "Generated measurements are draft suggestions and must be reviewed by a technical designer."
    )


if __name__ == "__main__":
    main()
