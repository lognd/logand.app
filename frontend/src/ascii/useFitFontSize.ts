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
function measureCharAspect(): number {
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
      const sizeForWidth = window.innerWidth / (cols * aspect);
      const sizeForHeight = window.innerHeight / rows;
      setFontSize(Math.max(4, Math.min(sizeForWidth, sizeForHeight) * SAFETY_MARGIN));
    }
    recompute();
    // "resize" alone isn't reliably fired by every browser's Fullscreen
    // API transition -- "fullscreenchange" is the dedicated event for
    // exactly that state change, and orientationchange covers mobile
    // rotation, which can also change the effective viewport without a
    // "resize" event firing first on some browsers.
    window.addEventListener("resize", recompute);
    document.addEventListener("fullscreenchange", recompute);
    window.addEventListener("orientationchange", recompute);
    return () => {
      window.removeEventListener("resize", recompute);
      document.removeEventListener("fullscreenchange", recompute);
      window.removeEventListener("orientationchange", recompute);
    };
  }, [cols, rows, charAspect]);

  return fontSize;
}
