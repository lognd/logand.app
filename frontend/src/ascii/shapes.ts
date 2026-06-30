// Pure, framework-agnostic math for the rotating ASCII wireframe shapes on
// the landing page. Generates a point cloud + normal per shape, rotates and
// projects it, then rasterizes onto a character grid via a z-buffer (the
// classic "spinning donut" technique generalized to torus/cube/sphere).
// Kept separate from SpinningShape.tsx so the math is unit-testable without
// mounting React.

import { charForBrightness, DEFAULT_RAMP } from "./fallback";

export type ShapeKind = "donut" | "cube" | "sphere";

export interface Point3 {
  x: number;
  y: number;
  z: number;
}

export interface SurfacePoint {
  position: Point3;
  normal: Point3;
}

const SHAPE_KINDS: ShapeKind[] = ["donut", "cube", "sphere"];

export function randomShapeKind(): ShapeKind {
  return SHAPE_KINDS[Math.floor(Math.random() * SHAPE_KINDS.length)];
}

function normalize(v: Point3): Point3 {
  const len = Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z) || 1;
  return { x: v.x / len, y: v.y / len, z: v.z / len };
}

// --- Point cloud generators -------------------------------------------------
//
// Each generator samples a parametric surface densely enough that, after
// projection, adjacent samples land on neighboring (or the same) character
// cells -- this is what makes the wireframe read as a filled, shaded surface
// rather than sparse dots, matching the classic ASCII-donut look.

function generateDonut(majorRadius = 1.5, minorRadius = 0.7): SurfacePoint[] {
  const points: SurfacePoint[] = [];
  const thetaSteps = 80; // around the tube
  const phiSteps = 200; // around the donut hole
  for (let i = 0; i < thetaSteps; i++) {
    const theta = (i / thetaSteps) * 2 * Math.PI;
    const cosTheta = Math.cos(theta);
    const sinTheta = Math.sin(theta);
    for (let j = 0; j < phiSteps; j++) {
      const phi = (j / phiSteps) * 2 * Math.PI;
      const cosPhi = Math.cos(phi);
      const sinPhi = Math.sin(phi);

      const circleX = majorRadius + minorRadius * cosTheta;
      const position: Point3 = {
        x: circleX * cosPhi,
        y: minorRadius * sinTheta,
        z: circleX * sinPhi,
      };
      const normal = normalize({
        x: cosTheta * cosPhi,
        y: sinTheta,
        z: cosTheta * sinPhi,
      });
      points.push({ position, normal });
    }
  }
  return points;
}

// A densely-sampled filled sphere shades as a smooth, featureless blob under
// simple diffuse lighting -- a sphere's normal varies continuously in every
// direction, so there's no edge, hole, or corner for the eye to lock onto
// the way there is with the donut's hole or the cube's corners ("the sphere
// doesn't make sense" -- it just reads as a fuzzy circle, not recognizably
// a sphere). Rendering it as an explicit latitude/longitude wireframe (like
// a globe) gives it real structure instead: only points near `RING_COUNT`
// latitude circles and `RING_COUNT * 1.5` longitude circles are emitted, so
// the rasterizer's z-buffer naturally produces visible ring lines.
function generateSphere(radius = 1.6): SurfacePoint[] {
  const points: SurfacePoint[] = [];
  const latRings = 9;
  const lonRings = 14;
  const pointsPerRing = 220;

  for (let i = 1; i < latRings; i++) {
    const lat = (i / latRings) * Math.PI;
    const sinLat = Math.sin(lat);
    const cosLat = Math.cos(lat);
    for (let j = 0; j < pointsPerRing; j++) {
      const lon = (j / pointsPerRing) * 2 * Math.PI;
      const normal: Point3 = {
        x: sinLat * Math.cos(lon),
        y: cosLat,
        z: sinLat * Math.sin(lon),
      };
      points.push({
        position: { x: normal.x * radius, y: normal.y * radius, z: normal.z * radius },
        normal,
      });
    }
  }

  for (let i = 0; i < lonRings; i++) {
    const lon = (i / lonRings) * 2 * Math.PI;
    const cosLon = Math.cos(lon);
    const sinLon = Math.sin(lon);
    for (let j = 0; j < pointsPerRing; j++) {
      const lat = (j / pointsPerRing) * Math.PI;
      const sinLat = Math.sin(lat);
      const cosLat = Math.cos(lat);
      const normal: Point3 = {
        x: sinLat * cosLon,
        y: cosLat,
        z: sinLat * sinLon,
      };
      points.push({
        position: { x: normal.x * radius, y: normal.y * radius, z: normal.z * radius },
        normal,
      });
    }
  }

  return points;
}

function generateCube(halfSide = 1.3): SurfacePoint[] {
  const points: SurfacePoint[] = [];
  const stepsPerEdge = 40;
  const faces: { normal: Point3; u: Point3; v: Point3 }[] = [
    { normal: { x: 1, y: 0, z: 0 }, u: { x: 0, y: 1, z: 0 }, v: { x: 0, y: 0, z: 1 } },
    { normal: { x: -1, y: 0, z: 0 }, u: { x: 0, y: 1, z: 0 }, v: { x: 0, y: 0, z: 1 } },
    { normal: { x: 0, y: 1, z: 0 }, u: { x: 1, y: 0, z: 0 }, v: { x: 0, y: 0, z: 1 } },
    { normal: { x: 0, y: -1, z: 0 }, u: { x: 1, y: 0, z: 0 }, v: { x: 0, y: 0, z: 1 } },
    { normal: { x: 0, y: 0, z: 1 }, u: { x: 1, y: 0, z: 0 }, v: { x: 0, y: 1, z: 0 } },
    { normal: { x: 0, y: 0, z: -1 }, u: { x: 1, y: 0, z: 0 }, v: { x: 0, y: 1, z: 0 } },
  ];

  for (const face of faces) {
    for (let i = 0; i <= stepsPerEdge; i++) {
      const a = (i / stepsPerEdge) * 2 - 1; // -1..1
      for (let j = 0; j <= stepsPerEdge; j++) {
        const b = (j / stepsPerEdge) * 2 - 1;
        const position: Point3 = {
          x:
            face.normal.x * halfSide +
            face.u.x * a * halfSide +
            face.v.x * b * halfSide,
          y:
            face.normal.y * halfSide +
            face.u.y * a * halfSide +
            face.v.y * b * halfSide,
          z:
            face.normal.z * halfSide +
            face.u.z * a * halfSide +
            face.v.z * b * halfSide,
        };
        points.push({ position, normal: face.normal });
      }
    }
  }
  return points;
}

export function generateShape(kind: ShapeKind): SurfacePoint[] {
  switch (kind) {
    case "donut":
      return generateDonut();
    case "sphere":
      return generateSphere();
    case "cube":
      return generateCube();
  }
}

// --- Rotation ----------------------------------------------------------------

/** Rotates `p` by `angleX` around the X axis then `angleY` around the Y axis. */
export function rotatePoint(p: Point3, angleX: number, angleY: number): Point3 {
  const cosX = Math.cos(angleX);
  const sinX = Math.sin(angleX);
  const y1 = p.y * cosX - p.z * sinX;
  const z1 = p.y * sinX + p.z * cosX;

  const cosY = Math.cos(angleY);
  const sinY = Math.sin(angleY);
  const x2 = p.x * cosY + z1 * sinY;
  const z2 = -p.x * sinY + z1 * cosY;

  return { x: x2, y: y1, z: z2 };
}

// --- Rasterization -------------------------------------------------------

export interface ShapeCell {
  char: string;
  brightness: number;
}

const LIGHT_DIR = normalize({ x: -0.5, y: -0.5, z: -1 });

/**
 * Rotates every point in `points` by (angleX, angleY), projects with a
 * simple perspective division, and rasterizes onto a `cols` x `rows`
 * character grid using a z-buffer so nearer points win overlapping cells.
 * Per-cell brightness comes from the rotated normal's alignment with a
 * fixed light direction, which is what gives the shape its shading.
 */
export function rasterizeShape(
  points: SurfacePoint[],
  angleX: number,
  angleY: number,
  cols: number,
  rows: number,
  ramp: string = DEFAULT_RAMP,
): ShapeCell[][] {
  const zBuffer = new Float64Array(cols * rows).fill(-Infinity);
  const charGrid: string[] = new Array(cols * rows).fill(" ");
  const brightnessGrid = new Float64Array(cols * rows);

  // Camera/projection constants tuned so the shape comfortably fills a
  // terminal-ish aspect ratio; cells are roughly 2x taller than wide in a
  // monospace font, so X is scaled up relative to Y to compensate.
  const cameraDistance = 5;
  const scale = Math.min(cols, rows * 2) * 0.38;

  for (const { position, normal } of points) {
    const rotated = rotatePoint(position, angleX, angleY);
    const rotatedNormal = rotatePoint(normal, angleX, angleY);

    const z = rotated.z + cameraDistance;
    if (z <= 0.1) continue; // behind the camera

    const invZ = 1 / z;
    const projX = rotated.x * invZ;
    const projY = rotated.y * invZ;

    const col = Math.round(cols / 2 + projX * scale * 2);
    const row = Math.round(rows / 2 - projY * scale);
    if (col < 0 || col >= cols || row < 0 || row >= rows) continue;

    const idx = row * cols + col;
    if (invZ <= zBuffer[idx]) continue; // a nearer point already owns this cell

    zBuffer[idx] = invZ;
    const luminance = Math.max(
      0,
      rotatedNormal.x * LIGHT_DIR.x +
        rotatedNormal.y * LIGHT_DIR.y +
        rotatedNormal.z * LIGHT_DIR.z,
    );
    brightnessGrid[idx] = luminance;
    charGrid[idx] = charForBrightness(luminance, ramp);
  }

  const grid: ShapeCell[][] = [];
  for (let row = 0; row < rows; row++) {
    const cells: ShapeCell[] = [];
    for (let col = 0; col < cols; col++) {
      const idx = row * cols + col;
      cells.push({ char: charGrid[idx], brightness: brightnessGrid[idx] });
    }
    grid.push(cells);
  }
  return grid;
}
