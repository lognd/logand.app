import { describe, expect, it } from "vitest";
import {
  generateShape,
  rasterizeShape,
  rotatePoint,
  type SurfacePoint,
} from "../../src/ascii/shapes";

describe("rotatePoint", () => {
  it("returns to the original point after a full 360 degree rotation", () => {
    const p = { x: 1, y: 2, z: 3 };
    const fullTurn = 2 * Math.PI;
    const rotated = rotatePoint(p, fullTurn, fullTurn);
    expect(rotated.x).toBeCloseTo(p.x, 5);
    expect(rotated.y).toBeCloseTo(p.y, 5);
    expect(rotated.z).toBeCloseTo(p.z, 5);
  });

  it("rotating by 0 is the identity", () => {
    const p = { x: 1, y: -2, z: 0.5 };
    const rotated = rotatePoint(p, 0, 0);
    expect(rotated).toEqual(p);
  });
});

describe("generateShape", () => {
  it("donut produces a dense, bounded point cloud", () => {
    const points = generateShape("donut");
    expect(points.length).toBeGreaterThan(1000);
    for (const { position } of points) {
      expect(Math.abs(position.x)).toBeLessThanOrEqual(2.2);
      expect(Math.abs(position.y)).toBeLessThanOrEqual(0.7);
      expect(Math.abs(position.z)).toBeLessThanOrEqual(2.2);
    }
  });

  it("sphere points all sit at the configured radius", () => {
    const points = generateShape("sphere");
    expect(points.length).toBeGreaterThan(1000);
    for (const { position } of points) {
      const r = Math.hypot(position.x, position.y, position.z);
      expect(r).toBeCloseTo(1.6, 1);
    }
  });

  it("cube points stay within the configured half-side bound", () => {
    const points = generateShape("cube");
    expect(points.length).toBeGreaterThan(1000);
    for (const { position } of points) {
      expect(Math.abs(position.x)).toBeLessThanOrEqual(1.3 + 1e-9);
      expect(Math.abs(position.y)).toBeLessThanOrEqual(1.3 + 1e-9);
      expect(Math.abs(position.z)).toBeLessThanOrEqual(1.3 + 1e-9);
    }
  });
});

describe("rasterizeShape z-buffer", () => {
  it("keeps the nearer of two overlapping points for a given cell", () => {
    // Two points that project to the same cell (same x/y, different z) --
    // the nearer one (larger z, closer to the camera placed at +z) should
    // win and contribute its brightness, not be overwritten by the farther
    // one regardless of point order.
    const near: SurfacePoint = {
      position: { x: 0, y: 0, z: 1 },
      normal: { x: 0, y: 0, z: 1 }, // faces the light -> bright
    };
    const far: SurfacePoint = {
      position: { x: 0, y: 0, z: -1 },
      normal: { x: 0, y: 0, z: -1 }, // faces away from the light -> dark
    };

    const ramp = " .:-=+*#%@";
    const gridFarFirst = rasterizeShape([far, near], 0, 0, 20, 20, ramp);
    const gridNearFirst = rasterizeShape([near, far], 0, 0, 20, 20, ramp);

    const centerCellFarFirst = gridFarFirst[10][10];
    const centerCellNearFirst = gridNearFirst[10][10];

    // Order must not matter -- the z-buffer picks the nearer point either way.
    expect(centerCellFarFirst.brightness).toBeCloseTo(
      centerCellNearFirst.brightness,
      5,
    );
    expect(centerCellFarFirst.brightness).toBeGreaterThan(0);
  });

  it("produces a cols x rows grid", () => {
    const points = generateShape("sphere");
    const grid = rasterizeShape(points, 0.3, 0.7, 40, 20);
    expect(grid.length).toBe(20);
    for (const row of grid) {
      expect(row.length).toBe(40);
    }
  });
});
