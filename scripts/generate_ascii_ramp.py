#!/usr/bin/env python3
"""Renders candidate glyphs with a real font rasterizer and measures their
actual ink coverage and directional "lean" (where their mass sits within the
cell), instead of hand-guessing a brightness ramp and a fixed edge-character
set by eye.

Two things come out of this and get baked into
frontend/src/ascii/generatedGlyphs.ts (checked into source, not regenerated
at build time -- run this script by hand and commit the output when the
candidate glyph set changes):

1. A brightness ramp with more graduations than the hand-picked
   " .'`,:;~-+=*#%&8@$", built from measured % ink coverage (mean pixel
   intensity over the glyph's render) rather than guessed visual density --
   this also pulls in non-ASCII block/shade glyphs for finer steps than the
   ASCII repertoire alone provides.

2. A contour table: for 8 compass directions, the glyph (from a smaller
   "edge-ish" candidate set: lines, slashes, corners, partial blocks) whose
   own rendered mass leans most strongly in that direction. SpinningShape's
   silhouette/edge rendering picks from this instead of a hardcoded
   {-, /, |, \\} set, so an edge glyph's actual printed shape -- not just an
   arbitrary label -- approximates the local surface tangent.

Usage: python3 scripts/generate_ascii_ramp.py
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_TS = REPO_ROOT / "frontend" / "src" / "ascii" / "generatedGlyphs.ts"
OUTPUT_RS = REPO_ROOT / "wasm-ascii" / "src" / "ramp.rs"

# DejaVu Sans Mono ships on essentially every Linux box (it's the Matplotlib
# fallback font too) and has solid coverage of the Unicode block/shade
# ranges used below, so the rendering this script measures is what the
# eventual GitHub Actions/CI environment would also produce if this were
# ever re-run there -- no dependency on a font that's only on one dev
# machine.
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_SIZE = 44
# Canvas deliberately larger than the font size (not just big enough to fit
# the tallest glyph) -- a canvas sized exactly to one glyph's bbox leaves
# zero centering margin for glyphs whose own bbox height equals the canvas,
# which clips part of the glyph off one edge and skews the measured
# centroid toward the opposite edge (e.g. "|" rendered as a uniform full-
# height bar measured as leaning hard toward the top, simply because the
# bottom got clipped rather than because the glyph is actually top-heavy).
CELL = 80

# Candidates for the brightness ramp: classic ASCII density progression plus
# the Unicode block-element / shade ranges, which fill in graduations ASCII
# alone is too coarse for.
RAMP_CANDIDATES = list(
    " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"
    "░▒▓█"  # light/medium/dark shade, full block
    "▀▄"  # upper half block, lower half block
    "▌▐"  # left half block, right half block
    "▖▗▘▝"  # quadrant blocks
    "▪▫■□"  # small/large squares
    "·•"  # middle dot, bullet
)

# Directional contour table, keyed by Unicode half/quadrant block glyphs --
# unlike the brightness ramp, these glyphs' *direction* is unambiguous from
# their own Unicode names (U+2580 UPPER HALF BLOCK, U+259D QUADRANT UPPER
# RIGHT, etc.), so it's hand-assigned here rather than re-derived from a
# measured pixel centroid. A centroid-lean measurement was tried first (see
# git history) but DejaVu Sans Mono's actual glyph metrics for "|", "/",
# "\\" etc. aren't vertically centered within their own advance box the way
# a naive measurement assumes, which produced systematically wrong
# directions for line glyphs -- block-element glyphs don't have that
# ambiguity since each one's filled region literally *is* the named
# direction. coverage() below is still used to confirm the installed font
# actually renders each glyph as non-blank (catching a missing-glyph tofu
# box) rather than to derive direction.
COMPASS_DIRECTIONS = 8  # N, NE, E, SE, S, SW, W, NW
CONTOUR_BY_DIRECTION = ["▀", "▝", "▐", "▗", "▄", "▖", "▌", "▘"]
CONTOUR_FALLBACK_BY_DIRECTION = ["-", "/", "|", "\\", "-", "/", "|", "\\"]


def render_glyph(font: ImageFont.FreeTypeFont, ch: str) -> Image.Image:
    img = Image.new("L", (CELL, CELL), color=0)
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), ch, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (CELL - w) / 2 - bbox[0]
    y = (CELL - h) / 2 - bbox[1]
    draw.text((x, y), ch, font=font, fill=255)
    return img


def coverage(img: Image.Image) -> float:
    pixels = list(img.getdata())
    return sum(pixels) / (255.0 * len(pixels))


def build_ramp(font: ImageFont.FreeTypeFont) -> str:
    scored = []
    for ch in dict.fromkeys(RAMP_CANDIDATES):  # de-dupe, keep order
        if ch == " ":
            scored.append((0.0, ch))
            continue
        scored.append((coverage(render_glyph(font, ch)), ch))
    scored.sort(key=lambda pair: pair[0])
    # Collapse near-duplicate coverage levels (within 0.15%) to keep the
    # ramp's graduations meaningfully distinct rather than padded with
    # glyphs that render almost identically, while still being noticeably
    # finer-grained than the old 19-character hand-picked ramp.
    ramp: list[str] = []
    last_cov = -1.0
    for cov, ch in scored:
        if cov - last_cov < 0.0015 and ramp:
            continue
        ramp.append(ch)
        last_cov = cov
    return "".join(ramp)


def build_contour_table(font: ImageFont.FreeTypeFont) -> list[str]:
    table = []
    for i in range(COMPASS_DIRECTIONS):
        block_ch = CONTOUR_BY_DIRECTION[i]
        if coverage(render_glyph(font, block_ch)) > 0.01:
            table.append(block_ch)
        else:
            table.append(CONTOUR_FALLBACK_BY_DIRECTION[i])
    return table


def ts_string_literal(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def main() -> None:
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    ramp = build_ramp(font)
    contour_table = build_contour_table(font)

    ts_lines = [
        "// GENERATED by scripts/generate_ascii_ramp.py -- do not hand-edit.",
        "// Re-run the script and commit this file if the candidate glyph sets",
        "// in that script change.",
        "",
        f"export const GENERATED_RAMP: string = {ts_string_literal(ramp)};",
        "",
        "// Indexed by an 8-way compass bucket (0 = up/north, going clockwise),",
        "// matching the bucketing in shapes.ts's silhouetteChar().",
        "export const CONTOUR_GLYPHS: string[] = "
        + json.dumps(contour_table)
        + ";",
        "",
    ]
    OUTPUT_TS.write_text("\n".join(ts_lines))
    print(f"wrote {OUTPUT_TS} ({len(ramp)} ramp glyphs)")

    rust_lines = [
        "// Default brightness ramp, darkest -> brightest. GENERATED by",
        "// scripts/generate_ascii_ramp.py from measured glyph ink coverage --",
        "// kept in sync with frontend/src/ascii/generatedGlyphs.ts's",
        "// GENERATED_RAMP by re-running that script, not by hand.",
        f'pub const DEFAULT_RAMP: &str = {rust_str_literal(ramp)};',
        "",
        "pub fn char_for_brightness(brightness: f32, ramp: &str) -> char {",
        "    let ramp = if ramp.is_empty() { DEFAULT_RAMP } else { ramp };",
        "    let chars: Vec<char> = ramp.chars().collect();",
        "    let clamped = brightness.clamp(0.0, 1.0);",
        "    let index = ((clamped * (chars.len() - 1) as f32).floor() as usize).min(chars.len() - 1);",
        "    chars[index]",
        "}",
        "",
    ]
    OUTPUT_RS.write_text("\n".join(rust_lines))
    print(f"wrote {OUTPUT_RS}")


def rust_str_literal(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


if __name__ == "__main__":
    main()
