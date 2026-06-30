import { useEffect, useState } from "react";

// Computes a monospace font-size (px) so a `cols` x `rows` character grid
// fills the viewport without overflowing either axis. Used by both
// AsciiCanvas and SpinningShape, which previously had no explicit sizing at
// all and rendered at the browser's inherited default font-size -- a fixed
// 80x40 (or similar) grid at ~16px is nowhere near big enough to fill a
// fixed inset-0 layer on a real viewport, which is why the noise layer
// showed up as a small, oddly-placed block ("not the correct size").
//
// charAspect is the ratio of a monospace glyph's rendered width to its
// font-size (JetBrains Mono is close to 0.6). Picking the smaller of the
// width-driven and height-driven font sizes guarantees the whole grid stays
// within the viewport on both axes (letterboxed on whichever axis has
// slack) rather than clipping.
export function useFitFontSize(
  cols: number,
  rows: number,
  charAspect = 0.6,
): number {
  const [fontSize, setFontSize] = useState(10);

  useEffect(() => {
    function recompute() {
      const sizeForWidth = window.innerWidth / (cols * charAspect);
      const sizeForHeight = window.innerHeight / rows;
      setFontSize(Math.max(4, Math.min(sizeForWidth, sizeForHeight)));
    }
    recompute();
    window.addEventListener("resize", recompute);
    return () => window.removeEventListener("resize", recompute);
  }, [cols, rows, charAspect]);

  return fontSize;
}
