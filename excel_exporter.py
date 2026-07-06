"""Excel export for tech packs using xlsxwriter."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import xlsxwriter

from mock_data import DEFAULT_SIZE_RUN, build_graded_table

_DEFAULT_EXPORT_DIR = Path(__file__).resolve().parent / "exports"
EXPORT_DIR = Path(os.getenv("SPECBOT_EXPORT_DIR") or _DEFAULT_EXPORT_DIR)


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_\-]+", "_", name).strip("_")
    return cleaned or "tech_pack"


def _write_header_band(
    worksheet: xlsxwriter.workbook.Worksheet,
    tech_pack: dict[str, Any],
    sheet_title: str,
    title_format,
    meta_format,
    generated_at: str,
) -> int:
    """Write a 3-row header band on every sheet. Returns the next free row index."""
    style_number = tech_pack.get("style_number") or "(no style number)"
    style_name = tech_pack.get("style_name") or "(no style name)"

    worksheet.merge_range(0, 0, 0, 6, f"SpecBot Tech Pack — {sheet_title}", title_format)
    worksheet.write(
        1, 0, f"Style #{style_number}  •  {style_name}", meta_format
    )
    worksheet.write(2, 0, f"Generated: {generated_at}", meta_format)
    worksheet.set_row(0, 22)
    return 4  # leave a blank row before content


def _autosize(worksheet, headers: list[str], rows: list[list[Any]]) -> None:
    for col_idx, header in enumerate(headers):
        max_len = len(str(header))
        for row in rows:
            if col_idx < len(row):
                value = "" if row[col_idx] is None else str(row[col_idx])
                if len(value) > max_len:
                    max_len = len(value)
        worksheet.set_column(col_idx, col_idx, min(max_len + 2, 60))


def _prepare_sketch_png(sketch_bytes: bytes | None):
    """Convert uploaded sketch bytes to (PNG BytesIO, scale) for embedding, or None."""
    if not sketch_bytes:
        return None
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(sketch_bytes)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        scale = min(1.0, 420.0 / max(img.width, 1))
        return buf, scale
    except Exception:  # noqa: BLE001 - a bad image must never block the export
        return None


def export_tech_pack_to_excel(
    tech_pack: dict[str, Any],
    sketch_bytes: bytes | None = None,
) -> str:
    """Export the tech pack to an Excel workbook. Returns the absolute file path.

    `sketch_bytes` (optional) is the uploaded sketch; when provided it is
    embedded on the Cover sheet — a factory can't sew from prose alone.
    """
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    style_number = tech_pack.get("style_number") or "draft"
    rev = tech_pack.get("rev")
    rev_part = f"_rev{rev}" if rev else ""
    filename = f"techpack_{_safe_filename(style_number)}{rev_part}_{timestamp}.xlsx"
    filepath = (EXPORT_DIR / filename).resolve()

    workbook = xlsxwriter.Workbook(str(filepath))

    title_fmt = workbook.add_format(
        {"bold": True, "font_size": 14, "bg_color": "#1F2937", "font_color": "white", "align": "left", "valign": "vcenter"}
    )
    meta_fmt = workbook.add_format({"italic": True, "font_color": "#374151"})
    header_fmt = workbook.add_format(
        {"bold": True, "bg_color": "#E5E7EB", "border": 1, "align": "left"}
    )
    cell_fmt = workbook.add_format({"border": 1, "valign": "top", "text_wrap": True})
    label_fmt = workbook.add_format({"bold": True, "valign": "top"})

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Cover
    cover = workbook.add_worksheet("Cover")
    next_row = _write_header_band(cover, tech_pack, "Cover", title_fmt, meta_fmt, generated_at)
    cover_pairs: list[tuple[str, str]] = [
        ("Style number", tech_pack.get("style_number", "")),
        ("Style name", tech_pack.get("style_name", "")),
        ("Garment type", tech_pack.get("garment_type", "")),
        ("Fabric", tech_pack.get("fabric", "")),
        ("Sample size", tech_pack.get("sample_size", "")),
        ("Sample stage", tech_pack.get("sample_stage", "")),
        ("Design intent", tech_pack.get("style_description", "")),
        ("Garment summary", tech_pack.get("garment_summary", "")),
    ]
    for label, value in cover_pairs:
        cover.write(next_row, 0, label, label_fmt)
        cover.write(next_row, 1, value or "", cell_fmt)
        next_row += 1
    cover.set_column(0, 0, 22)
    cover.set_column(1, 1, 80)
    cover.freeze_panes(4, 0)

    sketch = _prepare_sketch_png(sketch_bytes)
    if sketch:
        sketch_buf, sketch_scale = sketch
        cover.write(next_row + 1, 0, "Sketch", label_fmt)
        cover.insert_image(
            next_row + 2,
            0,
            "sketch.png",
            {"image_data": sketch_buf, "x_scale": sketch_scale, "y_scale": sketch_scale},
        )
    else:
        cover.write(
            next_row + 1,
            0,
            "Sketch: none embedded — attach the flat/sketch before sending to a factory.",
            meta_fmt,
        )

    # 2. Measurements
    meas_sheet = workbook.add_worksheet("Measurements")
    next_row = _write_header_band(meas_sheet, tech_pack, "Measurements", title_fmt, meta_fmt, generated_at)
    meas_headers = ["POM", "Description", "Target", "Tol +", "Tol -", "Source", "Notes"]
    for col, h in enumerate(meas_headers):
        meas_sheet.write(next_row, col, h, header_fmt)
    rows_for_size: list[list[Any]] = []
    data_start = next_row + 1
    for i, m in enumerate(tech_pack.get("measurements", [])):
        row_values = [
            m.get("pom", ""),
            m.get("description", ""),
            m.get("target", ""),
            m.get("tolerance_plus", ""),
            m.get("tolerance_minus", ""),
            m.get("source", ""),
            m.get("notes", ""),
        ]
        for col, v in enumerate(row_values):
            meas_sheet.write(data_start + i, col, v, cell_fmt)
        rows_for_size.append(row_values)
    _autosize(meas_sheet, meas_headers, rows_for_size)
    meas_sheet.freeze_panes(data_start, 0)
    try:
        import io

        from spec_diagram import render_spec_diagram

        diagram_png = render_spec_diagram(tech_pack)
        meas_sheet.insert_image(
            4,
            len(meas_headers) + 1,
            "pom_diagram.png",
            {"image_data": io.BytesIO(diagram_png), "x_scale": 0.62, "y_scale": 0.62},
        )
    except Exception:  # noqa: BLE001 - the diagram must never block an export
        pass

    # 3. BOM
    bom_sheet = workbook.add_worksheet("BOM")
    next_row = _write_header_band(bom_sheet, tech_pack, "Bill of Materials", title_fmt, meta_fmt, generated_at)
    bom_headers = [
        "Component", "Material", "Placement", "Qty/Consumption", "UOM",
        "Supplier / Article #", "Color / DTM", "Notes", "Source",
    ]
    for col, h in enumerate(bom_headers):
        bom_sheet.write(next_row, col, h, header_fmt)
    rows_for_size = []
    data_start = next_row + 1
    for i, b in enumerate(tech_pack.get("bom", [])):
        row_values = [
            b.get("component", ""),
            b.get("material", ""),
            b.get("placement", ""),
            b.get("quantity", ""),
            b.get("uom", ""),
            b.get("supplier", ""),
            b.get("color", ""),
            b.get("notes", ""),
            b.get("source", ""),
        ]
        for col, v in enumerate(row_values):
            bom_sheet.write(data_start + i, col, v, cell_fmt)
        rows_for_size.append(row_values)
    _autosize(bom_sheet, bom_headers, rows_for_size)
    bom_sheet.freeze_panes(data_start, 0)

    # 4. Construction
    con_sheet = workbook.add_worksheet("Construction")
    next_row = _write_header_band(con_sheet, tech_pack, "Construction Notes", title_fmt, meta_fmt, generated_at)
    con_headers = ["#", "Zone", "Note", "Stitch (ISO 4915)", "Seam (ISO 4916)", "SPI", "Source"]
    for col, h in enumerate(con_headers):
        con_sheet.write(next_row, col, h, header_fmt)
    rows_for_size = []
    data_start = next_row + 1
    for i, note in enumerate(tech_pack.get("construction_notes", [])):
        if isinstance(note, dict):
            row_values = [
                i + 1,
                note.get("zone", ""),
                note.get("note", ""),
                note.get("stitch_type", ""),
                note.get("seam_class", ""),
                note.get("spi", ""),
                note.get("source", ""),
            ]
        else:
            row_values = [i + 1, "", str(note), "", "", "", ""]
        for col, v in enumerate(row_values):
            con_sheet.write(data_start + i, col, v, cell_fmt)
        rows_for_size.append(row_values)
    _autosize(con_sheet, con_headers, rows_for_size)
    con_sheet.set_column(2, 2, 60)
    con_sheet.freeze_panes(data_start, 0)

    # 5a. Grading
    grade_sheet = workbook.add_worksheet("Grading")
    next_row = _write_header_band(grade_sheet, tech_pack, "Grading", title_fmt, meta_fmt, generated_at)
    measurements = tech_pack.get("measurements", []) or []
    if measurements:
        rule_overrides = tech_pack.get("grade_rules") or {}
        sample_size = tech_pack.get("sample_size") or "M"
        graded = build_graded_table(
            measurements,
            sample_size=sample_size,
            size_run=DEFAULT_SIZE_RUN,
            rule_overrides=rule_overrides,
        )
        if graded:
            headers = list(graded[0].keys())
            for col, h in enumerate(headers):
                grade_sheet.write(next_row, col, h, header_fmt)
            data_start = next_row + 1
            rows_for_size = []
            for i, row in enumerate(graded):
                values = [row.get(h, "") for h in headers]
                for col, v in enumerate(values):
                    grade_sheet.write(data_start + i, col, v, cell_fmt)
                rows_for_size.append(values)
            _autosize(grade_sheet, headers, rows_for_size)
            grade_sheet.freeze_panes(data_start, 1)
        else:
            grade_sheet.write(next_row, 0, "(no measurements to grade)", cell_fmt)
    else:
        grade_sheet.write(next_row, 0, "(no measurements to grade)", cell_fmt)

    # 5b. Annotations
    ann_sheet = workbook.add_worksheet("Annotations")
    next_row = _write_header_band(
        ann_sheet, tech_pack, "Sketch Annotations", title_fmt, meta_fmt, generated_at
    )
    ann_headers = ["#", "Zone", "Callout"]
    for col, h in enumerate(ann_headers):
        ann_sheet.write(next_row, col, h, header_fmt)
    data_start = next_row + 1
    rows_for_size = []
    for i, ann in enumerate(tech_pack.get("annotations", []) or []):
        values = [
            ann.get("id", i + 1),
            ann.get("zone", ""),
            ann.get("callout", ""),
        ]
        for col, v in enumerate(values):
            ann_sheet.write(data_start + i, col, v, cell_fmt)
        rows_for_size.append(values)
    _autosize(ann_sheet, ann_headers, rows_for_size)
    ann_sheet.set_column(2, 2, 60)
    ann_sheet.freeze_panes(data_start, 0)

    # 6. Change Log
    change_sheet = workbook.add_worksheet("Change Log")
    next_row = _write_header_band(change_sheet, tech_pack, "Change Log", title_fmt, meta_fmt, generated_at)
    change_headers = ["Timestamp", "Stage", "POM", "Field", "Old value", "New value", "Reason"]
    for col, h in enumerate(change_headers):
        change_sheet.write(next_row, col, h, header_fmt)
    rows_for_size = []
    data_start = next_row + 1
    for i, entry in enumerate(tech_pack.get("change_log", [])):
        row_values = [
            entry.get("timestamp", ""),
            entry.get("stage", ""),
            entry.get("pom", ""),
            entry.get("field", ""),
            entry.get("old_value", ""),
            entry.get("new_value", ""),
            entry.get("reason", ""),
        ]
        for col, v in enumerate(row_values):
            change_sheet.write(data_start + i, col, v, cell_fmt)
        rows_for_size.append(row_values)
    _autosize(change_sheet, change_headers, rows_for_size)
    change_sheet.freeze_panes(data_start, 0)

    # 6. Assumptions and Missing Info
    assume_sheet = workbook.add_worksheet("Assumptions and Missing")
    next_row = _write_header_band(
        assume_sheet, tech_pack, "Assumptions & Missing Information", title_fmt, meta_fmt, generated_at
    )
    assume_sheet.write(next_row, 0, "Assumptions", header_fmt)
    assume_sheet.write(next_row, 1, "Missing information", header_fmt)
    assumptions = tech_pack.get("assumptions", []) or []
    missing = tech_pack.get("missing_information", []) or []
    max_len = max(len(assumptions), len(missing), 1)
    for i in range(max_len):
        assume_sheet.write(
            next_row + 1 + i, 0, assumptions[i] if i < len(assumptions) else "", cell_fmt
        )
        assume_sheet.write(
            next_row + 1 + i, 1, missing[i] if i < len(missing) else "", cell_fmt
        )
    assume_sheet.set_column(0, 0, 50)
    assume_sheet.set_column(1, 1, 50)
    assume_sheet.freeze_panes(next_row + 1, 0)

    workbook.close()
    return str(filepath)
