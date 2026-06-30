import { describe, expect, it } from "vitest";
import {
  generateShape,
  quatFromAxisAngle,
  quatIdentity,
  quatMultiply,
  rasterizeShape,
  rotateByQuaternion,
  type SurfacePoint,
} from "../../src/ascii/shapes";

describe("rotateByQuaternion", () => {
  it("returns to the original point after a full 360 degree rotation", () => {
    const p = { x: 1, y: 2, z: 3 };
    const fullTurn = 2 * Math.PI;
    const q = quatMultiply(
      quatFromAxisAngle({ x: 1, y: 0, z: 0 }, fullTurn),
      quatFromAxisAngle({ x: 0, y: 1, z: 0 }, fullTurn),
    );
    const rotated = rotateByQuaternion(p, q);
    expect(rotated.x).toBeCloseTo(p.x, 4);
    expect(rotated.y).toBeCloseTo(p.y, 4);
    expect(rotated.z).toBeCloseTo(p.z, 4);
  });

  it("the identity quaternion leaves a point unchanged", () => {
    const p = { x: 1, y: -2, z: 0.5 };
    const rotated = rotateByQuaternion(p, quatIdentity());
    expect(rotated.x).toBeCloseTo(p.x, 10);
    expect(rotated.y).toBeCloseTo(p.y, 10);
    expect(rotated.z).toBeCloseTo(p.z, 10);
  });

  it("rotating 90 degrees around Y maps +X to -Z (right-hand rule)", () => {
    const p = { x: 1, y: 0, z: 0 };
    const q = quatFromAxisAngle({ x: 0, y: 1, z: 0 }, Math.PI / 2);
    const rotated = rotateByQuaternion(p, q);
    expect(rotated.x).toBeCloseTo(0, 5);
    expect(rotated.y).toBeCloseTo(0, 5);
    expect(rotated.z).toBeCloseTo(-1, 5);
  });

  it("composing two incremental rotations matches one combined rotation", () => {
    const p = { x: 0, y: 0, z: 1 };
    const half = quatFromAxisAngle({ x: 0, y: 1, z: 0 }, Math.PI / 4);
    const twiceApplied = rotateByQuaternion(rotateByQuaternion(p, half), half);
    const combined = quatMultiply(half, half);
    const onceApplied = rotateByQuaternion(p, combined);
    expect(twiceApplied.x).toBeCloseTo(onceApplied.x, 10);
    expect(twiceApplied.z).toBeCloseTo(onceApplied.z, 10);
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

  it("cube points near a face boundary get a nonzero edgeBoost", () => {
    const points = generateShape("cube");
    expect(points.some((p) => (p.edgeBoost ?? 0) > 0)).toBe(true);
    expect(points.some((p) => (p.edgeBoost ?? 0) === 0)).toBe(true);
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
    const identity = quatIdentity();
    const gridFarFirst = rasterizeShape([far, near], identity, 20, 20, ramp);
    const gridNearFirst = rasterizeShape([near, far], identity, 20, 20, ramp);

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
    const q = quatMultiply(
      quatFromAxisAngle({ x: 1, y: 0, z: 0 }, 0.3),
      quatFromAxisAngle({ x: 0, y: 1, z: 0 }, 0.7),
    );
    const grid = rasterizeShape(points, q, 40, 20);
    expect(grid.length).toBe(20);
    for (const row of grid) {
      expect(row.length).toBe(40);
    }
  });
});
