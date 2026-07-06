"""JSON-backed local store for tech packs.

A redeploy or page reload otherwise wipes session state. This module persists
each tech pack as `<dir>/<style_number>.json` and lets the UI list / load /
delete saved styles.

Storage path resolution:
  1. `SPECBOT_TECHPACK_DIR` env var if set
  2. `<repo>/tech_packs/` next to `app.py`
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).resolve().parent / "tech_packs"
TECH_PACK_DIR = Path(os.getenv("SPECBOT_TECHPACK_DIR") or _DEFAULT_DIR)


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_\-]+", "_", name).strip("_")
    return cleaned or "tech_pack"


def _path_for(style_number: str) -> Path:
    return TECH_PACK_DIR / f"{_safe_filename(style_number)}.json"


def save_tech_pack(tech_pack: dict[str, Any]) -> Path:
    """Persist a tech pack keyed on its style_number. Returns the file path."""
    style_number = (tech_pack.get("style_number") or "").strip()
    if not style_number:
        raise ValueError("Cannot save tech pack without style_number.")

    TECH_PACK_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(tech_pack)
    payload["_saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    target = _path_for(style_number)
    with target.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    return target


def load_tech_pack(style_number: str) -> dict[str, Any] | None:
    """Return the saved tech pack for a style, or None if absent / unreadable."""
    target = _path_for(style_number)
    if not target.is_file():
        return None
    try:
        with target.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def list_tech_packs() -> list[dict[str, Any]]:
    """Return summaries of all saved tech packs, newest first."""
    if not TECH_PACK_DIR.is_dir():
        return []
    summaries: list[dict[str, Any]] = []
    for path in TECH_PACK_DIR.glob("*.json"):
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        summaries.append(
            {
                "style_number": data.get("style_number", ""),
                "style_name": data.get("style_name", ""),
                "garment_type": data.get("garment_type", ""),
                "sample_stage": data.get("sample_stage", ""),
                "saved_at": data.get("_saved_at", ""),
                "path": str(path),
            }
        )
    summaries.sort(key=lambda r: r.get("saved_at", ""), reverse=True)
    return summaries


def delete_tech_pack(style_number: str) -> bool:
    """Remove a saved tech pack. Returns True if a file was removed."""
    target = _path_for(style_number)
    if not target.is_file():
        return False
    try:
        target.unlink()
    except OSError:
        return False
    return True
