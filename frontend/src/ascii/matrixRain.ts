// Pure, framework-agnostic simulation for the optional "Matrix rain"
// interactive background: ambient falling-character streams (the classic
// idle look) plus a simple 2D particle system for two user-triggered
// effects -- a trail spawned along the pointer's recent path, and an
// outward "explosion" spawned on click/tap. Kept separate from
// MatrixRain.tsx so the physics is unit-testable without mounting a
// component or a <canvas>, same pattern as shapes.ts for SpinningShape.

// A katakana glyph set is more visually "Matrix," but the project has a
// hard no-non-ASCII-characters rule (see CLAUDE.md / docs/design
// conventions), so this stays strictly ASCII -- a mix of digits and
// symbols gives a similarly dense, glitchy texture without it.
export const RAIN_GLYPHS = "01:;+*=-<>/\\|";

export function randomGlyph(): string {
  return RAIN_GLYPHS[Math.floor(Math.random() * RAIN_GLYPHS.length)];
}

// Distinguishes click-explosion particles from pointer-trail particles so
// the renderer can color them differently (bright red/heat-curve for
// explosions, blue for the trail) -- separate from the ambient green rain
// streams, which aren't Particles at all (see RainStream below). Both
// kinds are stationary glyph-flashes (a grid-bound "ignite," not a flying
// particle) -- there is no physics-driven variant; an earlier version had
// one, removed per feedback preferring the grid-bound look exclusively.
export type ParticleKind = "trail" | "explosion";

export interface Particle {
  // Rendered (grid-snapped) position -- this is what MatrixRain.tsx draws
  // at. It only changes in whole-cell jumps on a timer, never smoothly.
  x: number;
  y: number;
  // True continuous physics position/velocity underneath the snapped
  // render position -- real 2D gravity simulation (Euler-integrated every
  // call, same as the project's other physics, e.g. shapes.ts), so the
  // underlying trajectory genuinely arcs outward and falls. (x, y) above
  // is just (physX, physY) rounded to the nearest cell whenever a step
  // fires, which is what gives "real gravity physics" + "step-like, not
  // translation" at the same time.
  physX: number;
  physY: number;
  vx: number;
  vy: number;
  char: string;
  age: number;
  lifetime: number;
  kind: ParticleKind;
  // Discrete-step timing, same model as RainStream below -- ms between
  // render-position snaps, and ms accumulated toward the next one.
  // Optional so a literal without these still type-checks; createParticle
  // always sets them.
  cellSize?: number;
  stepIntervalMs?: number;
  accumulatedMs?: number;
}

export interface RainStream {
  x: number;
  y: number;
  length: number;
  chars: string[];
  // Discrete-step timing (see stepStreams) -- ms between downward steps,
  // and ms accumulated toward the next one. Optional only so a freshly
  // constructed literal without these (e.g. in a test) still type-checks;
  // spawnStream always sets them.
  stepIntervalMs?: number;
  accumulatedMs?: number;
}

// Render position re-snaps to the physics position on this schedule --
// fast enough to track the underlying arc closely, slow enough to read as
// discrete jumps rather than a smooth slide.
const PARTICLE_STEP_INTERVAL_MIN_MS = 60;
const PARTICLE_STEP_INTERVAL_MAX_MS = 140;

const GRAVITY = 480; // px/s^2 -- gentle enough that debris arcs visibly before falling off-screen

export function createParticle(
  x: number,
  y: number,
  vx: number,
  vy: number,
  lifetime: number,
  char: string = randomGlyph(),
  kind: ParticleKind = "trail",
  cellSize = 18,
): Particle {
  return {
    x,
    y,
    physX: x,
    physY: y,
    vx,
    vy,
    char,
    age: 0,
    lifetime,
    kind,
    cellSize,
    stepIntervalMs:
      PARTICLE_STEP_INTERVAL_MIN_MS +
      Math.random() * (PARTICLE_STEP_INTERVAL_MAX_MS - PARTICLE_STEP_INTERVAL_MIN_MS),
    accumulatedMs: 0,
  };
}

// Chance per second that a single particle's glyph rerolls -- gives the
// classic Matrix "glitching" look (the same particle visibly changes
// character over its lifetime, not just at spawn).
const PARTICLE_GLYPH_MUTATION_RATE = 4;

/**
 * Pure: returns a new Particle one step forward, or null if its lifetime
 * expired. Two things happen every call:
 *  1. Real continuous 2D physics (Euler-integrated): physX/physY advance
 *     by velocity, vy accumulates gravity -- "it needs to act like 2D
 *     physics with gravity," same model as a classic particle system.
 *  2. The RENDERED x/y only re-snaps to the current physics position on
 *     a timer (see stepIntervalMs), rounded to the nearest grid cell --
 *     "step-like... not by translation." The glyph genuinely follows a
 *     gravity arc, it just visibly jumps cell-to-cell rather than
 *     sliding smoothly along it.
 */
export function stepParticle(
  p: Particle,
  dtSeconds: number,
  gravity: number = GRAVITY,
): Particle | null {
  const age = p.age + dtSeconds;
  if (age >= p.lifetime) return null;
  const char =
    Math.random() < PARTICLE_GLYPH_MUTATION_RATE * dtSeconds ? randomGlyph() : p.char;

  const physX = p.physX + p.vx * dtSeconds;
  const physY = p.physY + p.vy * dtSeconds;
  const vy = p.vy + gravity * dtSeconds;

  let x = p.x;
  let y = p.y;
  let accumulatedMs = (p.accumulatedMs ?? 0) + dtSeconds * 1000;
  const interval = p.stepIntervalMs ?? PARTICLE_STEP_INTERVAL_MIN_MS;
  const cellSize = p.cellSize ?? 18;
  if (accumulatedMs >= interval) {
    accumulatedMs %= interval;
    x = Math.round(physX / cellSize) * cellSize;
    y = Math.round(physY / cellSize) * cellSize;
  }

  return { ...p, age, char, x, y, physX, physY, vy, accumulatedMs };
}

export function stepParticles(
  particles: Particle[],
  dtSeconds: number,
  gravity: number = GRAVITY,
): Particle[] {
  const next: Particle[] = [];
  for (const p of particles) {
    const stepped = stepParticle(p, dtSeconds, gravity);
    if (stepped) next.push(stepped);
  }
  return next;
}

// Fraction of lifeFrac (from 1 down to this threshold) spent in the
// fast white -> yellow falloff; below the threshold is the slower
// yellow -> orange -> red cooldown.
const HEAT_WHITE_THRESHOLD = 0.7;

// Classic "heat map" gradient: dim red (cooling/dying, slow) -> orange ->
// yellow -> white-hot (freshly spawned, fast falloff). `lifeFrac` is 1 at
// spawn, 0 at death, matching how MatrixRain.tsx already tracks particle
// age. Per feedback the orange/red cooldown read well already; only the
// hot end needed work -- it now starts genuinely white (high lightness,
// desaturating) and drops through yellow quickly (the top 30% of
// lifeFrac), spending the remaining, larger range easing through
// orange to red exactly as before.
export function heatColor(lifeFrac: number): string {
  const t = Math.max(0, Math.min(1, lifeFrac));

  if (t > HEAT_WHITE_THRESHOLD) {
    const u = (t - HEAT_WHITE_THRESHOLD) / (1 - HEAT_WHITE_THRESHOLD); // 0..1
    const hue = 48; // yellow
    const sat = 85 - u * 55; // desaturating toward white as u -> 1
    const light = 65 + u * 30; // 65% -> 95% (white-hot)
    return `hsl(${hue} ${sat.toFixed(0)}% ${light.toFixed(0)}%)`;
  }

  const u = t / HEAT_WHITE_THRESHOLD; // 0..1
  const hue = 8 + u * 40; // ~8 (red) -> ~48 (yellow)
  const sat = 90;
  const light = 35 + u * 30; // 35% (dim ember) -> 65%
  return `hsl(${hue.toFixed(0)} ${sat}% ${light.toFixed(0)}%)`;
}

/**
 * Pointer-move trail: spawns particles along the pointer's recent path,
 * each with a gentle downward + slight sideways velocity (real gravity
 * physics, see stepParticle) so it reads as "rain following the cursor"
 * rather than a static flare -- but rendered with the same grid-snapped
 * stepping as everything else, not a smooth slide.
 *
 * `cellSize` scales both the jitter/velocity magnitudes AND the grid-snap
 * step (passed through to createParticle) relative to the 18px reference
 * they were originally tuned at -- these used to be hardcoded regardless
 * of the caller's actual on-screen cell size, so on a phone viewport
 * (where ParticleLayer.tsx's cellSize is much smaller than 18px, see
 * useResponsiveGrid.ts) particles still traveled the same absolute pixel
 * distances, which relative to the now-tiny glyphs read as "spacing...
 * too big."
 */
export function spawnTrail(
  path: { x: number; y: number }[],
  particlesPerPoint = 1,
  lifetime = 0.6,
  // Defaults to the original design-reference cell size (18px) so every
  // existing call site/test that doesn't pass one keeps its old behavior
  // exactly. `cellScale` below is relative to that reference -- see its
  // doc comment.
  cellSize = 18,
): Particle[] {
  const cellScale = cellSize / 18;
  const particles: Particle[] = [];
  for (const point of path) {
    for (let i = 0; i < particlesPerPoint; i++) {
      const jitterX = (Math.random() - 0.5) * 8 * cellScale;
      particles.push(
        createParticle(
          point.x + jitterX,
          point.y,
          (Math.random() - 0.5) * 20 * cellScale,
          (40 + Math.random() * 60) * cellScale,
          lifetime * (0.7 + Math.random() * 0.6),
          undefined,
          "trail",
          cellSize,
        ),
      );
    }
  }
  return particles;
}

/**
 * Click/tap "explosion": particles radiate outward from (x, y) at random
 * angles across a full circle with randomized speed, real gravity (see
 * stepParticle) pulling them into a falling arc over their lifetime --
 * "it needs to act like 2D physics with gravity," not a static flare.
 * `violence` (>= 1) scales both particle count and speed -- the caller
 * derives this from how rapidly the user is clicking (see
 * MatrixRain.tsx's clickStreakRef) so a quick burst of clicks escalates
 * into a bigger, faster explosion than a single isolated click.
 *
 * `cellSize` scales the outward speed (and the grid-snap step, passed
 * through to createParticle) relative to the 18px reference it was
 * originally tuned at -- see spawnTrail's identical doc comment for why
 * ("the spacing between the explosion is too big on mobile").
 */
export function spawnExplosion(
  x: number,
  y: number,
  count: number,
  minSpeed = 80,
  maxSpeed = 260,
  lifetime = 1.1,
  violence = 1,
  cellSize = 18,
): Particle[] {
  const cellScale = cellSize / 18;
  const particles: Particle[] = [];
  const scaledCount = Math.round(count * violence);
  const speedScale = 1 + (violence - 1) * 0.5; // speed escalates more gently than count
  for (let i = 0; i < scaledCount; i++) {
    const angle = Math.random() * Math.PI * 2;
    const speed = (minSpeed + Math.random() * (maxSpeed - minSpeed)) * speedScale * cellScale;
    particles.push(
      createParticle(
        x,
        y,
        Math.cos(angle) * speed,
        Math.sin(angle) * speed,
        lifetime * (0.7 + Math.random() * 0.6),
        undefined,
        "explosion",
        cellSize,
      ),
    );
  }
  return particles;
}

/** Ambient layer: one falling-character column per cell-width of the viewport. */
export function createStreams(width: number, height: number, cellSize: number): RainStream[] {
  const cols = Math.max(1, Math.floor(width / cellSize));
  const streams: RainStream[] = [];
  for (let i = 0; i < cols; i++) {
    streams.push(spawnStream(i * cellSize, height));
  }
  return streams;
}

// Time between discrete downward steps -- the rain visibly falls (a new
// row appears at the top, everything shifts down one cell) but as a
// grid-stepped jump, not a continuously-translating pixel scroll. "It
// needs to be step-like" / "visibly move downward, but not by
// translation."
const STEP_INTERVAL_MIN_MS = 60;
const STEP_INTERVAL_MAX_MS = 140;

function spawnStream(x: number, height: number): RainStream {
  const length = 6 + Math.floor(Math.random() * 14);
  return {
    x,
    y: -Math.random() * height,
    length,
    chars: Array.from({ length }, randomGlyph),
    stepIntervalMs:
      STEP_INTERVAL_MIN_MS + Math.random() * (STEP_INTERVAL_MAX_MS - STEP_INTERVAL_MIN_MS),
    accumulatedMs: Math.random() * STEP_INTERVAL_MAX_MS, // stagger columns' first step
  };
}

/** Pure: advances each stream by whole-cell steps on its own schedule
 * (see stepIntervalMs) rather than continuous sub-pixel translation -- a
 * stream that has fully fallen past the bottom respawns at the top of the
 * same column rather than being removed, since the ambient layer should
 * rain continuously, not deplete. Each step also mutates a handful of
 * characters so the trail visibly glitches/flickers (the defining
 * "Matrix" look) on top of the downward stepping. */
export function stepStreams(
  streams: RainStream[],
  dtSeconds: number,
  height: number,
  cellSize: number,
): RainStream[] {
  return streams.map((s) => {
    let y = s.y;
    let accumulatedMs = (s.accumulatedMs ?? 0) + dtSeconds * 1000;
    let chars = s.chars;
    const interval = s.stepIntervalMs ?? STEP_INTERVAL_MIN_MS;

    let mutated = false;
    while (accumulatedMs >= interval) {
      accumulatedMs -= interval;
      y += cellSize;
      if (!mutated) {
        chars = chars.slice();
        mutated = true;
      }
      // Mutate several characters per step (bumped up per feedback that
      // it "needs to mutate more") -- enough to read as a properly
      // glitching trail rather than a quiet flicker.
      const mutationCount = 2 + Math.floor(Math.random() * 3); // 2-4 per step
      for (let m = 0; m < mutationCount; m++) {
        chars[Math.floor(Math.random() * chars.length)] = randomGlyph();
      }
    }

    if (y - s.length * cellSize > height) {
      return spawnStream(s.x, height);
    }
    return { ...s, y, accumulatedMs, chars };
  });
}
