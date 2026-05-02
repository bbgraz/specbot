"""OpenAI GPT-4o service for sketch analysis and tech pack generation."""

from __future__ import annotations

import base64
import io
import json
import os
from typing import Any

from openai import OpenAI

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

SYSTEM_PROMPT = """You are SpecBot, an AI assistant for apparel technical designers.
You analyze sketches, reference images, and metadata to draft a tech pack.

Strict rules:
- Never invent certainty. If the image is unclear, say so in missing_information.
- Every measurement, BOM item, and construction note must be labeled with one of:
    "derived_from_input"             (visible in the sketch / explicit in metadata)
    "inferred_from_standard_practice" (industry-standard for this garment type)
    "placeholder_for_review"         (best guess, must be confirmed by a tech designer)
- Use inches for measurements unless otherwise specified.
- Provide tolerance_plus and tolerance_minus as decimal inches (e.g. "0.25").
- Output ONLY valid JSON matching the schema. No prose, no markdown fences.
"""

JSON_SCHEMA_HINT = {
    "garment_summary": "string - 2-3 sentence description of the garment",
    "detected_features": ["list of visible design features"],
    "suggested_measurements": [
        {
            "pom": "Point of Measure name (e.g. 'Chest Width')",
            "description": "how to measure",
            "target": "target value in inches as string",
            "tolerance_plus": "decimal string",
            "tolerance_minus": "decimal string",
            "source": "derived_from_input | inferred_from_standard_practice | placeholder_for_review",
            "notes": "string",
        }
    ],
    "construction_notes": [
        {
            "note": "construction detail",
            "source": "derived_from_input | inferred_from_standard_practice | placeholder_for_review",
        }
    ],
    "bom_items": [
        {
            "component": "e.g. Self fabric, Main label, Care label, Buttons",
            "material": "material spec",
            "placement": "where it goes",
            "notes": "string",
            "source": "derived_from_input | inferred_from_standard_practice | placeholder_for_review",
        }
    ],
    "assumptions": ["list of assumptions made"],
    "missing_information": ["list of things the designer must clarify"],
}


def _client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY not set. Add it to your .env file before generating a tech pack."
        )
    return OpenAI(api_key=api_key)


def _file_to_data_url(file_bytes: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(file_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _pdf_first_page_to_png_bytes(pdf_bytes: bytes) -> bytes | None:
    """Best-effort extraction of the first PDF page as a PNG. Returns None if unavailable."""
    try:
        from pypdf import PdfReader
        from PIL import Image

        reader = PdfReader(io.BytesIO(pdf_bytes))
        if not reader.pages:
            return None
        page = reader.pages[0]
        for image_obj in getattr(page, "images", []) or []:
            img = Image.open(io.BytesIO(image_obj.data)).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        return None
    return None


def _build_user_content(
    file_bytes: bytes | None,
    mime_type: str | None,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    metadata_block = (
        "Style metadata provided by the designer:\n"
        f"- Style name: {metadata.get('style_name') or 'N/A'}\n"
        f"- Style number: {metadata.get('style_number') or 'N/A'}\n"
        f"- Garment type: {metadata.get('garment_type') or 'N/A'}\n"
        f"- Fabric: {metadata.get('fabric') or 'N/A'}\n"
        f"- Sample size: {metadata.get('sample_size') or 'N/A'}\n\n"
        "Return JSON with keys: "
        "garment_summary, detected_features, suggested_measurements, "
        "construction_notes, bom_items, assumptions, missing_information.\n\n"
        f"Schema hint: {json.dumps(JSON_SCHEMA_HINT)}"
    )

    content: list[dict[str, Any]] = [{"type": "text", "text": metadata_block}]

    if file_bytes and mime_type:
        if mime_type == "application/pdf":
            png_bytes = _pdf_first_page_to_png_bytes(file_bytes)
            if png_bytes:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": _file_to_data_url(png_bytes, "image/png")},
                    }
                )
            else:
                content[0]["text"] += (
                    "\n\nNOTE: A PDF was uploaded but no embedded image could be extracted. "
                    "Treat as no image provided and rely on metadata + standard practice. "
                    "Add appropriate entries to missing_information."
                )
        elif mime_type.startswith("image/"):
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _file_to_data_url(file_bytes, mime_type)},
                }
            )
    else:
        content[0]["text"] += (
            "\n\nNOTE: No sketch was uploaded. Mark visual features as missing_information "
            "and base draft on metadata + standard practice."
        )

    return content


def _safe_json_loads(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        # strip code fences if the model added them despite instructions
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def analyze_sketch(file: Any | None, metadata: dict[str, Any]) -> dict[str, Any]:
    """Analyze an uploaded sketch / PDF / image and return a structured tech pack draft.

    `file` is a Streamlit UploadedFile (has `.read()`, `.type`, `.name`) or None.
    """
    file_bytes: bytes | None = None
    mime_type: str | None = None
    if file is not None:
        file_bytes = file.read()
        mime_type = getattr(file, "type", None) or "application/octet-stream"

    client = _client()
    user_content = _build_user_content(file_bytes, mime_type, metadata)

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )
    raw = response.choices[0].message.content or "{}"
    data = _safe_json_loads(raw)

    return {
        "garment_summary": data.get("garment_summary", ""),
        "detected_features": data.get("detected_features", []) or [],
        "suggested_measurements": data.get("suggested_measurements", []) or [],
        "construction_notes": data.get("construction_notes", []) or [],
        "bom_items": data.get("bom_items", []) or [],
        "assumptions": data.get("assumptions", []) or [],
        "missing_information": data.get("missing_information", []) or [],
    }


def reason_fitting_notes(tech_pack: dict[str, Any], fitting_notes: str) -> dict[str, Any]:
    """Use GPT to interpret freeform fitting notes into structured updates.

    Returns:
        {
          "updates": [
            {"pom": str, "new_target": str | None, "delta": str | None,
             "tolerance_plus": str | None, "tolerance_minus": str | None,
             "action": "update" | "add", "reason": str}
          ],
          "summary": str
        }
    """
    client = _client()

    measurements_summary = [
        {
            "pom": m.get("pom", ""),
            "target": m.get("target", ""),
            "tolerance_plus": m.get("tolerance_plus", ""),
            "tolerance_minus": m.get("tolerance_minus", ""),
        }
        for m in tech_pack.get("measurements", [])
    ]

    system = (
        "You translate apparel fitting notes into structured POM updates. "
        "Be conservative: if a note is ambiguous, do not invent a delta. "
        "Output ONLY valid JSON."
    )
    user = (
        f"Current measurements:\n{json.dumps(measurements_summary, indent=2)}\n\n"
        f"Fitting notes from the fit session:\n\"\"\"\n{fitting_notes}\n\"\"\"\n\n"
        "Return JSON: {\n"
        '  "updates": [\n'
        '     {"pom": "<exact name from list, or new POM>",\n'
        '      "new_target": "<inches as string, or null>",\n'
        '      "delta": "<+0.5 / -0.25 etc, or null>",\n'
        '      "tolerance_plus": "<or null>",\n'
        '      "tolerance_minus": "<or null>",\n'
        '      "action": "update" | "add",\n'
        '      "reason": "<short, quote the fitting note>"}\n'
        "  ],\n"
        '  "summary": "<one sentence>"\n'
        "}\n"
        "If the note doesn't map to a measurement, omit it."
    )

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    raw = response.choices[0].message.content or "{}"
    data = _safe_json_loads(raw)
    return {
        "updates": data.get("updates", []) or [],
        "summary": data.get("summary", ""),
    }
