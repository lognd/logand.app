import { useEffect, useRef } from "react";
import {
  createStreams,
  heatColor,
  spawnExplosion,
  spawnTrail,
  stepParticles,
  stepStreams,
  type Particle,
  type RainStream,
} from "./matrixRain";

const CELL_SIZE = 18; // px per character cell at the canvas's own (CSS) pixel scale
const EXPLOSION_COUNT = 36;
const TRAIL_PARTICLES_PER_MOVE = 1;
const MAX_TRAIL_POINTS_PER_FRAME = 6; // cap how many path points one pointermove can spawn from, for fast drags

// Rapid-fire clicks within this window (ms) count toward the same
// "streak" and escalate explosion violence; a click after a longer gap
// resets the streak back to baseline.
const CLICK_STREAK_WINDOW_MS = 600;
const MAX_VIOLENCE = 4;

// Matrix rain is a specific-enough aesthetic reference that a brighter,
// more saturated green than the muted Gruvbox --accent-green reads
// correctly here -- a near-desaturated Gruvbox tone looks washed out for
// this particular effect. HEAD_COLOR is the leading/brightest character of
// each ambient stream; TRAIL_COLOR is the fading body, closer to the
// site's existing --accent-green so the effect still feels related to the
// rest of the palette rather than a clashing foreign color. These two only
// apply to the ambient ("idle") rain streams -- trail and explosion
// particles use their own distinct colors below, per feedback that they
// should visually read as different effects, not just more green rain.
const HEAD_COLOR = "#7CFC9A";
const TRAIL_COLOR = "#3a7d4a";

// Pointer-trail particles are blue (distinct from the ambient green rain
// and from the explosion's heat-curve red/orange/yellow) -- a lighter blue
// for freshly-spawned trail glyphs fading to a darker blue as they age,
// mirroring the head/trail treatment used for the ambient streams.
const TRAIL_PARTICLE_HEAD_COLOR = "#7CC7FC";
const TRAIL_PARTICLE_TAIL_COLOR = "#2f5d80";

// Solid, stationary backdrop the rain renders against -- exactly Gruvbox
// Dark's --bg-primary (tokens.css), resolved to a literal hex value since
// canvas fillStyle can't read CSS custom properties directly.
const BACKDROP_COLOR = "#282828";

/**
 * The landing page's "Rain" background option (see BackgroundPicker.tsx)
 * -- ambient falling-glyph rain on a stationary dark backdrop, plus a blue
 * trail of glyph-flashes along the pointer's recent path and a
 * heat-colored "explosion" flare on click/tap (rapid repeated clicks
 * escalate the flare's size -- see clickStreakRef below). Renders to a
 * <canvas> rather than DOM text nodes (unlike AsciiCanvas/SpinningShape)
 * because redrawing a whole grid of characters every frame as React state
 * would mean a few hundred DOM node text mutations per frame -- canvas
 * draw calls are dramatically cheaper and this effect has no need to be
 * selectable/copyable text the way the decorative ASCII shapes arguably do.
 *
 * The ambient layer advances in discrete whole-character-cell STEPS on a
 * per-column timer (see matrixRain.ts's stepStreams), not a continuously
 * translating pixel scroll -- "visibly move downward, but not by
 * translation... step-like." Trail/explosion glyphs are likewise
 * grid-bound, stationary flashes, not flying physics debris.
 *
 * Always renders once mounted -- selection (whether this is the active
 * background at all) is the parent's job, same as SpinningShape; this
 * component doesn't own an enabled/disabled toggle of its own.
 */
export function MatrixRain({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamsRef = useRef<RainStream[]>([]);
  const particlesRef = useRef<Particle[]>([]);
  const reducedMotionRef = useRef(false);
  const recentPathRef = useRef<{ x: number; y: number }[]>([]);
  // Tracks click timestamps within the current rapid-fire streak so a burst
  // of clicks escalates explosion violence (see CLICK_STREAK_WINDOW_MS).
  const clickStreakRef = useRef<{ count: number; lastClickAt: number }>({
    count: 0,
    lastClickAt: 0,
  });

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
      streamsRef.current = createStreams(rect.width, rect.height, CELL_SIZE);
    };
    resize();
    window.addEventListener("resize", resize);

    const render = (now: number) => {
      const dtSeconds = Math.min((now - lastTime) / 1000, 0.05);
      lastTime = now;
      const rect = canvas.getBoundingClientRect();

      // Solid fillRect, not clearRect -- a stationary opaque backdrop
      // instead of a transparent canvas (which let page content behind it
      // show through and shift as the page scrolled, reading as if the
      // "background" itself were moving rather than just the rain).
      ctx.fillStyle = BACKDROP_COLOR;
      ctx.fillRect(0, 0, rect.width, rect.height);
      ctx.font = `${CELL_SIZE * 0.85}px "JetBrains Mono", monospace`;
      ctx.textBaseline = "top";

      // Ambient rain -- the idle look. Skipped entirely under
      // prefers-reduced-motion, same convention as SpinningShape's
      // auto-rotation: autoplaying motion is suppressed, user-triggered
      // effects (trail/explosion, below) are not, since those only ever
      // happen in direct response to input.
      if (!reducedMotionRef.current) {
        streamsRef.current = stepStreams(streamsRef.current, dtSeconds, rect.height, CELL_SIZE);
        for (const s of streamsRef.current) {
          for (let i = 0; i < s.chars.length; i++) {
            const y = s.y - i * CELL_SIZE;
            if (y < -CELL_SIZE || y > rect.height) continue;
            ctx.fillStyle = i === 0 ? HEAD_COLOR : TRAIL_COLOR;
            ctx.globalAlpha = i === 0 ? 1 : Math.max(0, 1 - i / s.length);
            ctx.fillText(s.chars[i], s.x, y);
          }
        }
        ctx.globalAlpha = 1;
      }

      // Trail + explosion particles always run (user-initiated, not
      // autoplay). Colored by kind: blue for the pointer trail, a
      // heat-curve (red -> orange -> yellow-white) for explosions, each
      // fading out over its lifetime.
      particlesRef.current = stepParticles(particlesRef.current, dtSeconds);
      for (const p of particlesRef.current) {
        const lifeFrac = 1 - p.age / p.lifetime;
        ctx.fillStyle =
          p.kind === "explosion"
            ? heatColor(lifeFrac)
            : lifeFrac > 0.6
              ? TRAIL_PARTICLE_HEAD_COLOR
              : TRAIL_PARTICLE_TAIL_COLOR;
        ctx.globalAlpha = Math.max(0, lifeFrac);
        ctx.fillText(p.char, p.x, p.y);
      }
      ctx.globalAlpha = 1;

      raf = requestAnimationFrame(render);
    };
    raf = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, []);

  // Window-level (not canvas-level) pointer listeners -- real page content
  // (nav links, headings, paragraph text) sits visually on top of this
  // decorative canvas and is hit-testable, so a canvas-scoped
  // pointermove/pointerdown never fires while the cursor is over that text
  // ("the highlight-able elements stop interaction with the background").
  // Listening on window instead means every pointer move/down anywhere on
  // the page is seen regardless of what's on top. No preventDefault
  // anywhere in this component -- native touch scrolling/panning is
  // unaffected either way.
  useEffect(() => {
    const isWithinCanvas = (clientX: number, clientY: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return false;
      const rect = canvas.getBoundingClientRect();
      return (
        clientX >= rect.left &&
        clientX <= rect.right &&
        clientY >= rect.top &&
        clientY <= rect.bottom
      );
    };

    const onWindowPointerMove = (e: PointerEvent) => {
      const canvas = canvasRef.current;
      if (!canvas || !isWithinCanvas(e.clientX, e.clientY)) return;
      const rect = canvas.getBoundingClientRect();
      const point = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      const path = recentPathRef.current;
      path.push(point);
      if (path.length > MAX_TRAIL_POINTS_PER_FRAME) path.shift();
      // Spawn at the precise pointer position -- each particle's REAL
      // gravity-physics trajectory starts here; grid-snapping only
      // happens to the rendered position (see stepParticle), not the
      // spawn point itself.
      particlesRef.current.push(...spawnTrail([point], TRAIL_PARTICLES_PER_MOVE));
    };

    const onWindowPointerDown = (e: PointerEvent) => {
      const canvas = canvasRef.current;
      if (!canvas || !isWithinCanvas(e.clientX, e.clientY)) return;
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const now = performance.now();
      const streak = clickStreakRef.current;
      // A click within the streak window escalates; a gap resets to
      // baseline ("multiple clicks in a row make it more violent" -- a
      // single isolated click should NOT be more violent than before).
      streak.count =
        now - streak.lastClickAt <= CLICK_STREAK_WINDOW_MS ? streak.count + 1 : 1;
      streak.lastClickAt = now;
      const violence = Math.min(MAX_VIOLENCE, 1 + (streak.count - 1) * 0.6);

      particlesRef.current.push(
        ...spawnExplosion(x, y, EXPLOSION_COUNT, 80, 260, 1.1, violence),
      );
    };

    window.addEventListener("pointermove", onWindowPointerMove);
    window.addEventListener("pointerdown", onWindowPointerDown);
    return () => {
      window.removeEventListener("pointermove", onWindowPointerMove);
      window.removeEventListener("pointerdown", onWindowPointerDown);
    };
  }, []);

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
