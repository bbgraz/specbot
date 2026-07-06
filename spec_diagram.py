"""Rendered POM spec diagrams — the measured-flat drawing of a tech pack.

Draws a schematic garment flat for the style's category with numbered
dimension callouts. Numbers match the row order of the measurement table,
and a legend below the flat maps every number to its POM name and target.
Positions are category-conventional (chest line across the chest, body
length down the side, etc.) — a schematic, not a rescaled rendering of the
uploaded sketch.
"""

from __future__ import annotations

import io
import math
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from spec_blocks import match_category

_W = 1000
_LINE = (31, 41, 55)        # slate
_DIM = (37, 99, 235)        # blue dimension lines
_LEGEND_MISSING = (120, 120, 120)


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def _arrow_line(draw: ImageDraw.ImageDraw, x1, y1, x2, y2, color=_DIM, width=3) -> None:
    draw.line((x1, y1, x2, y2), fill=color, width=width)
    angle = math.atan2(y2 - y1, x2 - x1)
    for (px, py, a) in ((x2, y2, angle), (x1, y1, angle + math.pi)):
        for spread in (math.radians(25), -math.radians(25)):
            draw.line(
                (px, py, px - 14 * math.cos(a + spread), py - 14 * math.sin(a + spread)),
                fill=color,
                width=width,
            )


def _marker(draw: ImageDraw.ImageDraw, x, y, number: int) -> None:
    r = 17
    draw.ellipse((x - r, y - r, x + r, y + r), fill="white", outline=_DIM, width=3)
    draw.text((x, y), str(number), fill=_DIM, font=_font(20), anchor="mm")


def _poly(draw: ImageDraw.ImageDraw, points, width=4) -> None:
    draw.line(list(points) + [points[0]], fill=_LINE, width=width, joint="curve")


# ---------------------------------------------------------------------------
# Category flats: outline drawing + POM anchor lines
# Each anchor: (keywords, (x1, y1, x2, y2))
# ---------------------------------------------------------------------------


def _tee(draw, long_body: bool = False, long_sleeve: bool = False, hood: bool = False):
    hem = 1080 if long_body else 880
    hem_l, hem_r = (300, 700) if long_body else (330, 670)
    if long_sleeve:
        sleeve_out = [(150, 300), (155, 730), (250, 765), (330, 430)]
        sleeve_out_r = [(670, 430), (750, 765), (845, 730), (850, 300)]
    else:
        sleeve_out = [(150, 300), (185, 420), (330, 430)]
        sleeve_out_r = [(670, 430), (815, 420), (850, 300)]
    points = (
        [(430, 220), (270, 220)]
        + sleeve_out
        + [(330 if not long_body else 330, 430), (hem_l, hem)]
        + [(hem_r, hem), (670, 430)]
        + sleeve_out_r
        + [(730, 220), (570, 220)]
    )
    _poly(draw, points)
    draw.arc((430, 190, 570, 300), 0, 180, fill=_LINE, width=4)  # front neck
    if hood:
        draw.arc((400, 60, 600, 260), 180, 360, fill=_LINE, width=4)
        draw.line((400, 160, 430, 220), fill=_LINE, width=4)
        draw.line((600, 160, 570, 220), fill=_LINE, width=4)

    anchors = [
        (("chest",), (330, 470, 670, 470)),
        (("waist",), (330, 650, 670, 650)),
        (("hip",), (330, 800 if long_body else 760, 670, 800 if long_body else 760)),
        (("hem sweep", "bottom"), (hem_l, hem - 20, hem_r, hem - 20)),
        (("body length", "front length", "back length"), (930, 220, 930, hem)),
        (("shoulder",), (270, 175, 730, 175)),
        (("neck width",), (430, 140, 570, 140)),
        (("neck drop",), (500, 222, 500, 278)),
        (("armhole",), (640, 225, 640, 430)),
    ]
    if long_sleeve:
        anchors += [
            (("sleeve length",), (735, 225, 840, 725)),
            (("cuff opening", "sleeve opening"), (160, 735, 245, 760)),
            (("cuff height",), (215, 700, 250, 758)),
        ]
    else:
        anchors += [
            (("sleeve length",), (735, 225, 812, 415)),
            (("sleeve opening", "cuff opening"), (190, 425, 325, 432)),
        ]
    if hood:
        anchors += [
            (("hood height",), (650, 65, 650, 218)),
            (("hood width",), (405, 55, 595, 55)),
        ]
    return anchors, hem + 30


def _pants(draw, short: bool = False):
    hem = 560 if short else 1020
    points = [
        (340, 150), (660, 150), (690, 420), (640, hem), (525, hem),
        (500, 450), (475, hem), (360, hem), (310, 420),
    ]
    _poly(draw, points)
    draw.line((340, 210, 660, 210), fill=_LINE, width=3)  # waistband
    anchors = [
        (("waist",), (340, 178, 660, 178)),
        (("hip",), (322, 330, 678, 330)),
        (("front rise",), (540, 152, 540, 448)),
        (("back rise",), (585, 152, 585, 448)),
        (("thigh",), (316, 500, 492, 500)),
        (("inseam",), (492, 470, 448, hem - 12)),
        (("leg opening",), (362, hem - 22, 473, hem - 22)),
    ]
    if not short:
        anchors.append((("knee",), (333, 760, 481, 760)))
    return anchors, hem + 30


def _skirt(draw):
    points = [(360, 150), (640, 150), (720, 760), (280, 760)]
    _poly(draw, points)
    draw.line((360, 205, 640, 205), fill=_LINE, width=3)
    anchors = [
        (("waist",), (360, 175, 640, 175)),
        (("hip",), (340, 330, 660, 330)),
        (("front length", "body length"), (790, 150, 790, 760)),
        (("hem sweep", "sweep", "bottom"), (285, 740, 715, 740)),
    ]
    return anchors, 790


def render_spec_diagram(tech_pack: dict[str, Any]) -> bytes:
    """Render the measured-flat diagram as PNG bytes."""
    measurements = tech_pack.get("measurements", []) or []
    category = match_category(tech_pack.get("garment_type") or "")

    # Draw the garment on a working canvas first.
    garment = Image.new("RGB", (_W, 1200), "white")
    draw = ImageDraw.Draw(garment)
    if category in ("pants",):
        anchors, garment_bottom = _pants(draw)
    elif category == "shorts":
        anchors, garment_bottom = _pants(draw, short=True)
    elif category == "skirt":
        anchors, garment_bottom = _skirt(draw)
    elif category == "sweatshirt":
        anchors, garment_bottom = _tee(draw, long_body=False, long_sleeve=True, hood=True)
    elif category == "dress":
        anchors, garment_bottom = _tee(draw, long_body=True)
    else:  # tee, polo, tank, woven_shirt, jacket, default
        long_sleeve = category in ("woven_shirt", "jacket")
        anchors, garment_bottom = _tee(draw, long_sleeve=long_sleeve)

    # Place numbered dimension lines for POMs we can anchor.
    used: set[int] = set()
    legend: list[tuple[int, str, str, bool]] = []
    for i, m in enumerate(measurements):
        number = i + 1
        pom = (m.get("pom") or "").strip()
        target = str(m.get("target") or "").strip()
        name = pom.lower()
        placed = False
        for j, (keywords, line) in enumerate(anchors):
            if j in used:
                continue
            if any(k in name for k in keywords):
                x1, y1, x2, y2 = line
                _arrow_line(draw, x1, y1, x2, y2)
                _marker(draw, (x1 + x2) / 2, (y1 + y2) / 2, number)
                used.add(j)
                placed = True
                break
        legend.append((number, pom, target, placed))

    # Compose final image: title + garment + legend.
    legend_font = _font(22)
    row_h = 38
    rows_per_col = max(1, math.ceil(len(legend) / 2))
    legend_h = rows_per_col * row_h + 70
    total_h = garment_bottom + 40 + legend_h + 30

    img = Image.new("RGB", (_W, total_h), "white")
    img.paste(garment.crop((0, 0, _W, garment_bottom + 20)), (0, 20))
    d = ImageDraw.Draw(img)
    style = f"{tech_pack.get('style_number') or ''} | {tech_pack.get('style_name') or ''}".strip(" |")
    d.text((20, 4), f"POM diagram - {style}", fill=_LINE, font=_font(26))

    y0 = garment_bottom + 60
    d.line((20, y0 - 18, _W - 20, y0 - 18), fill=(200, 200, 200), width=2)
    for i, (number, pom, target, placed) in enumerate(legend):
        col = 0 if i < rows_per_col else 1
        x = 30 + col * (_W // 2)
        y = y0 + (i % rows_per_col) * row_h
        color = _DIM if placed else _LEGEND_MISSING
        r = 14
        d.ellipse((x, y, x + 2 * r, y + 2 * r), outline=color, width=3)
        d.text((x + r, y + r), str(number), fill=color, font=_font(18), anchor="mm")
        suffix = "" if placed else "  (legend only)"
        target_part = f" - {target} in" if target else ""
        d.text((x + 2 * r + 12, y + r), f"{pom}{target_part}{suffix}",
               fill=_LINE if placed else _LEGEND_MISSING, font=legend_font, anchor="lm")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
