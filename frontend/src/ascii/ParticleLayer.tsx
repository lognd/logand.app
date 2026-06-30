import { useEffect, useRef } from "react";
import {
  heatColor,
  spawnExplosion,
  spawnTrail,
  stepParticles,
  type Particle,
} from "./matrixRain";

const CELL_SIZE = 18; // px per character cell -- matches MatrixRain's ambient grid
const EXPLOSION_COUNT = 36;
const TRAIL_PARTICLES_PER_MOVE = 1;
const MAX_TRAIL_POINTS_PER_FRAME = 6; // cap how many path points one pointermove can spawn from, for fast drags

// Rapid-fire clicks within this window (ms) count toward the same
// "streak" and escalate explosion violence; a click after a longer gap
// resets the streak back to baseline.
const CLICK_STREAK_WINDOW_MS = 600;
const MAX_VIOLENCE = 4;

// Pointer-trail particles are blue; explosions follow heatColor's red ->
// orange -> yellow -> white curve (see matrixRain.ts).
const TRAIL_PARTICLE_HEAD_COLOR = "#7CC7FC";
const TRAIL_PARTICLE_TAIL_COLOR = "#2f5d80";

/**
 * The click/drag particle interaction (blue pointer trail + heat-colored,
 * gravity-physics "explosion" on click/tap, rapid clicks escalating
 * violence) extracted out of MatrixRain so it can layer on top of ANY
 * background -- not just the "Rain" option -- per explicit feedback ("I
 * actually really like the mouse drag and explosion... I don't see the
 * trail and explosion on the donut and cube and globe"). MatrixRain still
 * owns its own ambient falling-rain look; this is purely the interactive
 * layer, transparent (no backdrop fill) so it composites over whatever's
 * underneath.
 *
 * Same window-level pointer listeners as everything else in ascii/ --
 * real page content sits on top and is hit-testable, so an element-scoped
 * listener would stop firing under text/links.
 */
export function ParticleLayer({ className }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const particlesRef = useRef<Particle[]>([]);
  const recentPathRef = useRef<{ x: number; y: number }[]>([]);
  const clickStreakRef = useRef<{ count: number; lastClickAt: number }>({
    count: 0,
    lastClickAt: 0,
  });

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
    };
    resize();
    window.addEventListener("resize", resize);

    const render = (now: number) => {
      const dtSeconds = Math.min((now - lastTime) / 1000, 0.05);
      lastTime = now;
      const rect = canvas.getBoundingClientRect();

      // Transparent -- clearRect, not a backdrop fill, so this composites
      // over whatever background is currently mounted underneath it.
      ctx.clearRect(0, 0, rect.width, rect.height);
      ctx.font = `${CELL_SIZE * 0.85}px "JetBrains Mono", monospace`;
      ctx.textBaseline = "top";

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
      // Same device-pixel-ratio / CSS-size pinning as the other canvases
      // (see AsciiCanvas/MatrixRain/SpinningShape) -- prevents the
      // overflow bug where a canvas's layout box defaults to its
      // attribute dimensions instead of 100% of its container.
      style={{ width: "100%", height: "100%" }}
    />
  );
}
