"""Apply freeform fitting notes to a tech pack and produce change-log entries.

Uses GPT-4o when OPENAI_API_KEY is available; otherwise falls back to a small
rule-based parser so the demo still runs offline.
"""

from __future__ import annotations

import copy
import os
import re
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_number(text: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _format_number(value: float) -> str:
    if value == int(value):
        return f"{int(value)}"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _find_pom(measurements: list[dict[str, Any]], pom_query: str) -> int | None:
    """Return the index of the first POM whose name fuzzy-matches the query."""
    if not pom_query:
        return None
    q = pom_query.strip().lower()
    for i, m in enumerate(measurements):
        if m.get("pom", "").strip().lower() == q:
            return i
    for i, m in enumerate(measurements):
        name = m.get("pom", "").strip().lower()
        if q in name or name in q:
            return i
    return None


def _add_change_log(
    tech_pack: dict[str, Any],
    pom: str,
    field: str,
    old_value: str,
    new_value: str,
    reason: str,
) -> None:
    tech_pack.setdefault("change_log", []).append(
        {
            "timestamp": _now_iso(),
            "pom": pom,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "reason": reason,
        }
    )


# ---------------------------------------------------------------------------
# Rule-based fallback parser
# ---------------------------------------------------------------------------

_RULE_PATTERNS = [
    # "raise armhole by 0.5"
    re.compile(
        r"(?P<verb>raise|lower|increase|decrease|reduce|add|drop|let out|take in|shorten|lengthen)\s+"
        r"(?P<pom>[A-Za-z][A-Za-z \-/]+?)\s+by\s+(?P<amount>-?\d+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
    # "armhole +0.5" / "chest -0.25"
    re.compile(
        r"(?P<pom>[A-Za-z][A-Za-z \-/]+?)\s+(?P<sign>[+\-])\s*(?P<amount>\d+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
    # "set chest to 20" / "chest = 20"
    re.compile(
        r"(?:set\s+)?(?P<pom>[A-Za-z][A-Za-z \-/]+?)\s+(?:to|=)\s+(?P<amount>-?\d+(?:\.\d+)?)",
        re.IGNORECASE,
    ),
]

_NEGATIVE_VERBS = {"lower", "decrease", "reduce", "drop", "take in", "shorten"}


def _split_statements(text: str) -> list[str]:
    """Split on newlines, semicolons, and sentence-ending periods.

    A period is treated as a separator only when it's followed by whitespace
    (or end of string) — this preserves decimal numbers like "0.5".
    """
    parts = re.split(r"[\n;]+|\.(?=\s|$)", text)
    return [p.strip() for p in parts if p and p.strip()]


def _rule_based_updates(fitting_notes: str) -> list[dict[str, Any]]:
    """Tiny parser used when OPENAI_API_KEY isn't set."""
    updates: list[dict[str, Any]] = []
    for line in _split_statements(fitting_notes):
        for pattern in _RULE_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            groups = match.groupdict()
            pom = groups.get("pom", "").strip()
            amount = _parse_number(groups.get("amount", ""))
            if not pom or amount is None:
                continue

            if "verb" in groups and groups["verb"]:
                verb = groups["verb"].lower()
                signed = -amount if verb in _NEGATIVE_VERBS else amount
                updates.append(
                    {
                        "pom": pom,
                        "delta": _format_number(signed),
                        "new_target": None,
                        "tolerance_plus": None,
                        "tolerance_minus": None,
                        "action": "update",
                        "reason": line,
                    }
                )
            elif "sign" in groups and groups.get("sign"):
                signed = amount if groups["sign"] == "+" else -amount
                updates.append(
                    {
                        "pom": pom,
                        "delta": _format_number(signed),
                        "new_target": None,
                        "tolerance_plus": None,
                        "tolerance_minus": None,
                        "action": "update",
                        "reason": line,
                    }
                )
            else:
                updates.append(
                    {
                        "pom": pom,
                        "delta": None,
                        "new_target": _format_number(amount),
                        "tolerance_plus": None,
                        "tolerance_minus": None,
                        "action": "update",
                        "reason": line,
                    }
                )
            break  # one update per line
    return updates


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _apply_update(tech_pack: dict[str, Any], update: dict[str, Any]) -> None:
    measurements = tech_pack.setdefault("measurements", [])
    pom = (update.get("pom") or "").strip()
    if not pom:
        return

    reason = update.get("reason") or "fitting note"
    idx = _find_pom(measurements, pom)
    action = update.get("action") or ("update" if idx is not None else "add")

    if action == "add" or idx is None:
        new_target = update.get("new_target")
        if new_target is None and update.get("delta") is not None:
            # No baseline to apply a delta to → record as placeholder.
            new_target = update.get("delta")
        new_row = {
            "pom": pom,
            "description": "",
            "target": new_target or "",
            "tolerance_plus": update.get("tolerance_plus") or "0.25",
            "tolerance_minus": update.get("tolerance_minus") or "0.25",
            "source": "fitting_note",
            "notes": reason,
        }
        measurements.append(new_row)
        _add_change_log(
            tech_pack,
            pom,
            "row",
            "(none)",
            f"target={new_row['target']}",
            reason,
        )
        return

    row = measurements[idx]

    if update.get("new_target") is not None:
        old = row.get("target", "")
        row["target"] = update["new_target"]
        _add_change_log(tech_pack, row["pom"], "target", str(old), str(row["target"]), reason)
    elif update.get("delta") is not None:
        delta = _parse_number(str(update["delta"]))
        baseline = _parse_number(str(row.get("target", "")))
        if delta is not None and baseline is not None:
            old = row.get("target", "")
            new_value = _format_number(baseline + delta)
            row["target"] = new_value
            _add_change_log(
                tech_pack,
                row["pom"],
                "target",
                str(old),
                str(new_value),
                f"{reason} (delta {update['delta']})",
            )
        else:
            _add_change_log(
                tech_pack,
                row["pom"],
                "target",
                str(row.get("target", "")),
                str(row.get("target", "")),
                f"Could not apply delta '{update.get('delta')}' — non-numeric. Note: {reason}",
            )

    if update.get("tolerance_plus"):
        old = row.get("tolerance_plus", "")
        row["tolerance_plus"] = update["tolerance_plus"]
        _add_change_log(
            tech_pack, row["pom"], "tolerance_plus", str(old), str(row["tolerance_plus"]), reason
        )
    if update.get("tolerance_minus"):
        old = row.get("tolerance_minus", "")
        row["tolerance_minus"] = update["tolerance_minus"]
        _add_change_log(
            tech_pack,
            row["pom"],
            "tolerance_minus",
            str(old),
            str(row["tolerance_minus"]),
            reason,
        )


def apply_fitting_notes(
    tech_pack: dict[str, Any], fitting_notes: str
) -> dict[str, Any]:
    """Return a *new* tech pack with fitting notes applied and change log entries appended."""
    if not fitting_notes or not fitting_notes.strip():
        return copy.deepcopy(tech_pack)

    revised = copy.deepcopy(tech_pack)

    updates: list[dict[str, Any]] = []
    use_gpt = bool(os.getenv("OPENAI_API_KEY"))
    if use_gpt:
        try:
            from gpt_service import reason_fitting_notes

            result = reason_fitting_notes(revised, fitting_notes)
            updates = result.get("updates", []) or []
        except Exception as exc:  # noqa: BLE001 - demo fallback
            revised.setdefault("missing_information", []).append(
                f"GPT fitting-note interpretation failed ({exc}). Used rule-based fallback."
            )
            updates = _rule_based_updates(fitting_notes)
    else:
        updates = _rule_based_updates(fitting_notes)

    if not updates:
        _add_change_log(
            revised,
            "(unmatched)",
            "note",
            "",
            "",
            f"Fitting note received but no actionable update parsed: {fitting_notes.strip()[:200]}",
        )
        return revised

    for update in updates:
        _apply_update(revised, update)

    return revised
