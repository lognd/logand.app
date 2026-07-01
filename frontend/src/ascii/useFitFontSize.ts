import { useEffect, useState } from "react";

// Computes a monospace font-size (px) so a `cols` x `rows` character grid
// fills the viewport without overflowing either axis. Used by both
// AsciiCanvas and SpinningShape, which previously had no explicit sizing at
// all and rendered at the browser's inherited default font-size -- a fixed
// 80x40 (or similar) grid at ~16px is nowhere near big enough to fill a
// fixed inset-0 layer on a real viewport, which is why the noise layer
// showed up as a small, oddly-placed block ("not the correct size").
//
// FONT_STACK must match SpinningShape.tsx/AsciiCanvas.tsx's own inline
// fontFamily exactly -- it's used both to render the grid AND (via
// measureCharWidth below) to figure out how wide a glyph in it actually
// is, so a mismatch here would reintroduce the same "measured against one
// font, rendered in another" gap that caused the grid to overflow its
// container in the first place.
const FONT_STACK = '"JetBrains Mono", ui-monospace, monospace';

// A hardcoded ratio (previously 0.6, "JetBrains Mono is close to 0.6") is
// only ever an approximation -- it doesn't account for browser/OS font
// substitution, and any gap between the assumed and actual glyph width
// compounds across every column, so on a wide viewport (a fullscreened
// window is exactly when this bites hardest, since the width-constrained
// branch below produces the largest font sizes) the rendered grid ends up
// a little wider than its container and the container's overflow-hidden
// clips real content off both edges ("shapes and rain get cut off when
// fullscreening"). Measuring the actual rendered advance width of a glyph
// in FONT_STACK via canvas removes that gap entirely.
export function measureCharAspect(): number {
  if (typeof document === "undefined") return 0.6;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  if (!ctx) return 0.6;
  const referenceSize = 200; // large reference size keeps sub-pixel measurement noise negligible
  ctx.font = `${referenceSize}px ${FONT_STACK}`;
  const width = ctx.measureText("0").width;
  return width > 0 ? width / referenceSize : 0.6;
}

// Multiplies the computed font size down slightly as a safety margin --
// CSS layout rounds font-size/line-height to the nearest device pixel, and
// that rounding can push the actual rendered width a hair past what was
// computed even with an accurately measured charAspect. A 1.5% margin is
// imperceptible but guarantees the grid never exceeds its container.
const SAFETY_MARGIN = 0.985;

// Below this font size, per-glyph pixel rounding stops being negligible:
// measureCharAspect measures at a large reference size (200px) and scales
// the result down linearly, which assumes a glyph's rendered width is a
// smooth fraction of its font-size -- true at normal sizes, but at a few
// px per character the renderer snaps each glyph's advance to a whole
// device pixel, and that per-glyph rounding is a much bigger fraction of
// a tiny glyph's own width. Summed across 100+ columns, that was enough
// to overflow the container by tens of pixels on very short/zoomed-out
// viewports even with SAFETY_MARGIN applied (a fixed 1.5% margin is far
// too small relative to the actual rounding error down here). A much
// larger margin only in this small-font regime fixes that without
// affecting the normal case, where SAFETY_MARGIN alone is already enough.
const SMALL_FONT_THRESHOLD_PX = 12;
const SMALL_FONT_SAFETY_MARGIN = 0.85;

// window.innerWidth/innerHeight report the LAYOUT viewport, which on a
// pinch-zoomed mobile browser stays the same size the whole page was laid
// out at -- it's window.visualViewport (when available) that reports what
// portion of that layout is actually visible right now, shrinking as the
// user zooms in. Sizing off innerWidth/innerHeight alone meant zooming in
// didn't shrink the computed font size to match, so the grid kept
// rendering at its un-zoomed size and overflowed the now-smaller visible
// area ("zooming out is broken (Ctrl+- and Ctrl++)"). Falls back to
// window.inner* on browsers without the API (desktop Firefox before 2024,
// old Safari).
function viewportSize(): { width: number; height: number } {
  const vv = typeof window !== "undefined" ? window.visualViewport : null;
  if (vv) return { width: vv.width, height: vv.height };
  return { width: window.innerWidth, height: window.innerHeight };
}

export function useFitFontSize(
  cols: number,
  rows: number,
  charAspect?: number,
): number {
  const [fontSize, setFontSize] = useState(10);

  useEffect(() => {
    // Re-measured per mount (cheap -- one canvas measureText call) rather
    // than hardcoded, so it reflects whatever charAspect prop callers pass
    // (tests/storybook can still override it) or the real measured value
    // otherwise.
    const aspect = charAspect ?? measureCharAspect();

    function recompute() {
      const { width, height } = viewportSize();
      const sizeForWidth = width / (cols * aspect);
      const sizeForHeight = height / rows;
      const raw = Math.min(sizeForWidth, sizeForHeight);
      const margin = raw < SMALL_FONT_THRESHOLD_PX ? SMALL_FONT_SAFETY_MARGIN : SAFETY_MARGIN;
      setFontSize(Math.max(4, raw * margin));
    }
    recompute();
    // "resize" alone isn't reliably fired by every browser's Fullscreen
    // API transition -- "fullscreenchange" is the dedicated event for
    // exactly that state change, and orientationchange covers mobile
    // rotation, which can also change the effective viewport without a
    // "resize" event firing first on some browsers. visualViewport's own
    // "resize" is what actually fires on pinch-zoom/page-zoom scale
    // changes (see viewportSize's doc comment) -- window's "resize" isn't
    // guaranteed to fire for those on every browser.
    window.addEventListener("resize", recompute);
    document.addEventListener("fullscreenchange", recompute);
    window.addEventListener("orientationchange", recompute);
    window.visualViewport?.addEventListener("resize", recompute);
    return () => {
      window.removeEventListener("resize", recompute);
      document.removeEventListener("fullscreenchange", recompute);
      window.removeEventListener("orientationchange", recompute);
      window.visualViewport?.removeEventListener("resize", recompute);
    };
  }, [cols, rows, charAspect]);

  return fontSize;
}
