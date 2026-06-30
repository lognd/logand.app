import { useEffect, useMemo, useRef, useState } from "react";
import { colorForBrightness } from "./fallback";
import {
  generateShape,
  quatFromAngularVelocity,
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

// Radians/sec auto-rotation when idle. Restored to the original 0.25/0.45
// -- an earlier "it goes a little fast" complaint turned out to be about
// the user-to-idle ramp's pacing (IDLE_RAMP_MS below), not this speed
// itself, which the user liked.
const AUTO_SPEED_X = 0.25;
const AUTO_SPEED_Y = 0.45;
// Combined rate + default axis for idle auto-rotation, expressed the same
// way a flick's angular velocity is (see quatFromAngularVelocity in
// shapes.ts) -- this is what lets "resume in the same direction as the
// flick" and "the original default direction" share one code path instead
// of auto-rotation being a special case applied separately per axis.
const AUTO_SPEED_MAGNITUDE = Math.hypot(AUTO_SPEED_X, AUTO_SPEED_Y);
const DEFAULT_AUTO_AXIS = { x: AUTO_SPEED_X / AUTO_SPEED_MAGNITUDE, y: AUTO_SPEED_Y / AUTO_SPEED_MAGNITUDE };

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
// shape leans toward the cursor even when the user isn't dragging.
// HOVER_LERP controls how quickly the lean tracks its target each frame --
// fast, since this should feel responsive while actively moving, not lazy.
// FOLLOW_MAX_TILT is deliberately large ("the amount it moves when the
// mouse moves needs to be greatly increased") -- a dramatic lean, not a
// subtle one.
const FOLLOW_MAX_TILT = 1.4; // radians (~80 degrees)
const HOVER_LERP = 10;

// Mouse-follow vs. idle-auto-rotate state machine ("not idle when the
// mouse is moving... ramp smoothly (cubically) back to idle rotation"):
// a pointermove within the shape's area marks "moving" for IDLE_GRACE_MS;
// once that grace period lapses with no further movement, a cubic-eased
// crossfade runs over IDLE_RAMP_MS, fading the follow-tilt's influence
// out (1 -> 0) while fading auto-rotation's speed in (0 -> 1) in lockstep,
// so the handoff is smooth rather than an abrupt mode switch.
const IDLE_GRACE_MS = 150;
// Slowed from an earlier 1200ms -- "I was referring to the lerp from user
// to idle [being fast]", not the idle auto-rotation speed itself.
const IDLE_RAMP_MS = 2400;

function easeInOutCubic(t: number): number {
  const c = Math.max(0, Math.min(1, t));
  return c < 0.5 ? 4 * c * c * c : 1 - Math.pow(-2 * c + 2, 3) / 2;
}

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
  // Current and target follow-tilt offset (rad around world X/Y), eased
  // toward the target each frame -- see HOVER_LERP above.
  const hoverTiltRef = useRef({ x: 0, y: 0 });
  const hoverTargetRef = useRef({ x: 0, y: 0 });
  // Timestamp of the last qualifying pointermove -- drives the
  // moving-vs-idle state machine (see IDLE_GRACE_MS/IDLE_RAMP_MS above).
  const lastMoveAtRef = useRef(0);
  // Timestamp the idle ramp began, or null while still actively moving /
  // before any movement has happened.
  const idleRampStartRef = useRef<number | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  // Normalized (vx, vy) axis the idle auto-rotation spins around once it
  // resumes ("start the idle animation in the same direction as the user
  // flicked it") -- captured from the drag's final angular velocity at
  // release. Defaults to AUTO_SPEED_X/Y's own direction so a page load
  // with no drag yet still spins the way it always has.
  const autoAxisRef = useRef(DEFAULT_AUTO_AXIS);

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

      // Moving-vs-idle crossfade: while a qualifying pointermove happened
      // within IDLE_GRACE_MS, the shape is "following" the mouse at full
      // strength and auto-rotation is fully suppressed ("not idle when
      // the mouse is moving"). Once that grace period lapses, a cubic-
      // eased ramp over IDLE_RAMP_MS crossfades follow-strength down to 0
      // and auto-rotate-strength up to 1.
      const idleFor = now - lastMoveAtRef.current;
      let followBlend: number;
      let autoBlend: number;
      if (idleFor < IDLE_GRACE_MS) {
        followBlend = 1;
        autoBlend = 0;
        idleRampStartRef.current = null;
      } else {
        if (idleRampStartRef.current === null) idleRampStartRef.current = now;
        const t = (now - idleRampStartRef.current) / IDLE_RAMP_MS;
        const eased = easeInOutCubic(t);
        followBlend = 1 - eased;
        autoBlend = eased;
      }

      if (!draggingRef.current) {
        const v = velocityRef.current;
        const coasting = Math.hypot(v.x, v.y) > MIN_COASTING_VELOCITY;
        if (coasting) {
          // Momentum: keep spinning at the velocity the drag left behind,
          // exponentially decaying toward zero. Independent of the
          // follow/idle crossfade -- a released drag's momentum always
          // plays out.
          const incr = quatFromAngularVelocity(v.x, v.y, dtSeconds);
          orientationRef.current = quatNormalize(quatMultiply(incr, orientationRef.current));
          const decay = Math.exp(-VELOCITY_DAMPING_PER_SEC * dtSeconds);
          velocityRef.current = { x: v.x * decay, y: v.y * decay };
        } else if (!reducedMotionRef.current) {
          // Auto-rotation speed is scaled by autoBlend -- zero while
          // actively following the mouse, cubically ramping back to full
          // speed once the pointer has been idle for a while.
          const axis = autoAxisRef.current;
          const incr = quatFromAngularVelocity(
            axis.x * AUTO_SPEED_MAGNITUDE,
            axis.y * AUTO_SPEED_MAGNITUDE,
            autoBlend * dtSeconds,
          );
          orientationRef.current = quatNormalize(quatMultiply(incr, orientationRef.current));
        }
      }

      // Follow tilt: only applied while actually following (followBlend >
      // 0). Critically, the target is NEVER scaled back toward zero as
      // the idle ramp progresses -- doing that earlier is exactly what
      // caused the "snapping back" complaint: scaling the target down
      // forced the tilt to actively reverse itself, fighting auto-
      // rotation rather than handing off to it. Once idle (followBlend
      // hits 0), this block is skipped entirely, so whatever tilt was
      // last applied stays permanently baked into orientationRef and
      // auto-rotation just continues accumulating on top of it --
      // "continue from where the user left off rather than snapping
      // back."
      if (followBlend > 0) {
        const target = hoverTargetRef.current;
        const tilt = hoverTiltRef.current;
        const lerpAmount = 1 - Math.exp(-HOVER_LERP * dtSeconds);
        const nextTilt = {
          x: tilt.x + (target.x - tilt.x) * lerpAmount,
          y: tilt.y + (target.y - tilt.y) * lerpAmount,
        };
        const tiltDelta = { x: nextTilt.x - tilt.x, y: nextTilt.y - tilt.y };
        hoverTiltRef.current = nextTilt;
        if (tiltDelta.x !== 0 || tiltDelta.y !== 0) {
          // dt=1: tiltDelta is already a one-shot angle delta for this
          // frame, not a rate, so quatFromAngularVelocity's magnitude*dt
          // should just be |tiltDelta|.
          const tiltIncr = quatFromAngularVelocity(tiltDelta.x, tiltDelta.y, 1);
          orientationRef.current = quatNormalize(
            quatMultiply(tiltIncr, orientationRef.current),
          );
        }
      }

      const grid = rasterizeShape(points, orientationRef.current, COLS, ROWS, undefined, kind);
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
  }, [points, kind]);

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
        // Follow-tilt target tracks the pointer position within the
        // container any time it's over the shape's area, drag or not --
        // "I want the object to react without clicking". Normalized to
        // [-1, 1] across the container's bounds, then scaled to
        // FOLLOW_MAX_TILT radians (large, "greatly increased").
        const nx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        const ny = ((e.clientY - rect.top) / rect.height) * 2 - 1;
        // Negated on both axes -- the un-negated mapping span the shape
        // spinning opposite the cursor's motion (reported: "it spins the
        // wrong direction"). This matches the same sign convention as the
        // drag handler below (cursor moving right -> shape's near side
        // turns right, not left).
        hoverTargetRef.current = {
          x: -Math.max(-1, Math.min(1, ny)) * FOLLOW_MAX_TILT,
          y: -Math.max(-1, Math.min(1, nx)) * FOLLOW_MAX_TILT,
        };
        // Marks "moving" for the idle/follow crossfade in the render loop
        // -- auto-rotation is suppressed for IDLE_GRACE_MS after this,
        // then cubically ramps back in once movement actually stops.
        lastMoveAtRef.current = performance.now();
      }
      // No `else` branch resetting the target to {0,0} when the pointer
      // leaves the shape's area -- that was the other source of the
      // "snapping back" complaint (it forced the tilt to actively reverse
      // toward neutral the instant the cursor left, before the idle timer
      // even started). The target just stays frozen at wherever the
      // pointer last was inside the area; lastMoveAtRef not being
      // refreshed here means the idle/follow crossfade in the render loop
      // still kicks in on its own normal schedule.

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
      // dt=1: dAngleX/dAngleY are already this frame's one-shot angle delta,
      // not a rate -- see quatFromAngularVelocity's doc comment for why a
      // single combined-axis quaternion replaces the old sequential
      // X-then-Y composition.
      const incr = quatFromAngularVelocity(dAngleX, dAngleY, 1);
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
      // Capture the flick's direction (as a normalized axis, same
      // representation quatFromAngularVelocity uses internally) before
      // momentum decay zeroes velocityRef out -- this is what "start the
      // idle animation in the same direction as the user flicked it" reads
      // from once auto-rotation resumes. A near-zero release velocity
      // leaves the previous axis unchanged rather than collapsing to a
      // degenerate zero-length axis.
      const v = velocityRef.current;
      const magnitude = Math.hypot(v.x, v.y);
      if (magnitude > 1e-6) {
        autoAxisRef.current = { x: v.x / magnitude, y: v.y / magnitude };
      }
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
