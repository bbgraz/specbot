"""Local JSON-backed Work-In-Progress dashboard store."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

_DEFAULT_WIP_PATH = Path(__file__).resolve().parent / "wip_records.json"
WIP_PATH = Path(os.getenv("SPECBOT_WIP_PATH") or _DEFAULT_WIP_PATH)


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_wip_records() -> list[dict[str, Any]]:
    if not WIP_PATH.is_file():
        return []
    try:
        with WIP_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def save_wip_records(records: list[dict[str, Any]]) -> None:
    WIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with WIP_PATH.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2)


def add_or_update_wip_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Insert or update a record keyed on style_number. Returns the full record list."""
    style_number = (record.get("style_number") or "").strip()
    if not style_number:
        raise ValueError("style_number is required to add or update a WIP record.")

    record = {**record, "last_update": record.get("last_update") or _now_iso()}

    records = load_wip_records()
    for i, existing in enumerate(records):
        if existing.get("style_number", "").strip() == style_number:
            merged = {**existing, **record}
            records[i] = merged
            save_wip_records(records)
            return records

    records.append(record)
    save_wip_records(records)
    return records
