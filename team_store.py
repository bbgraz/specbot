"""Local JSON-backed pitch-squad roster with a PTO / holiday tracker.

Mirrors wip_store.py: a small, pure-JSON file edited live during a demo.
The roster carries each squad member's RACI role plus their out-of-office
(OOO) date ranges. A roster-wide holiday list is matched to members by
region, so public holidays don't have to be entered for each person.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

_DEFAULT_TEAM_PATH = Path(__file__).resolve().parent / "team_roster.json"
TEAM_PATH = Path(os.getenv("SPECBOT_TEAM_PATH") or _DEFAULT_TEAM_PATH)

# RACI — who is Responsible / Accountable / Consulted / Informed on the pitch.
RACI_ROLES: list[str] = ["Responsible", "Accountable", "Consulted", "Informed"]

OOO_TYPES: list[str] = [
    "PTO",
    "Public holiday",
    "Sick",
    "Conference / travel",
    "Partial day",
]


def _empty_team() -> dict[str, Any]:
    return {"squad_name": "Pitch Squad", "members": [], "holidays": []}


def load_team() -> dict[str, Any]:
    if not TEAM_PATH.is_file():
        return _empty_team()
    try:
        with TEAM_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return _empty_team()
    if not isinstance(data, dict):
        return _empty_team()
    data.setdefault("squad_name", "Pitch Squad")
    data.setdefault("members", [])
    data.setdefault("holidays", [])
    for member in data["members"]:
        member.setdefault("ooo", [])
    return data


def save_team(team: dict[str, Any]) -> None:
    TEAM_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TEAM_PATH.open("w", encoding="utf-8") as fh:
        json.dump(team, fh, indent=2)


def parse_date(value: Any) -> date | None:
    """Best-effort parse of an ISO date string / date / datetime."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def entry_covers(entry: dict[str, Any], day: date) -> bool:
    """True if an OOO entry's date range includes `day`."""
    start = parse_date(entry.get("start"))
    if start is None:
        return False
    end = parse_date(entry.get("end")) or start
    if end < start:
        start, end = end, start
    return start <= day <= end


def holiday_for_member(
    member: dict[str, Any], day: date, holidays: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the holiday that lands on `day` for this member's region, if any."""
    region = (member.get("region") or "").strip().lower()
    if not region:
        return None
    for holiday in holidays:
        if parse_date(holiday.get("date")) != day:
            continue
        h_region = (holiday.get("region") or "").strip().lower()
        if h_region and h_region in ("all", region):
            return holiday
    return None


def member_status(
    member: dict[str, Any], day: date, holidays: list[dict[str, Any]]
) -> tuple[str, dict[str, Any] | None]:
    """Return (state, detail); state is 'ooo' | 'holiday' | 'available'."""
    for entry in member.get("ooo", []):
        if entry_covers(entry, day):
            return "ooo", entry
    holiday = holiday_for_member(member, day, holidays)
    if holiday:
        return "holiday", holiday
    return "available", None


def upcoming_holidays(
    team: dict[str, Any], today: date | None = None, within_days: int = 150
) -> list[dict[str, Any]]:
    """Holidays falling within `within_days` of today, sorted soonest-first."""
    today = today or date.today()
    horizon = today + timedelta(days=within_days)
    rows: list[dict[str, Any]] = []
    for holiday in team.get("holidays", []):
        when = parse_date(holiday.get("date"))
        if when and today <= when <= horizon:
            rows.append({**holiday, "_date": when})
    rows.sort(key=lambda h: h["_date"])
    return rows
