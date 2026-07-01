import { useEffect, useRef } from "react";
import { createStreams, stepStreams, type RainStream } from "./matrixRain";
import { useFitFontSize } from "./useFitFontSize";
import { SHAPE_GRID_BOUNDS, SHAPE_TARGET_CELLS, useResponsiveGrid } from "./useResponsiveGrid";

// Used to be a flat 18px constant regardless of viewport -- on a phone
// screen that stayed fixed while SpinningShape's own text shrank to fit
// the smaller viewport, so the rain/trail glyphs read as wildly larger
// than the shape's ("the trail text size and the background text size are
// very far apart... especially for the spinning shapes"). Deriving it from
// the exact same grid budget/bounds SpinningShape uses (see
// useResponsiveGrid.ts's SHAPE_TARGET_CELLS doc comment) produces a
// matching font size instead -- `ctx.font` below is `CELL_SIZE * 0.85`px,
// so dividing back out by 0.85 here recovers the CELL_SIZE that yields
// that exact font size.

// Matrix rain is a specific-enough aesthetic reference that a brighter,
// more saturated green than the muted Gruvbox --accent-green reads
// correctly here -- a near-desaturated Gruvbox tone looks washed out for
// this particular effect. HEAD_COLOR is the leading/brightest character of
// each ambient stream; TRAIL_COLOR is the fading body, closer to the
// site's existing --accent-green so the effect still feels related to the
// rest of the palette rather than a clashing foreign color.
const HEAD_COLOR = "#7CFC9A";
const TRAIL_COLOR = "#3a7d4a";

// Solid, stationary backdrop the rain renders against -- exactly Gruvbox
// Dark's --bg-primary (tokens.css), resolved to a literal hex value since
// canvas fillStyle can't read CSS custom properties directly.
const BACKDROP_COLOR = "#282828";

/**
 * The landing page's "Rain" background option (see BackgroundPicker.tsx)
 * -- ambient falling-glyph rain on a stationary dark backdrop. Renders to
 * a <canvas> rather than DOM text nodes (unlike AsciiCanvas/SpinningShape)
 * because redrawing a whole grid of characters every frame as React state
 * would mean a few hundred DOM node text mutations per frame -- canvas
 * draw calls are dramatically cheaper and this effect has no need to be
 * selectable/copyable text the way the decorative ASCII shapes arguably do.
 *
 * The ambient layer advances in discrete whole-character-cell STEPS on a
 * per-column timer (see matrixRain.ts's stepStreams), not a continuously
 * translating pixel scroll -- "visibly move downward, but not by
 * translation... step-like."
 *
 * The click/drag particle interaction (trail + explosion) used to live
 * here too -- it's now ParticleLayer.tsx, mounted as a separate layer
 * alongside whichever background is active (not just this one), per
 * feedback that the interaction should work on the shape backgrounds too.
 *
 * Always renders once mounted -- selection (whether this is the active
 * background at all) is the parent's job, same as SpinningShape; this
 * component doesn't own an enabled/disabled toggle of its own.
 */
export function MatrixRain({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamsRef = useRef<RainStream[]>([]);
  const reducedMotionRef = useRef(false);
  const { cols, rows } = useResponsiveGrid(SHAPE_TARGET_CELLS, SHAPE_GRID_BOUNDS);
  const fontSize = useFitFontSize(cols, rows);
  const cellSize = fontSize / 0.85;

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    reducedMotionRef.current = mq.matches;
    const onChange = () => {
      reducedMotionRef.current = mq.matches;
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf = 0;
    let lastTime = performance.now();

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      streamsRef.current = createStreams(rect.width, rect.height, cellSize);
    };
    resize();
    // "resize" alone isn't reliably fired by every browser's Fullscreen
    // API transition -- without also resizing here, the canvas's backing
    // pixel buffer stays stale after fullscreening while its CSS box grows
    // to fill the new viewport, stretching/cutting off the rendered rain
    // ("shapes and rain get cut off when fullscreening").
    window.addEventListener("resize", resize);
    document.addEventListener("fullscreenchange", resize);

    const render = (now: number) => {
      const dtSeconds = Math.min((now - lastTime) / 1000, 0.05);
      lastTime = now;
      const rect = canvas.getBoundingClientRect();

      // Solid fillRect, not clearRect -- a stationary opaque backdrop
      // instead of a transparent canvas (which let page content behind it
      // show through and shift as the page scrolled, reading as if the
      // "background" itself were moving rather than just the rain).
      //
      // Fills via the canvas's own (integer, device-pixel) width/height,
      // not rect.width/rect.height under the dpr transform -- see
      // ParticleLayer.tsx's identical fix for why: rect.width is a
      // fractional CSS value that can drift slightly frame to frame, and
      // filling based on it (through the dpr transform) can cover very
      // slightly less than the actual backing store, leaving a sliver at
      // the edge that's never repainted -- whatever was drawn there stays
      // stuck instead of fading under the next frame's backdrop.
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = BACKDROP_COLOR;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.restore();
      ctx.font = `${cellSize * 0.85}px "JetBrains Mono", monospace`;
      ctx.textBaseline = "top";

      // Skipped entirely under prefers-reduced-motion, same convention as
      // SpinningShape's auto-rotation: autoplaying motion is suppressed.
      if (!reducedMotionRef.current) {
        streamsRef.current = stepStreams(streamsRef.current, dtSeconds, rect.height, cellSize);
        for (const s of streamsRef.current) {
          for (let i = 0; i < s.chars.length; i++) {
            const y = s.y - i * cellSize;
            if (y < -cellSize || y > rect.height) continue;
            ctx.fillStyle = i === 0 ? HEAD_COLOR : TRAIL_COLOR;
            ctx.globalAlpha = i === 0 ? 1 : Math.max(0, 1 - i / s.length);
            ctx.fillText(s.chars[i], s.x, y);
          }
        }
        ctx.globalAlpha = 1;
      }

      raf = requestAnimationFrame(render);
    };
    raf = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      document.removeEventListener("fullscreenchange", resize);
    };
    // Restarts (streams reset) when cellSize changes -- already happens
    // today on every window resize anyway (resize() above always calls
    // createStreams() fresh), so this isn't a new disruption.
  }, [cellSize]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={className}
      // The canvas's width/height ATTRIBUTES are set in device pixels
      // (rect.width/height * devicePixelRatio, see resize() above) for
      // crisp rendering on high-DPI screens -- but a <canvas> is a
      // replaced element whose CSS box defaults to those attribute
      // dimensions when no CSS width/height is set, which on any
      // devicePixelRatio > 1 screen made the element's actual layout box
      // larger than the viewport (e.g. 2x), causing page overflow. Pin
      // the CSS box back to 100% of its positioned container regardless
      // of the internal pixel-buffer resolution.
      style={{ width: "100%", height: "100%" }}
    />
  );
}
