import { useEffect, useMemo, useRef, useState } from "react";
import { colorForBrightness } from "./fallback";
import {
  generateShape,
  quatFromAxisAngle,
  quatIdentity,
  quatMultiply,
  quatNormalize,
  randomShapeKind,
  rasterizeShape,
  type Quaternion,
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

// Momentum after release: the angular velocity (rad/s, around the fixed
// world X/Y axes) accumulated during the drag keeps spinning the shape and
// decays exponentially rather than stopping dead or instantly resuming the
// fixed auto-rotation speed.
const VELOCITY_DAMPING_PER_SEC = 2.2; // higher = stops sooner
const MIN_COASTING_VELOCITY = 0.02; // below this, snap to 0 and resume idle auto-rotate

// Hover-reactive tilt ("I want the object to react without clicking"): the
// shape leans slightly toward the cursor even when the user isn't
// dragging. HOVER_LERP controls how quickly the lean eases toward its
// target each frame (and back to neutral when the pointer leaves) -- this
// is the "smoothing between moving the mouse and idle" the easing
// addresses: the tilt blends continuously rather than snapping.
const HOVER_MAX_TILT = 0.25; // radians
const HOVER_LERP = 4; // higher = snaps faster to the target tilt

const WORLD_X: { x: number; y: number; z: number } = { x: 1, y: 0, z: 0 };
const WORLD_Y: { x: number; y: number; z: number } = { x: 0, y: 1, z: 0 };

interface ShapeRow {
  text: string;
  color: string;
}

export function SpinningShape({
  className,
  kind: controlledKind,
}: {
  className?: string;
  kind?: ShapeKind;
}) {
  const [randomKind] = useState<ShapeKind>(() => randomShapeKind());
  const kind = controlledKind ?? randomKind;
  const points = useMemo(() => generateShape(kind), [kind]);
  const [rows, setRows] = useState<ShapeRow[]>([]);
  const fontSize = useFitFontSize(COLS, ROWS);

  // Accumulated orientation as a single quaternion -- NOT a pair of Euler
  // angles applied in sequence each frame. Sequential Euler angles are
  // exactly what made drag controls feel like they "rotate the wrong way"
  // depending on the shape's current spin (a version of gimbal lock): each
  // frame's rotation was applied around the fixed WORLD axes, so once the
  // shape had turned partway, a horizontal drag no longer corresponded to
  // the visually-horizontal screen axis. Every incremental rotation below
  // (auto-spin, drag, momentum, hover-tilt) is built as its own small
  // quaternion around a FIXED world axis and left-multiplied onto the
  // accumulated orientation (orientation = increment * orientation), which
  // keeps "drag right" meaning the same visual thing regardless of how
  // much the shape has already turned.
  const orientationRef = useRef<Quaternion>(quatIdentity());
  // Angular velocity (rad/s) carried from the drag, decayed each frame --
  // this is what gives released drags momentum instead of stopping dead.
  const velocityRef = useRef({ x: 0, y: 0 });
  const draggingRef = useRef(false);
  const dragCapturedRef = useRef(false);
  const lastPointerRef = useRef({ x: 0, y: 0, t: 0 });
  const reducedMotionRef = useRef(false);
  // Current and target hover-tilt offset (rad around world X/Y), eased
  // toward the target each frame -- see HOVER_LERP above.
  const hoverTiltRef = useRef({ x: 0, y: 0 });
  const hoverTargetRef = useRef({ x: 0, y: 0 });
  const containerRef = useRef<HTMLDivElement | null>(null);

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

      if (!draggingRef.current) {
        const v = velocityRef.current;
        const coasting = Math.hypot(v.x, v.y) > MIN_COASTING_VELOCITY;
        if (coasting) {
          // Momentum: keep spinning at the velocity the drag left behind,
          // exponentially decaying toward zero.
          const incr = quatMultiply(
            quatFromAxisAngle(WORLD_X, v.x * dtSeconds),
            quatFromAxisAngle(WORLD_Y, v.y * dtSeconds),
          );
          orientationRef.current = quatNormalize(quatMultiply(incr, orientationRef.current));
          const decay = Math.exp(-VELOCITY_DAMPING_PER_SEC * dtSeconds);
          velocityRef.current = { x: v.x * decay, y: v.y * decay };
        } else if (!reducedMotionRef.current) {
          velocityRef.current = { x: 0, y: 0 };
          const incr = quatMultiply(
            quatFromAxisAngle(WORLD_X, AUTO_SPEED_X * dtSeconds),
            quatFromAxisAngle(WORLD_Y, AUTO_SPEED_Y * dtSeconds),
          );
          orientationRef.current = quatNormalize(quatMultiply(incr, orientationRef.current));
        }
      }

      // Hover-reactive tilt: ease the current tilt toward the target
      // (which pointermove below updates continuously, and which decays
      // back to {0,0} once the pointer leaves) and fold it in as one more
      // small world-axis rotation on top of whatever spin/drag is
      // happening. This is on every frame regardless of drag state, so it
      // keeps responding even while idle or coasting.
      const tilt = hoverTiltRef.current;
      const target = hoverTargetRef.current;
      const lerpAmount = 1 - Math.exp(-HOVER_LERP * dtSeconds);
      const nextTilt = {
        x: tilt.x + (target.x - tilt.x) * lerpAmount,
        y: tilt.y + (target.y - tilt.y) * lerpAmount,
      };
      const tiltDelta = { x: nextTilt.x - tilt.x, y: nextTilt.y - tilt.y };
      hoverTiltRef.current = nextTilt;
      if (tiltDelta.x !== 0 || tiltDelta.y !== 0) {
        const tiltIncr = quatMultiply(
          quatFromAxisAngle(WORLD_X, tiltDelta.x),
          quatFromAxisAngle(WORLD_Y, tiltDelta.y),
        );
        orientationRef.current = quatNormalize(
          quatMultiply(tiltIncr, orientationRef.current),
        );
      }

      const grid = rasterizeShape(points, orientationRef.current, COLS, ROWS);
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

  // Window-level (not element-level) pointer listeners: real page content
  // (nav links, headings, paragraph text) sits visually on top of this
  // decorative background and is hit-testable, so an element-scoped
  // pointermove/pointerdown on the <pre> itself never fires while the
  // cursor is over that text -- the shape would stop reacting and dragging
  // would stop mid-gesture the moment the cursor crossed a link ("the
  // highlight-able elements stop interaction with the background").
  // Listening on window instead means every pointer move/down anywhere on
  // the page is seen regardless of what's on top, and position is always
  // computed against the container's own bounding rect.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const isWithinContainer = (clientX: number, clientY: number) => {
      const rect = container.getBoundingClientRect();
      return (
        clientX >= rect.left &&
        clientX <= rect.right &&
        clientY >= rect.top &&
        clientY <= rect.bottom
      );
    };

    const onWindowPointerMove = (e: PointerEvent) => {
      const rect = container.getBoundingClientRect();
      if (isWithinContainer(e.clientX, e.clientY)) {
        // Hover-tilt target tracks the pointer position within the
        // container any time it's over the shape's area, drag or not --
        // "I want the object to react without clicking". Normalized to
        // [-1, 1] across the container's bounds, then scaled to
        // HOVER_MAX_TILT radians.
        const nx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        const ny = ((e.clientY - rect.top) / rect.height) * 2 - 1;
        hoverTargetRef.current = {
          x: Math.max(-1, Math.min(1, ny)) * HOVER_MAX_TILT,
          y: Math.max(-1, Math.min(1, nx)) * HOVER_MAX_TILT,
        };
      } else {
        // Pointer left the shape's area entirely -- ease back to neutral
        // via the same HOVER_LERP smoothing used to ease toward a target,
        // rather than snapping back instantly.
        hoverTargetRef.current = { x: 0, y: 0 };
      }

      if (!draggingRef.current) return;
      const dx = e.clientX - lastPointerRef.current.x;
      const dy = e.clientY - lastPointerRef.current.y;

      if (!dragCapturedRef.current) {
        // Don't claim the gesture until the pointer has moved a
        // meaningful distance -- otherwise a mobile user trying to scroll
        // the page, whose thumb happens to land on the shape, gets their
        // scroll silently eaten.
        if (Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
        dragCapturedRef.current = true;
      }

      const now = performance.now();
      const dt = Math.max(1, now - lastPointerRef.current.t) / 1000;
      // Dragging right turns the shape's near side to the right (matching
      // the hand's motion), dragging down tips the near side toward the
      // viewer. Each increment rotates around the FIXED world X/Y axes
      // and is left-multiplied onto the accumulated orientation
      // quaternion, so this mapping stays correct no matter how the
      // shape is currently oriented (see orientationRef's doc comment).
      const dAngleX = -dy * 0.01;
      const dAngleY = -dx * 0.01;
      const incr = quatMultiply(
        quatFromAxisAngle(WORLD_X, dAngleX),
        quatFromAxisAngle(WORLD_Y, dAngleY),
      );
      orientationRef.current = quatNormalize(quatMultiply(incr, orientationRef.current));
      // Track angular velocity from this move so a release can carry
      // momentum (see VELOCITY_DAMPING_PER_SEC above).
      velocityRef.current = { x: dAngleX / dt, y: dAngleY / dt };
      lastPointerRef.current = { x: e.clientX, y: e.clientY, t: now };
    };

    const onWindowPointerDown = (e: PointerEvent) => {
      if (!isWithinContainer(e.clientX, e.clientY)) return;
      draggingRef.current = true;
      dragCapturedRef.current = false;
      velocityRef.current = { x: 0, y: 0 };
      lastPointerRef.current = { x: e.clientX, y: e.clientY, t: performance.now() };
    };

    const endDrag = () => {
      draggingRef.current = false;
      dragCapturedRef.current = false;
    };

    window.addEventListener("pointermove", onWindowPointerMove);
    window.addEventListener("pointerdown", onWindowPointerDown);
    window.addEventListener("pointerup", endDrag);
    window.addEventListener("pointercancel", endDrag);
    return () => {
      window.removeEventListener("pointermove", onWindowPointerMove);
      window.removeEventListener("pointerdown", onWindowPointerDown);
      window.removeEventListener("pointerup", endDrag);
      window.removeEventListener("pointercancel", endDrag);
    };
  }, []);

  return (
    // `className` (from Landing.tsx) carries flex-centering classes meant to
    // center the whole shape block within its positioned container -- it
    // must NOT land on the <pre> itself now that the <pre> has 50 row <div>
    // children instead of one text node: `display:flex` (default
    // flex-direction:row) would lay those 50 rows out *horizontally* as
    // individual flex items instead of stacking them, squashing the shape
    // into a single visible line. Centering happens on this wrapper; the
    // <pre> below stays a plain block so its row divs stack normally.
    <div className={className} ref={containerRef}>
      <pre
        aria-hidden="true"
        // Listeners are window-level now (see the effect above), not on
        // this element -- touchAction/preventDefault-avoidance no longer
        // gates "does the shape see the gesture" (it always does), only
        // "does the browser's native scroll still happen alongside it",
        // which it does since nothing here ever calls preventDefault.
        // userSelect: "none" stops a drag gesture from also
        // highlighting/selecting the rendered characters as text, which
        // was visually distracting mid-drag.
        style={{
          cursor: "grab",
          fontSize: `${fontSize}px`,
          lineHeight: `${fontSize}px`,
          display: "block",
          userSelect: "none",
          WebkitUserSelect: "none",
        }}
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
