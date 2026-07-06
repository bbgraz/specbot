"""SpecBot AI Technical Designer — single-page Streamlit demo."""

from __future__ import annotations

import base64
import copy
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
    NUMERIC_SIZE_RUN,
    SAMPLE_STAGES,
    build_graded_table,
)
from tech_pack_store import (
    delete_tech_pack,
    list_tech_packs,
    load_tech_pack,
    save_tech_pack,
)
from spec_blocks import build_offline_draft, match_category
from wip_store import (
    add_or_update_wip_record,
    ensure_wip_record,
    load_wip_records,
    mark_milestone_done,
    set_wip_milestones,
)

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
        "style_description": "",
        "garment_summary": "",
        "detected_features": [],
        "measurements": [],
        "original_measurements": [],
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
                "quantity": item.get("quantity", ""),
                "uom": item.get("uom", ""),
                "supplier": item.get("supplier", ""),
                "color": item.get("color", ""),
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
        "original_measurements": copy.deepcopy(measurements),
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


_BOM_COLUMNS = [
    "component", "material", "placement", "quantity", "uom",
    "supplier", "color", "notes", "source",
]


def _bom_df(tech_pack: dict[str, Any]) -> pd.DataFrame:
    rows = [
        {col: r.get(col, "") for col in _BOM_COLUMNS}
        for r in tech_pack.get("bom", [])
    ]
    if not rows:
        return pd.DataFrame(columns=_BOM_COLUMNS)
    return pd.DataFrame(rows, columns=_BOM_COLUMNS)


def _df_to_bom(df: pd.DataFrame) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        item = {col: str(row.get(col, "") or "").strip() for col in _BOM_COLUMNS}
        if any(item.values()):
            out.append(item)
    return out


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


# ---------------------------------------------------------------------------
# Workflow navigation — the app follows the tech-designer process:
# Intake → Tech Pack → Fit & Revise → Send to Factory → WIP Board.
# ---------------------------------------------------------------------------

WORKFLOW_STAGES: list[tuple[str, str]] = [
    ("intake", "① Styles"),
    ("techpack", "② Tech Pack"),
    ("fit", "③ Fit & Revise"),
    ("send", "④ Send to Factory"),
    ("wip", "⑤ WIP Board"),
    ("library", "📚 Brand Library"),
]
_STAGE_LABELS = dict(WORKFLOW_STAGES)


_PROCESS_ORDER = ["intake", "techpack", "fit", "send", "wip"]
_GATED_STAGES = ("techpack", "fit", "send")


def _go(stage: str) -> None:
    """Navigate to a workflow stage on the next rerun (safe for widget state)."""
    st.session_state._pending_nav = stage
    st.rerun()


def _style_progress() -> dict[str, bool]:
    """What's done for the current style — drives stepper checkmarks."""
    tp = st.session_state.tech_pack
    has_style = bool(tp.get("style_number"))
    sent = False
    if has_style:
        for record in load_wip_records():
            if record.get("style_number") == tp.get("style_number"):
                sent = record.get("status") == "Sent to Factory"
                break
    return {
        "intake": has_style,
        "techpack": has_style,
        "fit": bool(tp.get("measurement_history")),
        "send": sent,
        "wip": sent,
    }


def _stepper() -> None:
    """Always-visible workflow stepper on the main canvas — click any stage,
    forward or back. Gated stages are disabled until a style is loaded."""
    current = st.session_state.get("nav_stage", "intake")
    has_style = bool(st.session_state.tech_pack.get("style_number"))
    done = _style_progress()

    cols = st.columns(len(WORKFLOW_STAGES))
    for col, (key, label) in zip(cols, WORKFLOW_STAGES):
        gated = key in _GATED_STAGES and not has_style
        display = f"✓ {label[1:].strip()}" if done.get(key) and key != current else label
        with col:
            if st.button(
                display,
                key=f"nav_btn_{key}",
                type="primary" if key == current else "secondary",
                disabled=gated,
                use_container_width=True,
                help="Load or generate a style first." if gated else None,
            ):
                if key != current:
                    _go(key)


def _stage_footer_nav(stage: str) -> None:
    """Uniform ← Back / Next → controls at the bottom of every process stage."""
    if stage not in _PROCESS_ORDER:
        return
    idx = _PROCESS_ORDER.index(stage)
    has_style = bool(st.session_state.tech_pack.get("style_number"))
    st.divider()
    cols = st.columns([2, 3, 2])
    if idx > 0:
        prev = _PROCESS_ORDER[idx - 1]
        with cols[0]:
            if st.button(f"← Back to {_STAGE_LABELS[prev]}", key=f"back_btn_{stage}"):
                _go(prev)
    if idx < len(_PROCESS_ORDER) - 1:
        nxt = _PROCESS_ORDER[idx + 1]
        gated = nxt in _GATED_STAGES and not has_style
        with cols[2]:
            if st.button(
                f"Next: {_STAGE_LABELS[nxt]} →",
                key=f"next_btn_{stage}",
                type="primary",
                disabled=gated,
            ):
                _go(nxt)


def _flash(level: str, message: str) -> None:
    """Queue a message that survives the rerun caused by navigation."""
    st.session_state.setdefault("_flashes", []).append((level, message))


def _render_flashes() -> None:
    for level, message in st.session_state.pop("_flashes", []) or []:
        getattr(st, level, st.info)(message)


def _persist_current_tech_pack() -> None:
    """Save the currently-loaded tech pack to disk; swallow errors quietly."""
    tp = st.session_state.get("tech_pack") or {}
    if not tp.get("style_number"):
        return
    try:
        save_tech_pack(tp)
    except Exception:  # noqa: BLE001
        pass
    try:
        ensure_wip_record(
            {
                "style_number": tp.get("style_number", ""),
                "style_name": tp.get("style_name", ""),
                "sample_stage": tp.get("sample_stage", DEFAULT_STAGE),
                "garment_type": tp.get("garment_type", ""),
            }
        )
    except Exception:  # noqa: BLE001
        pass


def _attach_sketch_to_tech_pack(tp: dict[str, Any]) -> None:
    """Persist the working sketch on the tech pack so it survives reloads."""
    data = st.session_state.get("uploaded_sketch_bytes")
    if data:
        tp["sketch_b64"] = _b64(data)
        tp["sketch_mime"] = st.session_state.get("uploaded_sketch_mime") or "image/png"


def _restore_sketch_from_tech_pack(tp: dict[str, Any]) -> None:
    data = _from_b64(tp.get("sketch_b64") or "")
    st.session_state.uploaded_sketch_bytes = data or None
    st.session_state.uploaded_sketch_mime = tp.get("sketch_mime") if data else None


def _push_undo_snapshot() -> None:
    """Push the current tech pack onto the undo stack (max 20) and clear redo."""
    stack = st.session_state.setdefault("undo_stack", [])
    stack.append(copy.deepcopy(st.session_state.tech_pack))
    del stack[:-20]
    st.session_state.redo_stack = []


def _bump_editor_epoch() -> None:
    """Force data editors to rebuild from the restored tech pack state."""
    st.session_state.editor_epoch = int(st.session_state.get("editor_epoch", 0)) + 1


def _original_measurements(tp: dict[str, Any]) -> list[dict[str, Any]]:
    original = tp.get("original_measurements")
    if original:
        return original
    history = tp.get("measurement_history") or []
    if history:
        return history[0].get("measurements") or []
    return []


def _render_undo_controls(prefix: str) -> None:
    """Multi-step Undo / Redo plus reset-to-original-draft measurements."""
    tp = st.session_state.tech_pack
    if not tp.get("style_number"):
        return
    undo_stack = st.session_state.get("undo_stack") or []
    redo_stack = st.session_state.get("redo_stack") or []
    original = _original_measurements(tp)

    cols = st.columns([1, 1, 2.2, 3])
    if cols[0].button(
        f"↩ Undo ({len(undo_stack)})",
        key=f"{prefix}_undo_btn",
        disabled=not undo_stack,
        help="Step back through applied changes (up to 20 steps).",
    ):
        st.session_state.setdefault("redo_stack", []).append(copy.deepcopy(tp))
        st.session_state.tech_pack = st.session_state.undo_stack.pop()
        st.session_state.pending_fit = None
        _bump_editor_epoch()
        _persist_current_tech_pack()
        st.rerun()
    if cols[1].button(
        f"↪ Redo ({len(redo_stack)})",
        key=f"{prefix}_redo_btn",
        disabled=not redo_stack,
        help="Step forward again after an undo.",
    ):
        st.session_state.setdefault("undo_stack", []).append(copy.deepcopy(tp))
        st.session_state.tech_pack = st.session_state.redo_stack.pop()
        st.session_state.pending_fit = None
        _bump_editor_epoch()
        _persist_current_tech_pack()
        st.rerun()
    if cols[2].button(
        "⟲ Reset to original measurements",
        key=f"{prefix}_reset_btn",
        disabled=not original,
        help=(
            "Reverts every measurement to the first generated draft. "
            "The reset itself is undoable and is recorded in the change log."
        ),
    ):
        from fit_update_service import _add_change_log

        _push_undo_snapshot()
        tp = st.session_state.tech_pack
        tp["measurements"] = copy.deepcopy(original)
        _add_change_log(
            tp,
            "(all POMs)",
            "measurements",
            "current values",
            "original draft values",
            "Reset to original measurements",
        )
        tp["change_log"][-1]["stage"] = tp.get("sample_stage", DEFAULT_STAGE)
        st.session_state.pending_fit = None
        _bump_editor_epoch()
        _persist_current_tech_pack()
        st.rerun()


def _commit_fit_revision(old_tp: dict[str, Any], revised: dict[str, Any], stage: str) -> None:
    """Commit an approved fit revision: bump rev, snapshot prior measurements,
    stamp the stage on new change-log entries, persist."""
    _push_undo_snapshot()
    _bump_editor_epoch()
    prev_rev = int(old_tp.get("rev") or 0)
    revised["rev"] = prev_rev + 1
    revised["sample_stage"] = stage
    history = list(old_tp.get("measurement_history") or [])
    history.append(
        {
            "rev": prev_rev,
            "stage": old_tp.get("sample_stage", ""),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "measurements": copy.deepcopy(old_tp.get("measurements", [])),
        }
    )
    revised["measurement_history"] = history
    for entry in revised.get("change_log", [])[len(old_tp.get("change_log", [])) :]:
        entry.setdefault("stage", stage)
    st.session_state.tech_pack = revised
    st.session_state.export_path = None
    _persist_current_tech_pack()


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def _init_state() -> None:
    st.session_state.setdefault("tech_pack", _empty_tech_pack())
    st.session_state.setdefault("export_path", None)
    st.session_state.setdefault("last_email_result", None)
    st.session_state.setdefault("last_fitting_summary", None)
    st.session_state.setdefault("pending_fit", None)
    st.session_state.setdefault("pasted_sketch_bytes", None)
    st.session_state.setdefault("pasted_sketch_mime", None)
    st.session_state.setdefault("_flashes", [])
    st.session_state.setdefault("undo_stack", [])
    st.session_state.setdefault("redo_stack", [])
    st.session_state.setdefault("editor_epoch", 0)
    # Persist intake-form values across stage navigation. The self-assignment
    # marks the keys as app-managed so Streamlit's widget cleanup doesn't drop
    # them when the Intake stage isn't rendered.
    for k in (
        "form_style_name",
        "form_style_number",
        "form_garment_type",
        "form_fabric",
        "form_sample_size",
        "form_style_description",
    ):
        st.session_state[k] = st.session_state.get(k, "")
    st.session_state.form_sample_stage = st.session_state.get("form_sample_stage", DEFAULT_STAGE)
    st.session_state.camera_enable = st.session_state.get("camera_enable", False)
    # Keep-alive for stage-local widgets whose state must survive navigating
    # to another stage (Streamlit drops widget keys that don't render).
    for _k in ("grading_size_run", "fitting_stage_select", "use_fitting_draft"):
        if _k in st.session_state:
            st.session_state[_k] = st.session_state[_k]
    # Apply queued navigation BEFORE the nav widget is instantiated.
    if st.session_state.get("_pending_nav"):
        st.session_state.nav_stage = st.session_state.pop("_pending_nav")
    st.session_state.setdefault("nav_stage", "intake")
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


def _render_saved_styles(key_prefix: str = "sidebar") -> None:
    saved = list_tech_packs()
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
        key=f"{key_prefix}_open_saved",
    )
    if choice and choice != "—":
        idx = options.index(choice) - 1
        target = saved[idx]
        cols = st.columns(2)
        if cols[0].button("Load", key=f"{key_prefix}_load_btn", use_container_width=True):
            loaded = load_tech_pack(target["style_number"])
            if loaded:
                st.session_state.tech_pack = {**_empty_tech_pack(), **loaded}
                st.session_state.export_path = None
                st.session_state.undo_stack, st.session_state.redo_stack = [], []
                _restore_sketch_from_tech_pack(st.session_state.tech_pack)
                _flash("success", f"Loaded {target['style_number']} — continue where you left off.")
                _go("techpack")
            else:
                st.error("Could not load that tech pack.")
        if cols[1].button("Delete", key=f"{key_prefix}_delete_btn", use_container_width=True):
            if delete_tech_pack(target["style_number"]):
                st.success(f"Deleted {target['style_number']}.")
                st.rerun()
            else:
                st.error("Delete failed.")


def _sidebar_saved_styles() -> None:
    st.markdown("### Saved styles")
    _render_saved_styles("sidebar")


def sidebar() -> None:
    tech_pack = st.session_state.tech_pack
    with st.sidebar:
        st.markdown("### Current style")
        if tech_pack.get("style_number"):
            st.markdown(
                f"**{tech_pack.get('style_number')}** · {tech_pack.get('style_name') or '(no name)'}"
            )
            st.caption(
                f"Rev **{tech_pack.get('rev', 0)}** · Stage **{tech_pack.get('sample_stage', DEFAULT_STAGE)}**  ·  "
                f"{tech_pack.get('garment_type') or '—'} · size {tech_pack.get('sample_size') or '—'}"
            )
        else:
            st.caption("No style loaded — start at ① Styles.")

        st.divider()
        _sidebar_saved_styles()

        with st.expander("Feature roadmap"):
            live = [r for r in FEATURE_ROADMAP if r["status"] == "live"]
            preview = [r for r in FEATURE_ROADMAP if r["status"] == "preview"]
            st.markdown(f"**{LIVE_BADGE} ({len(live)})**")
            for r in live:
                st.markdown(f"- {r['feature']}")
            st.markdown(f"**{PREVIEW_BADGE} ({len(preview)})**")
            for r in preview:
                st.markdown(f"- {r['feature']}")

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
        header[data-testid="stHeader"] { background: transparent; }

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


def _status_strip() -> None:
    """Persistent style-context strip: identity + where it sits in the process."""
    tech_pack = st.session_state.tech_pack
    if not tech_pack.get("style_number"):
        return
    style_no = tech_pack.get("style_number") or "(no #)"
    style_name = tech_pack.get("style_name") or "(no name)"
    stage = tech_pack.get("sample_stage", DEFAULT_STAGE)
    garment = tech_pack.get("garment_type") or "—"
    sample_size = tech_pack.get("sample_size") or "—"
    rev = tech_pack.get("rev", 0)
    fit_rounds = len(tech_pack.get("measurement_history") or [])

    sent = False
    for record in load_wip_records():
        if record.get("style_number") == tech_pack.get("style_number"):
            sent = record.get("status") == "Sent to Factory"
            break
    progress = (
        "Draft ✓ · "
        + (f"Fit rounds: {fit_rounds}" if fit_rounds else "No fit rounds yet")
        + (" · Sent to factory ✓" if sent else "")
    )

    st.markdown(
        f"""
        <div class="specbot-status-strip">
          <div><span class="label">Style</span><span class="pill">{style_no}</span></div>
          <div><span class="label">Name</span><span class="pill">{style_name}</span></div>
          <div><span class="label">Type</span><span class="pill">{garment}</span></div>
          <div><span class="label">Size</span><span class="pill">{sample_size}</span></div>
          <div><span class="label">Stage</span><span class="pill">{stage}</span></div>
          <div><span class="label">Rev</span><span class="pill">{rev}</span></div>
          <div><span class="label">Progress</span><span class="pill">{progress}</span></div>
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
    st.session_state.undo_stack, st.session_state.redo_stack = [], []
    st.session_state.uploaded_sketch_bytes = None
    st.session_state.uploaded_sketch_mime = None


def _render_alt_sketch_inputs() -> None:
    """Paste-from-clipboard and camera capture as alternatives to file upload.

    Whichever source was used most recently lands in
    st.session_state.pasted_sketch_bytes and is picked up at generation time
    when no file is uploaded.
    """
    with st.expander("No file? Paste a screenshot or photograph the sketch"):
        cols = st.columns(2)
        with cols[0]:
            try:
                from streamlit_paste_button import paste_image_button

                result = paste_image_button(
                    "📋 Paste sketch from clipboard", key="paste_sketch_btn"
                )
                if getattr(result, "image_data", None) is not None:
                    import io as _io

                    buf = _io.BytesIO()
                    result.image_data.convert("RGB").save(buf, format="PNG")
                    st.session_state.pasted_sketch_bytes = buf.getvalue()
                    st.session_state.pasted_sketch_mime = "image/png"
            except Exception:  # noqa: BLE001 - component optional; never block setup
                st.caption(
                    "Clipboard paste unavailable in this browser — use upload or camera."
                )
        with cols[1]:
            # The camera widget activates the webcam the moment it renders,
            # so only instantiate it after an explicit opt-in.
            use_camera = st.toggle(
                "📷 Use camera to photograph a sketch", key="camera_enable"
            )
            if use_camera:
                snap = st.camera_input("Snap a paper sketch", key="camera_sketch")
                if snap is not None:
                    st.session_state.pasted_sketch_bytes = snap.getvalue()
                    st.session_state.pasted_sketch_mime = snap.type or "image/jpeg"
        if st.session_state.get("pasted_sketch_bytes"):
            st.image(
                st.session_state.pasted_sketch_bytes,
                caption="Captured sketch — will be used if no file is uploaded above.",
                width=260,
            )
            if st.button("Clear captured sketch", key="clear_pasted_sketch"):
                st.session_state.pasted_sketch_bytes = None
                st.session_state.pasted_sketch_mime = None
                st.rerun()


class _MemorySketch:
    """Duck-typed stand-in for a Streamlit UploadedFile (has .read/.type/.name)."""

    def __init__(self, data: bytes, mime: str, name: str = "pasted_sketch.png"):
        self._data = data
        self.type = mime
        self.name = name

    def read(self) -> bytes:
        return self._data

    def getvalue(self) -> bytes:
        return self._data


def _render_style_archive() -> None:
    """First-class archive of every generated tech pack — open, duplicate, delete."""
    saved = list_tech_packs()
    if not saved:
        st.info(
            "No saved tech packs yet. Every generated style is auto-saved here — "
            "start one in the **New Style** tab."
        )
        return

    st.caption(
        "Every tech pack is auto-saved as you work. **Open** one to continue exactly "
        "where you left off — measurements, fit history, change log, everything."
    )
    header = st.columns([2, 3, 2, 1.2, 1, 2, 1.2, 1.4, 1.2])
    for col, title in zip(header, ["Style #", "Name", "Type", "Stage", "Rev", "Last saved", "", "", ""]):
        col.markdown(f"**{title}**" if title else "")
    for i, s in enumerate(saved):
        cols = st.columns([2, 3, 2, 1.2, 1, 2, 1.2, 1.4, 1.2])
        cols[0].markdown(s.get("style_number") or "—")
        cols[1].markdown(s.get("style_name") or "—")
        cols[2].markdown(s.get("garment_type") or "—")
        cols[3].markdown(s.get("sample_stage") or "—")
        cols[4].markdown(str(s.get("rev", 0)))
        cols[5].caption(s.get("saved_at") or "—")
        if cols[6].button("Open", key=f"arch_open_{i}", type="primary"):
            loaded = load_tech_pack(s["style_number"])
            if loaded:
                st.session_state.tech_pack = {**_empty_tech_pack(), **loaded}
                st.session_state.export_path = None
                st.session_state.undo_stack, st.session_state.redo_stack = [], []
                _restore_sketch_from_tech_pack(st.session_state.tech_pack)
                _flash("success", f"Opened {s['style_number']} — continue where you left off.")
                _go("techpack")
            else:
                st.error("Could not load that tech pack.")
        if cols[7].button("Duplicate", key=f"arch_dup_{i}"):
            loaded = load_tech_pack(s["style_number"])
            if loaded:
                dup = copy.deepcopy(loaded)
                existing = {r.get("style_number") for r in list_tech_packs()}
                base = f"{s['style_number']}-COPY"
                new_number, n = base, 2
                while new_number in existing:
                    new_number, n = f"{base}{n}", n + 1
                dup["style_number"] = new_number
                dup.pop("_saved_at", None)
                dup.setdefault("change_log", []).append(
                    {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "stage": dup.get("sample_stage", DEFAULT_STAGE),
                        "pom": "(style)",
                        "field": "style_number",
                        "old_value": s["style_number"],
                        "new_value": new_number,
                        "reason": f"Duplicated from {s['style_number']}",
                    }
                )
                st.session_state.tech_pack = {**_empty_tech_pack(), **dup}
                st.session_state.export_path = None
                st.session_state.undo_stack, st.session_state.redo_stack = [], []
                _restore_sketch_from_tech_pack(st.session_state.tech_pack)
                _persist_current_tech_pack()
                _flash("success", f"Duplicated {s['style_number']} as {new_number}.")
                _go("techpack")
            else:
                st.error("Could not load that tech pack.")
        if cols[8].button("Delete", key=f"arch_del_{i}"):
            if delete_tech_pack(s["style_number"]):
                st.rerun()
            else:
                st.error("Delete failed.")


def section_style_setup() -> None:
    saved_count = len(list_tech_packs())
    tab_new, tab_archive = st.tabs(["Start New Style", f"Style Archive ({saved_count})"])
    with tab_archive:
        _render_style_archive()
    with tab_new:
        _render_new_style_form()


def _render_new_style_form() -> None:
    st.markdown(
        "Drop a sketch, add the style basics, generate — you'll land on the "
        "**② Tech Pack** stage to review and edit the draft."
    )
    if not os.getenv("OPENAI_API_KEY"):
        st.caption(
            "⚠️ No OPENAI_API_KEY set — generation runs offline from the "
            "category-standard spec block (sketch won't be analyzed)."
        )
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

        style_description = st.text_area(
            "Design intent / style description (optional — treated as designer-stated fact)",
            placeholder=(
                "e.g. Oversized boxy fit with dropped shoulders, heavyweight fleece, "
                "raw-edge hems. Like our FW24 crew but 2\" longer, kangaroo pocket."
            ),
            height=90,
            key="form_style_description",
        )

        submitted = st.form_submit_button("Generate Tech Pack", type="primary")

    _render_alt_sketch_inputs()

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
        _flash(
            "success",
            "Demo tech pack loaded (offline draft from the category-standard spec block). "
            "Review it below, then move on to ③ Fit & Revise.",
        )
        _go("techpack")
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
        "style_description": (style_description or "").strip(),
    }

    # Sketch source priority: uploaded file, else pasted/camera capture.
    if upload is None and st.session_state.get("pasted_sketch_bytes"):
        upload = _MemorySketch(
            st.session_state.pasted_sketch_bytes,
            st.session_state.get("pasted_sketch_mime") or "image/png",
        )

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
        _attach_sketch_to_tech_pack(st.session_state.tech_pack)
        st.session_state.undo_stack, st.session_state.redo_stack = [], []
        st.session_state.export_path = None
        _flash(
            "warning",
            "No OPENAI_API_KEY configured — generated an offline draft from the "
            "category-standard spec block instead. The sketch was NOT analyzed. "
            "Add an API key to .env for AI sketch analysis.",
        )
        _go("techpack")
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
            _flash(
                "success",
                "Draft tech pack generated and grounded against the brand library. "
                "Review below, then move on to ③ Fit & Revise.",
            )
        except Exception as exc:  # noqa: BLE001
            analysis = build_offline_draft(metadata)
            _flash(
                "warning",
                f"GPT call failed ({exc}). Generated an offline draft from the "
                "category-standard spec block instead — the sketch was NOT analyzed.",
            )

    analysis["grounding_report"] = report
    tech_pack = _to_tech_pack(analysis, metadata)
    _attach_sketch_to_tech_pack(tech_pack)
    st.session_state.tech_pack = tech_pack
    st.session_state.undo_stack, st.session_state.redo_stack = [], []
    st.session_state.export_path = None
    try:
        save_tech_pack(tech_pack)
    except Exception as exc:  # noqa: BLE001
        _flash("warning", f"Generated, but local save failed: {exc}")
    _go("techpack")


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

        st.markdown("**POM diagram**")
        try:
            from spec_diagram import render_spec_diagram

            st.image(render_spec_diagram(tech_pack), use_container_width=True)
        except Exception as exc:  # noqa: BLE001
            st.caption(f"Diagram unavailable: {exc}")

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


def _log_manual_measurement_edits(
    tech_pack: dict[str, Any],
    old_rows: list[dict[str, Any]],
    new_rows: list[dict[str, Any]],
) -> int:
    """Change-log every manual measurement edit — no silent spec changes."""
    from fit_update_service import _add_change_log

    stage = tech_pack.get("sample_stage", DEFAULT_STAGE)
    old_by = {r.get("pom", ""): r for r in old_rows if r.get("pom")}
    new_by = {r.get("pom", ""): r for r in new_rows if r.get("pom")}
    fields = ["target", "tolerance_plus", "tolerance_minus", "description", "notes", "source"]
    count = 0
    for pom, new_r in new_by.items():
        old_r = old_by.get(pom)
        if old_r is None:
            _add_change_log(
                tech_pack, pom, "row", "(none)",
                f"target={new_r.get('target', '')}", "Manual edit — row added",
            )
            count += 1
            continue
        for field in fields:
            if str(old_r.get(field, "")) != str(new_r.get(field, "")):
                _add_change_log(
                    tech_pack, pom, field,
                    str(old_r.get(field, "")), str(new_r.get(field, "")),
                    "Manual edit (Measurements tab)",
                )
                count += 1
    for pom, old_r in old_by.items():
        if pom not in new_by:
            _add_change_log(
                tech_pack, pom, "row",
                f"target={old_r.get('target', '')}", "(deleted)", "Manual edit — row deleted",
            )
            count += 1
    if count:
        for entry in tech_pack.get("change_log", [])[-count:]:
            entry.setdefault("stage", stage)
    return count


def _tab_measurements(tech_pack: dict[str, Any]) -> None:
    _render_undo_controls("meas")
    with st.expander("POM diagram — numbers match the table rows", expanded=True):
        try:
            from spec_diagram import render_spec_diagram

            st.image(render_spec_diagram(tech_pack), width=560)
        except Exception as exc:  # noqa: BLE001
            st.caption(f"Diagram unavailable: {exc}")
    st.caption(
        f"{LIVE_BADGE}. Editable — every manual change is recorded in the change log. "
        "Source values control whether a row is AI-derived, inferred, a placeholder "
        "for review, or a fitting-session update."
    )
    edited = st.data_editor(
        _measurements_df(tech_pack),
        num_rows="dynamic",
        use_container_width=True,
        key=f"measurements_editor_{st.session_state.get('editor_epoch', 0)}",
        column_config={
            "source": st.column_config.SelectboxColumn(
                "source",
                options=[
                    "matched_from_brand_library",
                    "derived_from_input",
                    "inferred_from_standard_practice",
                    "placeholder_for_review",
                    "fitting_note",
                    "manual_edit",
                ],
            )
        },
    )
    new_rows = _df_to_measurements(edited)
    old_rows = tech_pack.get("measurements") or []
    if new_rows != old_rows:
        _push_undo_snapshot()
        logged = _log_manual_measurement_edits(tech_pack, old_rows, new_rows)
        tech_pack["measurements"] = new_rows
        _persist_current_tech_pack()
        if logged:
            st.toast(f"{logged} manual change(s) recorded in the change log.")


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
        key=f"grading_rules_editor_{st.session_state.get('editor_epoch', 0)}",
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
    category = match_category(tech_pack.get("garment_type") or "")
    default_run = "Numeric (28–38)" if category in ("pants", "shorts") else "Alpha (XS–XXL)"
    run_options = ["Alpha (XS–XXL)", "Numeric (28–38)"]
    run_choice = st.radio(
        "Size run",
        run_options,
        index=run_options.index(default_run),
        horizontal=True,
        key="grading_size_run",
        help="Bottoms grade on waist sizes; tops and dresses on alpha sizes.",
    )
    size_run = NUMERIC_SIZE_RUN if run_choice.startswith("Numeric") else DEFAULT_SIZE_RUN
    rows = build_graded_table(
        measurements,
        sample_size=sample_size,
        size_run=size_run,
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
        key=f"construction_editor_{st.session_state.get('editor_epoch', 0)}",
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
    st.caption(
        f"{LIVE_BADGE}. Self fabric, trims, labels, packaging — editable, with "
        "consumption, supplier, and color/DTM so the factory can cost and source."
    )
    edited = st.data_editor(
        _bom_df(tech_pack),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"bom_editor_{st.session_state.get('editor_epoch', 0)}",
        column_config={
            "component": st.column_config.TextColumn("Component"),
            "material": st.column_config.TextColumn("Material"),
            "placement": st.column_config.TextColumn("Placement"),
            "quantity": st.column_config.TextColumn("Qty/Consumption", help="e.g. 1.65 yd, 3 pcs"),
            "uom": st.column_config.TextColumn("UOM", help="yd, m, pcs, gross"),
            "supplier": st.column_config.TextColumn("Supplier / Article #"),
            "color": st.column_config.TextColumn("Color / DTM"),
            "notes": st.column_config.TextColumn("Notes"),
            "source": st.column_config.TextColumn("Source"),
        },
    )
    new_bom = _df_to_bom(edited)
    if new_bom != tech_pack.get("bom"):
        tech_pack["bom"] = new_bom
        _persist_current_tech_pack()


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
    history = tech_pack.get("measurement_history") or []
    if not history:
        _preview_banner(
            "Revision history appears here after the first applied fit round. "
            "The demo rows below show the intended shape."
        )
        df = pd.DataFrame(MOCK_REVISIONS)
        df.columns = ["Rev", "Date", "Author", "Stage", "Summary"]
        st.dataframe(df, use_container_width=True, hide_index=True)
        return

    st.caption(
        f"{LIVE_BADGE}. Current rev: **{tech_pack.get('rev', 0)}** "
        f"({tech_pack.get('sample_stage', '')}). Side-by-side vs the previous rev below."
    )
    rev_rows = [
        {
            "Rev": h.get("rev", i),
            "Stage": h.get("stage", ""),
            "Saved": h.get("timestamp", ""),
            "POMs": len(h.get("measurements", [])),
        }
        for i, h in enumerate(history)
    ]
    st.dataframe(pd.DataFrame(rev_rows), use_container_width=True, hide_index=True)

    prev = history[-1]
    prev_by_pom = {m.get("pom", ""): m.get("target", "") for m in prev.get("measurements", [])}
    diff_rows = []
    for m in tech_pack.get("measurements", []) or []:
        pom = m.get("pom", "")
        old_t = prev_by_pom.pop(pom, None)
        new_t = m.get("target", "")
        if old_t is None:
            diff_rows.append({"POM": pom, f"Rev {prev.get('rev', '')}": "(new row)", f"Rev {tech_pack.get('rev', 0)} (current)": new_t, "Δ": ""})
        elif str(old_t) != str(new_t):
            try:
                delta = f"{float(new_t) - float(old_t):+g}"
            except (TypeError, ValueError):
                delta = ""
            diff_rows.append({"POM": pom, f"Rev {prev.get('rev', '')}": old_t, f"Rev {tech_pack.get('rev', 0)} (current)": new_t, "Δ": delta})
    for pom, old_t in prev_by_pom.items():
        diff_rows.append({"POM": pom, f"Rev {prev.get('rev', '')}": old_t, f"Rev {tech_pack.get('rev', 0)} (current)": "(removed)", "Δ": ""})

    st.markdown(f"**Changed POMs — Rev {prev.get('rev', '')} → Rev {tech_pack.get('rev', 0)}**")
    if diff_rows:
        st.dataframe(pd.DataFrame(diff_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No measurement changes between the last two revs.")


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

    # Ordered the way a TD reviews a pack: what is it → spec → build → history.
    tab_labels = [
        "Overview",
        f"Measurements  {LIVE_BADGE}",
        f"Grading  {LIVE_BADGE}",
        f"Construction  {LIVE_BADGE}",
        f"BOM  {LIVE_BADGE}",
        f"Annotations  {LIVE_BADGE}",
        f"Revisions  {LIVE_BADGE}",
        f"Roadmap  {PREVIEW_BADGE}",
    ]
    tabs = st.tabs(tab_labels)
    with tabs[0]:
        _tab_overview(tech_pack)
        st.divider()
        _tab_assumptions(tech_pack)
    with tabs[1]:
        _tab_measurements(tech_pack)
    with tabs[2]:
        _tab_grading(tech_pack)
    with tabs[3]:
        _tab_construction(tech_pack)
    with tabs[4]:
        _tab_bom(tech_pack)
    with tabs[5]:
        _tab_annotations(tech_pack)
    with tabs[6]:
        _tab_revisions(tech_pack)
    with tabs[7]:
        st.markdown("#### Costing")
        _tab_costing(tech_pack)
        st.divider()
        st.markdown("#### Colorways")
        _tab_colorways(tech_pack)

    st.divider()
    cols = st.columns([1, 1, 4])
    with cols[0]:
        if st.button("Export Excel", key="export_btn"):
            try:
                path = export_tech_pack_to_excel(
                    tech_pack, sketch_bytes=st.session_state.get("uploaded_sketch_bytes")
                    or _from_b64(tech_pack.get("sketch_b64") or "")
                )
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
            revised["fit_photos"] = pinned
            _commit_fit_revision(
                tech_pack, revised, tech_pack.get("sample_stage", DEFAULT_STAGE)
            )
            st.session_state.fitting_change_count = len(new_entries)
            st.success(f"{len(new_entries)} change-log entries added from the transcript.")

    if st.session_state.get("fitting_change_count"):
        st.caption(
            f"{st.session_state['fitting_change_count']} updates applied from the most recent extraction. "
            "See the **Tech Pack → Measurements / Change Log** tabs for the full diff."
        )

    st.markdown("##### 4 · Hand off")
    st.caption(
        "Fit results are recorded on the tech pack (change log + revised measurements). "
        "Email drafting and sending live in the Send stage — no duplicate flows."
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

    if st.button("Preview Changes", key="preview_fitting_btn", type="primary"):
        if not notes.strip():
            st.warning("Enter fitting notes first.")
        else:
            with st.spinner("Parsing fitting notes…"):
                revised = apply_fitting_notes(tech_pack, notes)
            st.session_state.pending_fit = {
                "revised": revised,
                "stage": new_stage,
                "n_old": len(tech_pack.get("change_log", [])),
            }


def _render_revise_table_tab(tech_pack: dict[str, Any]) -> None:
    """Direct revision worksheet — no math, no notes. Type either the new
    target or a +/- delta per POM (fractions welcome) and preview."""
    from fit_update_service import _parse_amount

    st.caption(
        f"{LIVE_BADGE}. Type the **New target** (e.g. `21.5` or `21 1/2`) *or* a "
        "**Δ +/-** (e.g. `+1/4`, `-0.5`) for any POM — whichever you have in your "
        "head. Tolerances are editable too. Then preview and apply."
    )
    measurements = tech_pack.get("measurements", []) or []
    if not measurements:
        st.info("No measurements yet — generate a tech pack first.")
        return

    ctrl = st.columns([1, 2, 3])
    current_stage = tech_pack.get("sample_stage", DEFAULT_STAGE)
    with ctrl[0]:
        try:
            stage_idx = SAMPLE_STAGES.index(current_stage)
        except ValueError:
            stage_idx = 0
        revise_stage = st.selectbox(
            "Stage at fitting",
            options=SAMPLE_STAGES,
            index=stage_idx,
            key="revise_stage_select",
        )
    with ctrl[1]:
        reason_default = st.text_input(
            "Reason (applies to all rows)",
            value=f"{current_stage} fit revision",
            key="revise_reason_input",
        )

    rows = [
        {
            "POM": m.get("pom", ""),
            "Current": m.get("target", ""),
            "New target": "",
            "Δ +/-": "",
            "Tol +": m.get("tolerance_plus", ""),
            "Tol -": m.get("tolerance_minus", ""),
        }
        for m in measurements
    ]
    edited = st.data_editor(
        pd.DataFrame(rows),
        num_rows="fixed",
        use_container_width=True,
        hide_index=True,
        key=f"revise_table_editor_{st.session_state.get('editor_epoch', 0)}",
        column_config={
            "POM": st.column_config.TextColumn("POM", disabled=True, pinned=True),
            "Current": st.column_config.TextColumn("Current (read-only)", disabled=True),
            "New target": st.column_config.TextColumn("✏️ New target"),
            "Δ +/-": st.column_config.TextColumn("✏️ Δ +/-"),
            "Tol +": st.column_config.TextColumn("Tol +"),
            "Tol -": st.column_config.TextColumn("Tol -"),
        },
    )

    if st.button("Preview Changes", key="revise_preview_btn", type="primary"):
        updates: list[dict[str, Any]] = []
        problems: list[str] = []
        by_pom = {m.get("pom", ""): m for m in measurements}
        for _, row in edited.iterrows():
            pom = str(row.get("POM", "")).strip()
            if not pom:
                continue
            current = by_pom.get(pom, {})
            new_raw = str(row.get("New target", "") or "").strip()
            delta_raw = str(row.get("Δ +/-", "") or "").strip()
            tol_p = str(row.get("Tol +", "") or "").strip()
            tol_m = str(row.get("Tol -", "") or "").strip()
            update: dict[str, Any] = {
                "pom": pom,
                "new_target": None,
                "delta": None,
                "tolerance_plus": tol_p if tol_p != str(current.get("tolerance_plus", "")) else None,
                "tolerance_minus": tol_m if tol_m != str(current.get("tolerance_minus", "")) else None,
                "action": "update",
                "reason": reason_default or "Direct revision (worksheet)",
            }
            if new_raw:
                value = _parse_amount(new_raw)
                if value is None:
                    problems.append(f"{pom}: could not read new target “{new_raw}”")
                    continue
                update["new_target"] = f"{value:g}"
            elif delta_raw:
                value = _parse_amount(delta_raw)
                if value is None:
                    problems.append(f"{pom}: could not read delta “{delta_raw}”")
                    continue
                update["delta"] = f"{value:+g}"
            elif update["tolerance_plus"] is None and update["tolerance_minus"] is None:
                continue  # untouched row
            updates.append(update)

        for msg in problems:
            st.warning(msg)
        if not updates:
            st.info("No revisions entered — type a new target or a Δ on at least one row.")
        else:
            from fit_update_service import apply_structured_updates

            revised = apply_structured_updates(tech_pack, updates)
            st.session_state.pending_fit = {
                "revised": revised,
                "stage": revise_stage,
                "n_old": len(tech_pack.get("change_log", [])),
            }


def _render_pending_fit_preview(tech_pack: dict[str, Any]) -> None:
    """Shared preview → Apply/Discard block for both revision paths."""
    pending = st.session_state.get("pending_fit")
    if pending:
        new_entries = pending["revised"].get("change_log", [])[pending["n_old"] :]
        applied = [
            e for e in new_entries if not str(e.get("reason", "")).startswith("NOT APPLIED")
        ]
        flagged = [e for e in new_entries if str(e.get("reason", "")).startswith("NOT APPLIED")]

        st.divider()
        st.markdown("**Proposed changes — nothing is saved until you click Apply**")
        if applied:
            st.dataframe(
                pd.DataFrame(applied)[["pom", "field", "old_value", "new_value", "reason"]],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No applicable measurement changes were found.")
        if flagged:
            st.warning(f"{len(flagged)} change(s) could not be applied — review manually:")
            for e in flagged:
                st.markdown(f"- {e.get('reason', '')}")

        col_apply, col_discard, _ = st.columns([1, 1, 3])
        with col_apply:
            if st.button("Apply Changes", key="apply_fitting_btn"):
                _commit_fit_revision(tech_pack, pending["revised"], pending["stage"])
                st.session_state.last_fitting_summary = (
                    f"{len(applied)} change(s) applied, {len(flagged)} flagged for review "
                    f"(rev {st.session_state.tech_pack.get('rev')}, stage {pending['stage']})."
                )
                st.session_state.pending_fit = None
                st.rerun()
        with col_discard:
            if st.button("Discard", key="discard_fitting_btn"):
                st.session_state.pending_fit = None
                st.rerun()

    if st.session_state.get("last_fitting_summary"):
        st.success(st.session_state.last_fitting_summary)

    tech_pack = st.session_state.tech_pack

    st.subheader("Change log")
    st.dataframe(_change_log_df(tech_pack), use_container_width=True, hide_index=True)

    st.subheader("Revised measurements")
    st.caption(
        "Read-only view. Revise via the worksheet or notes above, or hand-edit in "
        "**② Tech Pack → Measurements** — every change is change-logged."
    )
    st.dataframe(_measurements_df(tech_pack), use_container_width=True, hide_index=True)


def section_fitting_notes() -> None:
    tech_pack = st.session_state.tech_pack
    if not tech_pack.get("style_number"):
        st.info("Generate a tech pack first.", icon="ℹ️")
        return

    _render_undo_controls("fit")
    st.markdown(
        "Bring fit results into the spec, three ways: **Revise Table** for direct "
        "entry (no math — type the new number or the delta), **Paste Notes** for "
        "freeform fit comments, **Fitting Room** for a full session transcript."
    )
    tabs = st.tabs(
        [
            f"Revise Table  {LIVE_BADGE}",
            f"Paste Notes  {LIVE_BADGE}",
            f"Fitting Room  {LIVE_BADGE}",
        ]
    )
    with tabs[0]:
        _render_revise_table_tab(tech_pack)
    with tabs[1]:
        _render_paste_notes_tab(tech_pack)
    with tabs[2]:
        _render_fitting_room_live(tech_pack)

    _render_pending_fit_preview(tech_pack)


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

    with st.expander("AI-draft the email from the latest fit session"):
        has_openai = bool(os.getenv("OPENAI_API_KEY"))
        if not has_openai:
            st.caption("Requires OPENAI_API_KEY.")
        change_log = tech_pack.get("change_log", []) or []
        st.caption(
            f"Uses the last {min(len(change_log), 10)} change-log entries"
            + (" and the fitting-room transcript." if st.session_state.get("fitting_transcript") else ".")
        )
        if st.button("Draft email with AI", key="send_ai_draft_btn", disabled=not has_openai):
            structured = [
                {
                    "pom": e.get("pom", ""),
                    "delta": e.get("new_value", ""),
                    "reason": e.get("reason", ""),
                }
                for e in change_log[-10:]
            ]
            with st.spinner("Drafting…"):
                try:
                    from gpt_service import draft_fitting_email

                    draft = draft_fitting_email(
                        tech_pack,
                        st.session_state.get("fitting_transcript", ""),
                        structured,
                        tech_pack.get("fit_photos") or [],
                        factory_name=factory["factory_name"],
                        contact_name=contact["name"],
                    )
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Drafting failed: {exc}")
                    draft = None
            if draft:
                st.session_state.fitting_draft_subject = draft["subject"]
                st.session_state.fitting_draft_body = draft["body"]
                st.rerun()

    fitting_draft_body = st.session_state.get("fitting_draft_body") or ""
    fitting_draft_subject = st.session_state.get("fitting_draft_subject") or ""
    if fitting_draft_body:
        if st.checkbox(
            "Use the AI draft as the email body",
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
                    attachment = export_tech_pack_to_excel(
                        tech_pack, sketch_bytes=st.session_state.get("uploaded_sketch_bytes")
                    or _from_b64(tech_pack.get("sketch_b64") or "")
                    )
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
                _flash("warning", f"Email sent but WIP record update failed: {exc}")
            _flash(
                "success",
                f"Test email sent via {result.get('transport')} to "
                f"{os.getenv('TEST_EMAIL_RECIPIENT')} (intended: {contact['email']}). "
                "Status updated to Sent to Factory.",
            )
            _go("wip")
        else:
            st.error(f"Email failed: {result.get('error')}")

    with st.expander(f"Factory replies  {PREVIEW_BADGE}", expanded=False):
        _preview_banner(
            "Inbound factory comments will land here, threaded to the style + revision. "
            "Today this section is a placeholder."
        )


# Full production T&A milestone catalog, grouped by workstream.
TNA_PHASES: dict[str, list[str]] = {
    "Development": [
        "Tech pack sent",
        "Proto due",
        "Fit 1",
        "Fit 2",
        "Fit 3",
        "Grading approved",
    ],
    "Materials & approvals": [
        "Lab dips approved",
        "Strike-off approved",
        "Bulk fabric in-house",
        "Trims in-house",
        "Test reports approved",
    ],
    "Sales & production": [
        "SMS due",
        "Costing locked",
        "PO issued",
        "Size set approved",
        "PP approved",
        "TOP approved",
        "Final inspection",
        "Ex-factory",
        "Bulk delivery",
    ],
}
TNA_MILESTONES: list[str] = [m for phase in TNA_PHASES.values() for m in phase]

# Critical-path default shown in the calendar grid; any milestone that already
# has a date is added automatically. The rest are one multiselect away.
TNA_DEFAULT_TRACKED: list[str] = [
    "Tech pack sent", "Proto due", "Fit 1", "Lab dips approved",
    "Bulk fabric in-house", "SMS due", "PP approved", "Ex-factory",
]


def _parse_iso_date(value: str):
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _milestone_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten milestones for overdue/upcoming views: one row per dated milestone."""
    today = datetime.now().date()
    rows = []
    for r in records:
        done = set(r.get("milestones_done") or [])
        for name in TNA_MILESTONES:
            d = _parse_iso_date((r.get("milestones") or {}).get(name, ""))
            if d is None:
                continue
            rows.append(
                {
                    "style_number": r.get("style_number", ""),
                    "style_name": r.get("style_name", ""),
                    "milestone": name,
                    "date": d,
                    "days": (d - today).days,
                    "status": r.get("status", ""),
                    "done": name in done,
                }
            )
    rows.sort(key=lambda x: x["date"])
    return rows


def _tab_wip_board(records: list[dict[str, Any]]) -> None:
    with st.expander("Open a saved style"):
        _render_saved_styles("wip")
    if not records:
        st.info(
            "No styles in progress yet. Generate a tech pack — every style lands "
            "here automatically as “In Development”.",
            icon="ℹ️",
        )
        return
    milestone_rows = _milestone_rows(records)
    next_by_style: dict[str, str] = {}
    for row in milestone_rows:
        if row["days"] >= 0 and not row["done"] and row["style_number"] not in next_by_style:
            next_by_style[row["style_number"]] = f"{row['milestone']} · {row['date']}"
    df = pd.DataFrame(records)
    df["next_milestone"] = df["style_number"].map(next_by_style).fillna("—")
    preferred = [
        "style_number", "style_name", "sample_stage", "factory_name",
        "contact_name", "status", "next_milestone", "last_update", "tech_pack_file",
    ]
    columns = [c for c in preferred if c in df.columns]
    st.dataframe(df[columns], use_container_width=True, hide_index=True)


def _tab_wip_report(records: list[dict[str, Any]]) -> None:
    if not records:
        st.info("Nothing to report yet.", icon="ℹ️")
        return
    today = datetime.now().date()
    milestone_rows = _milestone_rows(records)
    overdue = [r for r in milestone_rows if r["days"] < 0 and not r["done"]]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Styles on board", len(records))
    m2.metric("In development", sum(1 for r in records if r.get("status") != "Sent to Factory"))
    m3.metric("Sent to factory", sum(1 for r in records if r.get("status") == "Sent to Factory"))
    m4.metric("Overdue milestones", len(overdue), delta_color="inverse")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**By status**")
        status_counts = pd.DataFrame(records)["status"].value_counts().reset_index()
        status_counts.columns = ["Status", "Styles"]
        st.dataframe(status_counts, use_container_width=True, hide_index=True)
    with col_b:
        st.markdown("**By factory**")
        fac = pd.DataFrame(records).get("factory_name")
        if fac is not None:
            fac_counts = fac.fillna("(unassigned)").replace("", "(unassigned)").value_counts().reset_index()
            fac_counts.columns = ["Factory", "Styles"]
            st.dataframe(fac_counts, use_container_width=True, hide_index=True)

    st.markdown("**Aging — days since last activity**")
    aging = []
    for r in records:
        last = _parse_iso_date(r.get("last_update", ""))
        aging.append(
            {
                "Style #": r.get("style_number", ""),
                "Name": r.get("style_name", ""),
                "Status": r.get("status", ""),
                "Last update": r.get("last_update", ""),
                "Days idle": (today - last).days if last else "—",
            }
        )
    aging.sort(key=lambda x: (x["Days idle"] if isinstance(x["Days idle"], int) else -1), reverse=True)
    st.dataframe(pd.DataFrame(aging), use_container_width=True, hide_index=True)

    export_rows = []
    for r in records:
        row = {k: v for k, v in r.items() if k != "milestones"}
        done = set(r.get("milestones_done") or [])
        for name in TNA_MILESTONES:
            value = (r.get("milestones") or {}).get(name, "")
            row[name] = f"{value} ✓" if value and name in done else value
        export_rows.append(row)
    csv = pd.DataFrame(export_rows).to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download WIP report (CSV)",
        data=csv,
        file_name=f"wip_report_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        key="wip_report_download",
    )


def _tab_wip_calendar(records: list[dict[str, Any]]) -> None:
    if not records:
        st.info("Generate a style first — then plan its T&A dates here.", icon="ℹ️")
        return
    st.caption(
        f"{LIVE_BADGE}. Time & Action calendar — set target dates per style across "
        "development, materials, and production. Mark milestones done as they land; "
        "overdue and upcoming items surface below and on the Board."
    )
    dated = {
        name
        for r in records
        for name in TNA_MILESTONES
        if (r.get("milestones") or {}).get(name)
    }
    tracked = st.multiselect(
        "Milestones in the grid",
        options=TNA_MILESTONES,
        default=[m for m in TNA_MILESTONES if m in dated or m in TNA_DEFAULT_TRACKED],
        key="tna_tracked",
        help="The full catalog covers development, materials/approvals, and "
        "production gates — show the columns your team plans against.",
    )
    if not tracked:
        st.info("Pick at least one milestone to plan against.")
        return

    rows = []
    for r in records:
        row: dict[str, Any] = {
            "Style #": r.get("style_number", ""),
            "Name": r.get("style_name", ""),
        }
        for name in tracked:
            row[name] = _parse_iso_date((r.get("milestones") or {}).get(name, ""))
        rows.append(row)
    edited = st.data_editor(
        pd.DataFrame(rows),
        num_rows="fixed",
        use_container_width=True,
        hide_index=True,
        key="tna_editor",
        column_config={
            "Style #": st.column_config.TextColumn("Style #", disabled=True),
            "Name": st.column_config.TextColumn("Name", disabled=True),
            **{
                name: st.column_config.DateColumn(name, format="YYYY-MM-DD")
                for name in tracked
            },
        },
    )
    by_number = {r.get("style_number", ""): (r.get("milestones") or {}) for r in records}
    for _, row in edited.iterrows():
        style_number = str(row.get("Style #", "")).strip()
        if not style_number:
            continue
        existing_ms = {k: v for k, v in by_number.get(style_number, {}).items() if v}
        # merge: grid columns take the edited value; untracked milestones keep theirs
        new_ms = {k: v for k, v in existing_ms.items() if k not in tracked}
        for name in tracked:
            value = row.get(name)
            if value is not None and str(value) != "NaT" and not (isinstance(value, float) and pd.isna(value)):
                new_ms[name] = str(value)[:10]
        if new_ms != existing_ms:
            set_wip_milestones(style_number, new_ms)

    milestone_rows = _milestone_rows(load_wip_records())
    overdue = [r for r in milestone_rows if r["days"] < 0 and not r["done"]]
    upcoming = [r for r in milestone_rows if 0 <= r["days"] <= 14 and not r["done"]]
    recently_done = [r for r in milestone_rows if r["done"]]

    def _done_button(r: dict[str, Any], idx: int, prefix: str) -> None:
        if st.button("✓ done", key=f"{prefix}_done_{idx}"):
            mark_milestone_done(r["style_number"], r["milestone"], True)
            st.rerun()

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**🔴 Overdue**")
        if overdue:
            for i, r in enumerate(overdue):
                line, btn = st.columns([5, 1])
                line.markdown(
                    f"**{r['style_number']}** {r['milestone']} — {r['date']} "
                    f"({-r['days']} day{'s' if r['days'] != -1 else ''} late)"
                )
                with btn:
                    _done_button(r, i, "ov")
        else:
            st.caption("Nothing overdue.")
    with col_b:
        st.markdown("**🟡 Next 14 days**")
        if upcoming:
            for i, r in enumerate(upcoming):
                line, btn = st.columns([5, 1])
                line.markdown(
                    f"**{r['style_number']}** {r['milestone']} — {r['date']} "
                    f"(in {r['days']} day{'s' if r['days'] != 1 else ''})"
                )
                with btn:
                    _done_button(r, i, "up")
        else:
            st.caption("Nothing due in the next two weeks.")

    if recently_done:
        with st.expander(f"✅ Completed milestones ({len(recently_done)})"):
            for i, r in enumerate(recently_done):
                line, btn = st.columns([5, 1])
                line.markdown(f"**{r['style_number']}** {r['milestone']} — {r['date']}")
                if btn.button("undo", key=f"done_undo_{i}"):
                    mark_milestone_done(r["style_number"], r["milestone"], False)
                    st.rerun()


def section_wip_dashboard() -> None:
    records = load_wip_records()
    tabs = st.tabs(
        [
            f"Board  {LIVE_BADGE}",
            f"Report  {LIVE_BADGE}",
            f"T&A Calendar  {LIVE_BADGE}",
        ]
    )
    with tabs[0]:
        _tab_wip_board(records)
    with tabs[1]:
        _tab_wip_report(records)
    with tabs[2]:
        _tab_wip_calendar(records)


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

    _stepper()
    _render_flashes()

    stage = st.session_state.get("nav_stage", "intake")
    has_style = bool(st.session_state.tech_pack.get("style_number"))

    if stage in ("techpack", "fit", "send") and not has_style:
        st.info(
            f"**{_STAGE_LABELS[stage]}** needs a style in progress. "
            "Start at ① Styles — open a saved tech pack from the archive, or generate a new style."
        )
        if st.button("← Go to ① Styles", key="goto_intake_btn"):
            _go("intake")
        return

    st.markdown(f"## {_STAGE_LABELS[stage]}")
    if stage == "intake":
        section_style_setup()
    elif stage == "techpack":
        section_tech_pack_preview()
    elif stage == "fit":
        section_fitting_notes()
    elif stage == "send":
        section_send_to_factory()
    elif stage == "wip":
        section_wip_dashboard()
    elif stage == "library":
        section_brand_library()

    _stage_footer_nav(stage)

    st.divider()
    st.caption(
        "Demo only — outbound emails are routed to TEST_EMAIL_RECIPIENT, not real factories. "
        "Generated measurements are draft suggestions and must be reviewed by a technical designer."
    )


if __name__ == "__main__":
    main()
