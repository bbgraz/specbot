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


_UNICODE_FRACTIONS = {
    "¼": 0.25, "½": 0.5, "¾": 0.75,
    "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
}

# Matches: 1.25 | 3/8 | 1 1/2 | 1-1/2 | ½ | 1½   (fit comments are written in fractions)
_AMOUNT_RE = r"(?:\d+(?:\.\d+)?\s*[\-\s]\s*\d+\s*/\s*\d+|\d+\s*/\s*\d+|\d+(?:\.\d+)?[¼½¾⅛⅜⅝⅞]?|[¼½¾⅛⅜⅝⅞])"


def _parse_amount(text: str) -> float | None:
    """Parse a measurement amount: decimals, fractions, mixed numbers, unicode fractions."""
    if text is None:
        return None
    t = str(text).strip().rstrip('"”″in').strip()
    sign = 1.0
    if t.startswith("-"):
        sign, t = -1.0, t[1:].strip()
    elif t.startswith("+"):
        t = t[1:].strip()

    frac_extra = 0.0
    if t and t[-1] in _UNICODE_FRACTIONS:
        frac_extra = _UNICODE_FRACTIONS[t[-1]]
        t = t[:-1].strip()
        if not t:
            return sign * frac_extra

    # mixed number: "1 1/2" or "1-1/2"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[\-\s]\s*(\d+)\s*/\s*(\d+)", t)
    if m:
        whole, num, den = float(m.group(1)), float(m.group(2)), float(m.group(3))
        return sign * (whole + (num / den if den else 0.0))
    # plain fraction: "3/8"
    m = re.fullmatch(r"(\d+)\s*/\s*(\d+)", t)
    if m:
        num, den = float(m.group(1)), float(m.group(2))
        return sign * (num / den) if den else None
    # decimal / integer (with optional unicode fraction suffix, e.g. "1½")
    m = re.fullmatch(r"\d+(?:\.\d+)?", t)
    if m:
        return sign * (float(m.group(0)) + frac_extra)
    return None


def _parse_number(text: str) -> float | None:
    """Extract the first amount (fraction-aware) from freeform text."""
    direct = _parse_amount(text)
    if direct is not None:
        return direct
    match = re.search(rf"-?{_AMOUNT_RE}", str(text))
    if not match:
        return None
    return _parse_amount(match.group(0))


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

_VERBS = (
    r"raise|lower|increase|decrease|reduce|add|drop|let out|take in|shorten|"
    r"lengthen|extend|open up|widen|narrow|slim"
)
_POM_RE = r"[A-Za-z][A-Za-z \-/]+?"
_UNIT_RE = r"(?:\s*(?:\"|”|″|in\b|inch(?:es)?\b))?"

_RULE_PATTERNS = [
    # "raise armhole by 0.5" / "shorten sleeve length 3/8" (with or without "by")
    re.compile(
        rf"(?P<verb>{_VERBS})\s+(?:the\s+)?(?P<pom>{_POM_RE})\s+(?:by\s+)?(?P<amount>{_AMOUNT_RE}){_UNIT_RE}",
        re.IGNORECASE,
    ),
    # "add 1/2 to chest" / "take in 0.25 at waist"
    re.compile(
        rf"(?P<verb>{_VERBS})\s+(?P<amount>{_AMOUNT_RE}){_UNIT_RE}\s+(?:to|at|on|from)\s+(?:the\s+)?(?P<pom>{_POM_RE})\s*$",
        re.IGNORECASE,
    ),
    # "armhole +0.5" / "chest -1/4"
    re.compile(
        rf"(?P<pom>{_POM_RE})\s*(?P<sign>[+\-])\s*(?P<amount>{_AMOUNT_RE}){_UNIT_RE}",
        re.IGNORECASE,
    ),
    # "set chest to 20" / "chest = 20"
    re.compile(
        rf"(?:set\s+)?(?P<pom>{_POM_RE})\s+(?:to|=)\s+(?P<amount>{_AMOUNT_RE}){_UNIT_RE}",
        re.IGNORECASE,
    ),
]

_NEGATIVE_VERBS = {"lower", "decrease", "reduce", "drop", "take in", "shorten", "narrow", "slim"}

# A line that mentions one of these (or contains a number) but produced no update
# is surfaced in the change log instead of being silently dropped.
_ACTIONABLE_HINT = re.compile(
    rf"(?:{_VERBS}|grade|move|adjust|[+\-]\s*{_AMOUNT_RE}|\d|[¼½¾⅛⅜⅝⅞])", re.IGNORECASE
)

_POM_STOPWORDS = ("the ", "at ", "on ", "front of ", "back of ")


def _clean_pom(pom: str) -> str:
    p = pom.strip()
    lowered = p.lower()
    for stop in _POM_STOPWORDS:
        if lowered.startswith(stop):
            p = p[len(stop):]
            lowered = p.lower()
    return p.strip()


def _split_statements(text: str) -> list[str]:
    """Split on newlines, semicolons, and sentence-ending periods.

    A period is treated as a separator only when it's followed by whitespace
    (or end of string) — this preserves decimal numbers like "0.5".
    """
    parts = re.split(r"[\n;]+|\.(?=\s|$)", text)
    return [p.strip() for p in parts if p and p.strip()]


def _rule_based_updates(fitting_notes: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Fraction-aware parser used when OPENAI_API_KEY isn't set.

    Returns (updates, unparsed_lines). Lines that look actionable (contain a
    number or a change verb) but produce no update are returned so the caller
    can surface them — a dropped fit comment must never be silent.
    """
    updates: list[dict[str, Any]] = []
    unparsed: list[str] = []
    for line in _split_statements(fitting_notes):
        matched = False
        for pattern in _RULE_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            groups = match.groupdict()
            pom = _clean_pom(groups.get("pom", ""))
            amount = _parse_amount(groups.get("amount", ""))
            if not pom or amount is None:
                continue
            matched = True

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
        if not matched and _ACTIONABLE_HINT.search(line):
            unparsed.append(line)
    return updates, unparsed


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
            # Plausibility cap: a fit adjustment rarely moves a POM by more
            # than ~30% of itself. Flag instead of silently corrupting the spec.
            if baseline > 0 and abs(delta) >= 0.75 and abs(delta) > 0.3 * baseline:
                _add_change_log(
                    tech_pack,
                    row["pom"],
                    "target",
                    str(row.get("target", "")),
                    str(row.get("target", "")),
                    f"NOT APPLIED — delta {_format_number(delta)}\" is "
                    f">{0.3:.0%} of current {_format_number(baseline)}\"; "
                    f"review and apply manually if intended. Note: {reason}",
                )
                return
            old = row.get("target", "")
            new_value = _format_number(max(0.0, baseline + delta))
            row["target"] = new_value
            _add_change_log(
                tech_pack,
                row["pom"],
                "target",
                str(old),
                str(new_value),
                f"{reason} (delta {_format_number(delta)})",
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
    unparsed: list[str] = []
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
            updates, unparsed = _rule_based_updates(fitting_notes)
    else:
        updates, unparsed = _rule_based_updates(fitting_notes)

    for line in unparsed:
        _add_change_log(
            revised,
            "(unparsed)",
            "note",
            "",
            "",
            f"NOT APPLIED — could not parse fitting note, review manually: {line}",
        )

    if not updates and not unparsed:
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
