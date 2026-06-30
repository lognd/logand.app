import { useEffect, useRef, useState } from "react";
import { BUTTON_CLASS } from "../styles/a11y";
import {
  createStreams,
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

// Matrix rain is a specific-enough aesthetic reference that a brighter,
// more saturated green than the muted Gruvbox --accent-green reads
// correctly here -- a near-desaturated Gruvbox tone looks washed out for
// this particular effect. HEAD_COLOR is the leading/brightest character of
// each ambient stream and the freshest particles; TRAIL_COLOR is the
// fading body, closer to the site's existing --accent-green so the effect
// still feels related to the rest of the palette rather than a clashing
// foreign color.
const HEAD_COLOR = "#7CFC9A";
const TRAIL_COLOR = "#3a7d4a";

/**
 * Optional, off-by-default interactive background: ambient falling-glyph
 * rain, plus a trail of rain spawned along the pointer's recent path and a
 * physics-driven "explosion" of rain on click/tap. Renders to a <canvas>
 * rather than DOM text nodes (unlike AsciiCanvas/SpinningShape) because a
 * few hundred independently-moving particles re-rendered as React state
 * every frame would mean a few hundred DOM node text mutations per frame --
 * canvas draw calls are dramatically cheaper at this particle count and
 * this effect has no need to be selectable/copyable text the way the
 * decorative ASCII shapes arguably do.
 *
 * Off by default (renders only its own toggle button until switched on) --
 * the user asked for this to be an "optional background", not forced site-
 * wide. Mount it once, anywhere full-bleed is appropriate (it positions
 * itself via the `className` you pass, same convention as AsciiCanvas).
 */
export function MatrixRain({ className }: { className?: string }) {
  const [enabled, setEnabled] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamsRef = useRef<RainStream[]>([]);
  const particlesRef = useRef<Particle[]>([]);
  const reducedMotionRef = useRef(false);
  const recentPathRef = useRef<{ x: number; y: number }[]>([]);

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
    if (!enabled) return;
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

      ctx.clearRect(0, 0, rect.width, rect.height);
      ctx.font = `${CELL_SIZE * 0.85}px "JetBrains Mono", monospace`;
      ctx.textBaseline = "top";

      // Ambient falling rain -- the idle look. Skipped entirely under
      // prefers-reduced-motion, same convention as SpinningShape's
      // auto-rotation: autoplaying motion is suppressed, user-triggered
      // effects (trail/explosion, below) are not, since those only ever
      // happen in direct response to the user's own input.
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

      // Trail + explosion particles always run (user-initiated, not autoplay).
      particlesRef.current = stepParticles(particlesRef.current, dtSeconds);
      for (const p of particlesRef.current) {
        const lifeFrac = 1 - p.age / p.lifetime;
        ctx.fillStyle = lifeFrac > 0.6 ? HEAD_COLOR : TRAIL_COLOR;
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
  }, [enabled]);

  // No preventDefault and no setPointerCapture anywhere in this component:
  // we only ever read pointer coordinates to spawn particles, never claim
  // exclusive control of the gesture, so native touch scrolling/panning is
  // completely unaffected -- pointermove still fires with coordinates
  // alongside the browser's own scroll handling, which is the simplest
  // possible resolution to "wants every pointer position" vs. "must not
  // trap mobile scroll".
  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!enabled) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const point = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    const path = recentPathRef.current;
    path.push(point);
    if (path.length > MAX_TRAIL_POINTS_PER_FRAME) path.shift();
    particlesRef.current.push(...spawnTrail([point], TRAIL_PARTICLES_PER_MOVE));
  };

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!enabled) return;
    const rect = e.currentTarget.getBoundingClientRect();
    particlesRef.current.push(
      ...spawnExplosion(e.clientX - rect.left, e.clientY - rect.top, EXPLOSION_COUNT),
    );
  };

  return (
    <>
      {enabled && (
        <canvas
          ref={canvasRef}
          aria-hidden="true"
          className={className}
          onPointerMove={onPointerMove}
          onPointerDown={onPointerDown}
        />
      )}
      <button
        type="button"
        aria-pressed={enabled}
        aria-label={enabled ? "Turn off matrix rain background" : "Turn on matrix rain background"}
        onClick={() => setEnabled((v) => !v)}
        className={`${BUTTON_CLASS} fixed bottom-4 right-4 z-50`}
      >
        {enabled ? "Rain: on" : "Rain: off"}
      </button>
    </>
  );
}
