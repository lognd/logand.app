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

export interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  char: string;
  age: number;
  lifetime: number;
}

export interface RainStream {
  x: number;
  y: number;
  speed: number;
  length: number;
  chars: string[];
}

const GRAVITY = 480; // px/s^2 -- gentle enough that explosion debris arcs visibly before falling off-screen

export function createParticle(
  x: number,
  y: number,
  vx: number,
  vy: number,
  lifetime: number,
  char: string = randomGlyph(),
): Particle {
  return { x, y, vx, vy, char, age: 0, lifetime };
}

/** Pure: returns a new Particle one step forward, or null if its lifetime expired. */
export function stepParticle(
  p: Particle,
  dtSeconds: number,
  gravity: number = GRAVITY,
): Particle | null {
  const age = p.age + dtSeconds;
  if (age >= p.lifetime) return null;
  return {
    ...p,
    x: p.x + p.vx * dtSeconds,
    y: p.y + p.vy * dtSeconds,
    vy: p.vy + gravity * dtSeconds,
    age,
  };
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

/**
 * Click/tap "explosion": particles radiate outward from (x, y) at random
 * angles across a full circle, with randomized speed within [minSpeed,
 * maxSpeed] -- gravity (applied in stepParticle) pulls them into a falling
 * arc over their lifetime, which is what makes this read as a small physics
 * "pop" rather than a static starburst.
 */
export function spawnExplosion(
  x: number,
  y: number,
  count: number,
  minSpeed = 80,
  maxSpeed = 260,
  lifetime = 1.1,
): Particle[] {
  const particles: Particle[] = [];
  for (let i = 0; i < count; i++) {
    const angle = Math.random() * Math.PI * 2;
    const speed = minSpeed + Math.random() * (maxSpeed - minSpeed);
    particles.push(
      createParticle(
        x,
        y,
        Math.cos(angle) * speed,
        Math.sin(angle) * speed,
        lifetime * (0.7 + Math.random() * 0.6),
      ),
    );
  }
  return particles;
}

/**
 * Drag/move trail: spawns particles along a path of recent pointer
 * positions (oldest to newest), each falling gently downward like rain
 * rather than flying outward -- this is what makes a dragged path read as
 * "rain following the cursor" instead of a second explosion.
 */
export function spawnTrail(
  path: { x: number; y: number }[],
  particlesPerPoint = 1,
  lifetime = 0.6,
): Particle[] {
  const particles: Particle[] = [];
  for (const point of path) {
    for (let i = 0; i < particlesPerPoint; i++) {
      const jitterX = (Math.random() - 0.5) * 8;
      particles.push(
        createParticle(
          point.x + jitterX,
          point.y,
          (Math.random() - 0.5) * 20,
          40 + Math.random() * 60,
          lifetime * (0.7 + Math.random() * 0.6),
        ),
      );
    }
  }
  return particles;
}

/** Ambient layer: one falling-character column per cell-width of the viewport. */
export function createStreams(width: number, height: number, cellSize: number): RainStream[] {
  const cols = Math.max(1, Math.floor(width / cellSize));
  const streams: RainStream[] = [];
  for (let i = 0; i < cols; i++) {
    streams.push(spawnStream(i * cellSize, width, height));
  }
  return streams;
}

function spawnStream(x: number, _width: number, height: number): RainStream {
  const length = 6 + Math.floor(Math.random() * 14);
  return {
    x,
    y: -Math.random() * height,
    speed: 120 + Math.random() * 220,
    length,
    chars: Array.from({ length }, randomGlyph),
  };
}

/** Pure: advances each stream; a stream that has fully fallen past the
 * bottom respawns at the top of the same column rather than being removed,
 * since the ambient layer should rain continuously, not deplete. */
export function stepStreams(
  streams: RainStream[],
  dtSeconds: number,
  height: number,
  cellSize: number,
): RainStream[] {
  return streams.map((s) => {
    const y = s.y + s.speed * dtSeconds;
    if (y - s.length * cellSize > height) {
      return spawnStream(s.x, 0, height);
    }
    // Occasionally mutate one character so the trail glitches/flickers,
    // matching the source-material look, instead of static strings falling.
    const chars =
      Math.random() < 0.05 * dtSeconds * 60
        ? [...s.chars.slice(0, -1), randomGlyph()]
        : s.chars;
    return { ...s, y, chars };
  });
}
