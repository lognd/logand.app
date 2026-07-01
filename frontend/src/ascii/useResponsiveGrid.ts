import { useEffect, useState } from "react";
import { getQualityMultiplier } from "./deviceQuality";
import { measureCharAspect } from "./useFitFontSize";

export interface GridDims {
  cols: number;
  rows: number;
}

// SpinningShape's own grid budget/bounds, re-exported so MatrixRain.tsx and
// ParticleLayer.tsx can size their canvas text to MATCH it -- those two
// don't lay out a cols x rows text grid themselves (free-form canvas
// particles/streams instead), but on mobile their previously-fixed 18px
// cell size and the shape's viewport-scaled font size diverged sharply
// ("the trail text size and the background text size are very far
// apart... especially for the spinning shapes"). Deriving the same
// cols/rows here that SpinningShape derives, then feeding them through
// useFitFontSize the same way, produces the same resulting font size --
// "coincident" by construction, not just visually close.
export const SHAPE_TARGET_CELLS = 100 * 50;
export const SHAPE_GRID_BOUNDS = { minCols: 40, maxCols: 140, minRows: 24, maxRows: 90 };

// Picks a cols x rows character grid whose own aspect ratio
// (cols * charAspect : rows) matches the viewport's, instead of a fixed
// ratio baked in at design time. A fixed 100x50 (2:1-ish) grid is close to
// a typical desktop window's aspect ratio, but on a tall phone viewport
// (often closer to 9:19.5) forcing that same wide-rectangle grid into a
// tall-rectangle container means the whole thing renders tiny and centered
// with huge empty margins top and bottom ("the background doesn't extend
// to the edges", "the animations get misaligned" on narrow/phone
// viewports) -- shrinking cols and growing rows to match the actual
// viewport shape fills the screen edge-to-edge on any aspect ratio
// instead.
//
// `targetCells` is the desired total cols*rows at quality tier "high"
// (see deviceQuality.ts) -- roughly preserves each component's original
// hand-tuned density on a capable desktop while scaling down on lower-end
// devices.
// Below this viewport width (matches Tailwind's `sm` breakpoint, the same
// one Shell.tsx's header nav collapses at), the grid's cell budget is
// reduced further -- "I prefer slightly larger background text on mobile
// viewport for the spinning shapes and rain." The aspect-fit math above
// already reshapes cols/rows to fill a narrow screen edge-to-edge, but at
// the SAME total budget as desktop that just means more, smaller
// characters packed into less physical space; deliberately shrinking the
// budget on narrow viewports makes each character bigger instead.
const MOBILE_BREAKPOINT_PX = 640;
const MOBILE_BUDGET_SCALE = 0.6;

export function useResponsiveGrid(
  targetCells: number,
  bounds: { minCols: number; maxCols: number; minRows: number; maxRows: number },
): GridDims {
  const [dims, setDims] = useState<GridDims>({
    cols: Math.round(Math.sqrt(targetCells)),
    rows: Math.round(Math.sqrt(targetCells)),
  });

  useEffect(() => {
    const charAspect = measureCharAspect();

    function recompute() {
      // window.visualViewport, when available, reflects what's actually
      // visible during pinch/page zoom -- window.innerWidth/innerHeight
      // stay pinned to the page's original layout viewport, so relying on
      // them alone left the grid's shape un-updated on zoom (see
      // useFitFontSize's viewportSize doc comment for the same issue).
      const vv = window.visualViewport;
      const viewportWidth = vv ? vv.width : window.innerWidth;
      const viewportAspect = vv ? vv.width / vv.height : window.innerWidth / window.innerHeight;
      const budget =
        targetCells *
        getQualityMultiplier() *
        (viewportWidth < MOBILE_BREAKPOINT_PX ? MOBILE_BUDGET_SCALE : 1);
      // Solve cols*charAspect/rows = viewportAspect and cols*rows = budget
      // simultaneously (see the derivation in the module doc comment).
      const rows = Math.sqrt((budget * charAspect) / viewportAspect);
      const cols = budget / rows;
      setDims({
        cols: Math.round(Math.min(bounds.maxCols, Math.max(bounds.minCols, cols))),
        rows: Math.round(Math.min(bounds.maxRows, Math.max(bounds.minRows, rows))),
      });
    }

    recompute();
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- bounds is a fresh object literal at every call site; only targetCells identity matters here
  }, [targetCells]);

  return dims;
}
