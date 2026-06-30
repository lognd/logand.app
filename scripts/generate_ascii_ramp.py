#!/usr/bin/env python3
"""Renders candidate glyphs with a real font rasterizer and measures their
actual ink coverage and shape, instead of hand-guessing a brightness ramp
and a fixed edge-character set by eye.

Three things come out of this and get baked into
frontend/src/ascii/generatedGlyphs.ts (checked into source, not regenerated
at build time -- run this script by hand and commit the output when the
candidate glyph set changes):

1. A brightness ramp with more graduations than the hand-picked
   " .'`,:;~-+=*#%&8@$", built from measured % ink coverage (mean pixel
   intensity over the glyph's render). Candidates are restricted to glyphs
   "typically found in text" (printable ASCII, no Unicode block/shade
   elements) -- selected via even binning across the measured coverage
   range so the ramp doesn't cluster around a few characters whose coverage
   happens to be close together while leaving gaps elsewhere ("some
   characters saturate sections").

2. CONTOUR_GLYPHS_TEXT: a per-orientation table of ordinary text glyphs for
   silhouette/edge rendering. For each candidate, this computes the
   glyph's own principal axis -- the single straight line through its
   center of mass that best captures its overall "lean" (the same
   PCA/second-moment technique used to find a shape's major axis in image
   processing) -- then groups candidates by that axis's orientation so a
   silhouette point can be matched to whichever ordinary character's own
   ink most resembles a boundary running in that direction.

3. CONTOUR_GLYPHS_BLOCK: the same idea but restricted to Unicode half/
   quadrant block glyphs, kept as a separate, explicitly-opted-into table
   for the globe specifically (its lighting model already treats it
   differently -- see shapes.ts) rather than removed outright.

Usage: python3 scripts/generate_ascii_ramp.py
"""

import json
import math
import string
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_TS = REPO_ROOT / "frontend" / "src" / "ascii" / "generatedGlyphs.ts"
OUTPUT_RS = REPO_ROOT / "wasm-ascii" / "src" / "ramp.rs"

# DejaVu Sans Mono ships on essentially every Linux box (it's the Matplotlib
# fallback font too), so the rendering this script measures is what the
# eventual GitHub Actions/CI environment would also produce if this were
# ever re-run there -- no dependency on a font that's only on one dev
# machine.
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_SIZE = 44
# Canvas deliberately larger than the font size (not just big enough to fit
# the tallest glyph) -- a canvas sized exactly to one glyph's bbox leaves
# zero centering margin for glyphs whose own bbox height equals the canvas,
# which clips part of the glyph off one edge and skews the measured mass
# position toward the opposite edge (e.g. "|" rendered as a uniform full-
# height bar measured as leaning hard toward the top, simply because the
# bottom got clipped rather than because the glyph is actually top-heavy).
CELL = 80

# "All characters should be typically found in text including symbols" --
# every printable ASCII character (letters, digits, standard punctuation/
# symbols), explicitly NOT Unicode block/shade elements, for both the
# brightness ramp and the (text) contour table.
TEXT_CANDIDATES = [c for c in (string.digits + string.ascii_letters + string.punctuation)]

RAMP_GRADUATIONS = 32

# Kept as an explicit, separate table per "actually, keep the box
# characters for the globe" -- the sphere/globe still uses its own
# already-distinctive view-facing lighting (see shapes.ts), and unlike a
# flat-faced cube or a donut, the globe's silhouette is densely curved in
# every direction, where a block glyph's unambiguous named direction reads
# better than a thin text-glyph line at the latitude/longitude ring density
# it renders at.
BLOCK_CONTOUR_DIRECTIONS = 8  # N, NE, E, SE, S, SW, W, NW
BLOCK_CONTOUR_BY_DIRECTION = ["▀", "▝", "▐", "▗", "▄", "▖", "▌", "▘"]
BLOCK_CONTOUR_FALLBACK = ["-", "/", "|", "\\", "-", "/", "|", "\\"]

# Orientation is only meaningful mod 180 degrees (a line and its reverse
# describe the same boundary direction), so the text-contour table buckets
# across a half-turn, not a full turn.
TEXT_CONTOUR_BUCKETS = 8

# Below this eccentricity (ratio of the principal-axis spread to the
# perpendicular spread), a glyph's mass distribution is too close to round/
# isotropic for any single line to "most accurately capture" it -- e.g. "o"
# or "8" don't have a real dominant axis the way "/" or "l" do, so they're
# excluded from the contour candidate pool entirely rather than forced into
# a bucket they don't actually represent well.
MIN_ECCENTRICITY = 0.25


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


def principal_axis(img: Image.Image) -> tuple[float, float] | None:
    """Returns (angle_radians, eccentricity) of the glyph's principal axis
    -- the line through its center of mass it's most "elongated" along --
    computed from the second-order moments of its pixel mass distribution,
    or None if the glyph has no ink at all.

    This is "the line across the glyph that most accurately captures [its]
    boundary": for an asymmetric glyph like "/" the major axis runs along
    the visible stroke; for a glyph like "|" it runs vertically even though
    the center of mass itself sits dead-center (centroid position alone
    can't distinguish "|" from "o" -- the *spread* of mass around that
    centroid is what does).
    """
    w, h = img.size
    total = 0.0
    sx = sy = 0.0
    for yy in range(h):
        for xx in range(w):
            v = img.getpixel((xx, yy))
            if v <= 0:
                continue
            total += v
            sx += v * xx
            sy += v * yy
    if total == 0:
        return None
    cx, cy = sx / total, sy / total

    mu_xx = mu_yy = mu_xy = 0.0
    for yy in range(h):
        for xx in range(w):
            v = img.getpixel((xx, yy))
            if v <= 0:
                continue
            dx, dy = xx - cx, yy - cy
            mu_xx += v * dx * dx
            mu_yy += v * dy * dy
            mu_xy += v * dx * dy
    mu_xx /= total
    mu_yy /= total
    mu_xy /= total

    angle = 0.5 * math.atan2(2 * mu_xy, mu_xx - mu_yy)
    # Eigenvalues of the 2x2 moment matrix -- their ratio is how elongated
    # vs. round the mass distribution is.
    common = math.sqrt((mu_xx - mu_yy) ** 2 + 4 * mu_xy * mu_xy)
    lambda1 = (mu_xx + mu_yy + common) / 2
    lambda2 = (mu_xx + mu_yy - common) / 2
    if lambda1 <= 1e-9:
        return None
    eccentricity = 1.0 - (lambda2 / lambda1)
    return angle, eccentricity


def build_ramp(font: ImageFont.FreeTypeFont) -> str:
    scored = [(0.0, " ")]
    for ch in dict.fromkeys(TEXT_CANDIDATES):
        scored.append((coverage(render_glyph(font, ch)), ch))
    scored.sort(key=lambda pair: pair[0])

    # Even binning across the full measured coverage range, not a fixed
    # "skip if too close to the last pick" gap -- a fixed gap still lets
    # multiple picks cluster in a dense region of the candidate pool (many
    # punctuation marks render within a hair of each other) while leaving
    # a visible jump elsewhere ("some characters saturate sections, [I
    # want] a good distribution"). Binning guarantees one representative
    # roughly every 1/RAMP_GRADUATIONS of the actual range.
    lo, hi = scored[0][0], scored[-1][0]
    span = hi - lo or 1.0
    used_chars: set[str] = set()
    ramp: list[str] = []
    for i in range(RAMP_GRADUATIONS):
        target = lo + (i / (RAMP_GRADUATIONS - 1)) * span
        best_ch, best_dist = None, math.inf
        for cov, ch in scored:
            if ch in used_chars:
                continue
            dist = abs(cov - target)
            if dist < best_dist:
                best_ch, best_dist = ch, dist
        if best_ch is not None:
            used_chars.add(best_ch)
            ramp.append(best_ch)
    ramp.sort(key=lambda ch: next(cov for cov, c in scored if c == ch))
    return "".join(ramp)


def build_text_contour_table(font: ImageFont.FreeTypeFont) -> list[str]:
    candidates: list[tuple[str, float, float]] = []  # (char, angle, eccentricity)
    for ch in dict.fromkeys(TEXT_CANDIDATES):
        result = principal_axis(render_glyph(font, ch))
        if result is None:
            continue
        angle, eccentricity = result
        if eccentricity < MIN_ECCENTRICITY:
            continue
        candidates.append((ch, angle % math.pi, eccentricity))

    table = []
    for i in range(TEXT_CONTOUR_BUCKETS):
        bucket_angle = (i / TEXT_CONTOUR_BUCKETS) * math.pi
        best_ch, best_score = "-", -math.inf
        for ch, angle, eccentricity in candidates:
            # Angular distance on a half-turn (mod pi) circle.
            diff = abs(angle - bucket_angle)
            diff = min(diff, math.pi - diff)
            # Prefer a close angle match; break ties toward more strongly
            # elongated (more unambiguously "line-shaped") glyphs.
            score = -diff * 4 + eccentricity
            if score > best_score:
                best_ch, best_score = ch, score
        table.append(best_ch)
    return table


def build_block_contour_table(font: ImageFont.FreeTypeFont) -> list[str]:
    table = []
    for i in range(BLOCK_CONTOUR_DIRECTIONS):
        block_ch = BLOCK_CONTOUR_BY_DIRECTION[i]
        if coverage(render_glyph(font, block_ch)) > 0.01:
            table.append(block_ch)
        else:
            table.append(BLOCK_CONTOUR_FALLBACK[i])
    return table


def ts_string_literal(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def main() -> None:
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    ramp = build_ramp(font)
    text_contour = build_text_contour_table(font)
    block_contour = build_block_contour_table(font)

    ts_lines = [
        "// GENERATED by scripts/generate_ascii_ramp.py -- do not hand-edit.",
        "// Re-run the script and commit this file if the candidate glyph sets",
        "// in that script change.",
        "",
        f"export const GENERATED_RAMP: string = {ts_string_literal(ramp)};",
        "",
        "// Indexed by an 8-way bucket across a half-turn (0 = horizontal,",
        "// going toward vertical and back) -- matching shapes.ts's",
        "// silhouetteChar(). Ordinary text glyphs, picked by which one's own",
        "// principal mass-axis most closely matches that bucket's boundary",
        "// orientation.",
        "export const CONTOUR_GLYPHS_TEXT: string[] = " + json.dumps(text_contour) + ";",
        "",
        "// Same idea, restricted to Unicode half/quadrant block glyphs --",
        "// reserved for the sphere/globe shape specifically (see shapes.ts).",
        "export const CONTOUR_GLYPHS_BLOCK: string[] = " + json.dumps(block_contour) + ";",
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
