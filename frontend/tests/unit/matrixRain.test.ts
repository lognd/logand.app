import { describe, expect, it } from "vitest";
import {
  createParticle,
  createStreams,
  heatColor,
  spawnExplosion,
  spawnTrail,
  stepParticle,
  stepParticles,
  stepStreams,
} from "../../src/ascii/matrixRain";

describe("stepParticle", () => {
  it("integrates real gravity physics into the underlying trajectory", () => {
    const p = createParticle(0, 0, 0, 0, 10, "*", "trail", 18);
    const stepped = stepParticle(p, 1, 100);
    expect(stepped).not.toBeNull();
    expect(stepped!.vy).toBeCloseTo(100, 5);
    expect(stepped!.physY).toBeCloseTo(0, 5); // vy was 0 for this 1s step
  });

  it("updates physX/physY from velocity even before a render-snap fires", () => {
    const p = createParticle(0, 0, 10, 20, 10, "*", "trail", 18);
    const stepped = stepParticle(p, 0.5, 0);
    expect(stepped).not.toBeNull();
    expect(stepped!.physX).toBeCloseTo(5, 5);
    expect(stepped!.physY).toBeCloseTo(10, 5);
  });

  it("the rendered x/y only re-snaps to a whole grid cell, not every frame", () => {
    const p = createParticle(0, 0, 100, 0, 10, "*", "trail", 18);
    // Large dt guarantees at least one render-snap regardless of the
    // particle's randomized stepIntervalMs.
    const stepped = stepParticle(p, 0.5, 0);
    expect(stepped).not.toBeNull();
    expect(stepped!.x % 18).toBeCloseTo(0, 5);
    expect(stepped!.y % 18).toBeCloseTo(0, 5);
  });

  it("dies (returns null) once its lifetime has elapsed", () => {
    const p = createParticle(0, 0, 0, 0, 1);
    expect(stepParticle(p, 0.5)).not.toBeNull();
    expect(stepParticle(p, 1)).toBeNull();
    expect(stepParticle(p, 1.5)).toBeNull();
  });

  it("does not mutate the input particle (pure)", () => {
    const p = createParticle(0, 0, 1, 1, 10);
    const before = { ...p };
    stepParticle(p, 1, 50);
    expect(p).toEqual(before);
  });
});

describe("stepParticles", () => {
  it("drops expired particles from the returned list", () => {
    const alive = createParticle(0, 0, 0, 0, 10);
    const dead = createParticle(0, 0, 0, 0, 0.1);
    const next = stepParticles([alive, dead], 1);
    expect(next).toHaveLength(1);
  });
});

describe("spawnExplosion", () => {
  it("produces the requested particle count, each with nonzero outward velocity", () => {
    const particles = spawnExplosion(100, 100, 20);
    expect(particles).toHaveLength(20);
    for (const p of particles) {
      expect(p.physX).toBe(100);
      expect(p.physY).toBe(100);
      const speed = Math.hypot(p.vx, p.vy);
      expect(speed).toBeGreaterThan(0);
    }
  });

  it("radiates in varied directions, not all the same angle", () => {
    const particles = spawnExplosion(0, 0, 30);
    const angles = new Set(particles.map((p) => Math.atan2(p.vy, p.vx).toFixed(2)));
    expect(angles.size).toBeGreaterThan(1);
  });

  it("particles spawned by spawnExplosion are tagged kind: explosion", () => {
    const particles = spawnExplosion(0, 0, 5);
    for (const p of particles) expect(p.kind).toBe("explosion");
  });

  it("a higher violence multiplier produces more, faster particles", () => {
    const baseline = spawnExplosion(0, 0, 20, 100, 100, 1, 1);
    const violent = spawnExplosion(0, 0, 20, 100, 100, 1, 3);
    expect(violent.length).toBeGreaterThan(baseline.length);
    const baselineSpeed = Math.hypot(baseline[0].vx, baseline[0].vy);
    const violentSpeed = Math.hypot(violent[0].vx, violent[0].vy);
    expect(violentSpeed).toBeGreaterThan(baselineSpeed);
  });
});

describe("spawnTrail", () => {
  it("spawns particles at each point along the given path", () => {
    const path = [
      { x: 0, y: 0 },
      { x: 10, y: 5 },
      { x: 20, y: 10 },
    ];
    const particles = spawnTrail(path, 2);
    expect(particles).toHaveLength(path.length * 2);
  });

  it("spawned particles fall (positive vy) rather than radiate outward", () => {
    const particles = spawnTrail([{ x: 0, y: 0 }], 5);
    for (const p of particles) {
      expect(p.vy).toBeGreaterThan(0);
    }
  });

  it("particles spawned by spawnTrail are tagged kind: trail", () => {
    const particles = spawnTrail([{ x: 0, y: 0 }], 3);
    for (const p of particles) expect(p.kind).toBe("trail");
  });
});

describe("heatColor", () => {
  it("returns a brighter (higher-lightness) color for a fresher particle", () => {
    const fresh = heatColor(1);
    const dying = heatColor(0);
    const lightnessOf = (hsl: string) => Number(hsl.match(/(\d+)%\)$/)?.[1]);
    expect(lightnessOf(fresh)).toBeGreaterThan(lightnessOf(dying));
  });

  it("clamps out-of-range input instead of producing an invalid color", () => {
    expect(() => heatColor(-1)).not.toThrow();
    expect(() => heatColor(2)).not.toThrow();
  });
});

describe("ambient streams", () => {
  it("createStreams fills one column per cell-width of the viewport", () => {
    const streams = createStreams(100, 200, 18);
    expect(streams.length).toBe(Math.floor(100 / 18));
  });

  it("stepStreams steps a column downward by whole cells over time, not continuously", () => {
    const streams = createStreams(100, 200, 18);
    const before = streams.map((s) => s.y);
    // Large dt guarantees at least one step for every column regardless of
    // its randomized stepIntervalMs.
    const after = stepStreams(streams, 1, 200, 18);
    for (let i = 0; i < streams.length; i++) {
      const delta = after[i].y - before[i];
      // Either it respawned at the top (delta can be anything) or it
      // stepped down by a whole multiple of the cell size.
      if (after[i].y >= before[i]) {
        // delta should be a whole multiple of 18 -- check distance to the
        // nearest multiple rather than `delta % 18` directly, since for a
        // delta just under one cell-size (e.g. 17.9999999999997 from
        // float drift across repeated additions) the naive modulo is
        // itself ~18, not ~0.
        const nearestMultiple = Math.round(delta / 18) * 18;
        expect(Math.abs(delta - nearestMultiple)).toBeLessThan(1e-6);
      }
    }
  });
});
