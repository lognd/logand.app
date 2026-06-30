import { useEffect, useMemo, useRef, useState } from "react";
import { colorForBrightness } from "./fallback";
import {
  generateShape,
  randomShapeKind,
  rasterizeShape,
  type ShapeKind,
} from "./shapes";
import { useFitFontSize } from "./useFitFontSize";

const COLS = 100;
const ROWS = 50;

// Degrees/sec auto-rotation when idle. Picked to read as a calm, deliberate
// spin rather than a distracting blur.
const AUTO_SPEED_X = 0.25;
const AUTO_SPEED_Y = 0.45;

// Below this drag distance (px) a pointerdown+move is treated as a scroll
// gesture, not a rotate gesture -- see the mobile-scroll note below.
const DRAG_THRESHOLD_PX = 6;

interface ShapeRow {
  text: string;
  color: string;
}

export function SpinningShape({ className }: { className?: string }) {
  const [kind] = useState<ShapeKind>(() => randomShapeKind());
  const points = useMemo(() => generateShape(kind), [kind]);
  const [rows, setRows] = useState<ShapeRow[]>([]);
  const fontSize = useFitFontSize(COLS, ROWS);

  const angleRef = useRef({ x: 0.4, y: 0 });
  const draggingRef = useRef(false);
  const dragCapturedRef = useRef(false);
  const lastPointerRef = useRef({ x: 0, y: 0 });
  const reducedMotionRef = useRef(false);

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
    let raf = 0;
    let lastTime = performance.now();

    const render = (now: number) => {
      const dtSeconds = (now - lastTime) / 1000;
      lastTime = now;

      // Auto-rotate only when idle and motion isn't reduced. Manual drag
      // rotation (handled in the pointermove handler below) always applies
      // regardless of reduced-motion, since it's user-initiated, not
      // autoplaying animation.
      if (!draggingRef.current && !reducedMotionRef.current) {
        angleRef.current = {
          x: angleRef.current.x + AUTO_SPEED_X * dtSeconds,
          y: angleRef.current.y + AUTO_SPEED_Y * dtSeconds,
        };
      }

      const grid = rasterizeShape(
        points,
        angleRef.current.x,
        angleRef.current.y,
        COLS,
        ROWS,
      );
      // One colored <span> per row rather than per character -- per-character
      // coloring would mean ~5000 styled DOM nodes re-rendered at up to
      // 60fps, which isn't worth it here; a per-row average brightness
      // still reads as a smooth light-to-dark gradient across the shape.
      setRows(
        grid.map((row) => {
          let text = "";
          let sum = 0;
          for (const cell of row) {
            text += cell.char;
            sum += cell.brightness;
          }
          return { text, color: colorForBrightness(sum / row.length) };
        }),
      );

      raf = requestAnimationFrame(render);
    };

    raf = requestAnimationFrame(render);
    return () => cancelAnimationFrame(raf);
  }, [points]);

  // Pointer Events unify mouse, touch, and pen -- one code path handles
  // "mouse drag" and "finger drag" alike, per docs/design/09's mobile-first
  // accessibility bar.
  const onPointerDown = (e: React.PointerEvent<HTMLPreElement>) => {
    draggingRef.current = true;
    dragCapturedRef.current = false;
    lastPointerRef.current = { x: e.clientX, y: e.clientY };
  };

  const onPointerMove = (e: React.PointerEvent<HTMLPreElement>) => {
    if (!draggingRef.current) return;
    const dx = e.clientX - lastPointerRef.current.x;
    const dy = e.clientY - lastPointerRef.current.y;

    if (!dragCapturedRef.current) {
      // Don't claim the gesture (and never preventDefault) until the
      // pointer has moved a meaningful distance -- otherwise a mobile user
      // trying to scroll the page, whose thumb happens to land on the
      // shape, gets their scroll silently eaten. Once we do claim it, we
      // capture the pointer so the drag continues even if the finger/mouse
      // leaves the element's bounds.
      if (Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
      dragCapturedRef.current = true;
      e.currentTarget.setPointerCapture(e.pointerId);
    }

    angleRef.current = {
      x: angleRef.current.x - dy * 0.01,
      y: angleRef.current.y + dx * 0.01,
    };
    lastPointerRef.current = { x: e.clientX, y: e.clientY };
  };

  const endDrag = (e: React.PointerEvent<HTMLPreElement>) => {
    draggingRef.current = false;
    if (dragCapturedRef.current) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    dragCapturedRef.current = false;
  };

  return (
    // `className` (from Landing.tsx) carries flex-centering classes meant to
    // center the whole shape block within its positioned container -- it
    // must NOT land on the <pre> itself now that the <pre> has 50 row <div>
    // children instead of one text node: `display:flex` (default
    // flex-direction:row) would lay those 50 rows out *horizontally* as
    // individual flex items instead of stacking them, squashing the shape
    // into a single visible line. Centering happens on this wrapper; the
    // <pre> below stays a plain block so its row divs stack normally.
    <div className={className}>
      <pre
        aria-hidden="true"
        // touchAction: "pan-y" deliberately leaves vertical touch scrolling
        // to the browser natively (so a thumb landing on the shape never
        // traps page scroll, per docs/design/09's mobile bar) while still
        // letting our pointermove handler see horizontal movement to drive
        // rotation. The threshold-gated capture above is the other half of
        // that guarantee for the horizontal axis.
        style={{
          touchAction: "pan-y",
          cursor: "grab",
          fontSize: `${fontSize}px`,
          lineHeight: `${fontSize}px`,
          display: "block",
        }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        {rows.map((row, i) => (
          <div key={i} style={{ color: row.color }}>
            {row.text}
          </div>
        ))}
      </pre>
    </div>
  );
}
