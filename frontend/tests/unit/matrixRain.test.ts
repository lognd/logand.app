import { describe, expect, it } from "vitest";
import {
  createParticle,
  spawnExplosion,
  spawnTrail,
  stepParticle,
  stepParticles,
} from "../../src/ascii/matrixRain";

describe("stepParticle", () => {
  it("applies gravity to vertical velocity over time", () => {
    const p = createParticle(0, 0, 0, 0, 10);
    const stepped = stepParticle(p, 1, 100);
    expect(stepped).not.toBeNull();
    expect(stepped!.vy).toBeCloseTo(100, 5);
  });

  it("updates position from velocity", () => {
    const p = createParticle(0, 0, 10, 20, 10);
    const stepped = stepParticle(p, 0.5, 0);
    expect(stepped).not.toBeNull();
    expect(stepped!.x).toBeCloseTo(5, 5);
    expect(stepped!.y).toBeCloseTo(10, 5);
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
      expect(p.x).toBe(100);
      expect(p.y).toBe(100);
      const speed = Math.hypot(p.vx, p.vy);
      expect(speed).toBeGreaterThan(0);
    }
  });

  it("radiates in varied directions, not all the same angle", () => {
    const particles = spawnExplosion(0, 0, 30);
    const angles = new Set(particles.map((p) => Math.atan2(p.vy, p.vx).toFixed(2)));
    expect(angles.size).toBeGreaterThan(1);
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
});
