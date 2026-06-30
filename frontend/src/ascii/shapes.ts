// Pure, framework-agnostic math for the rotating ASCII wireframe shapes on
// the landing page. Generates a point cloud + normal per shape, rotates and
// projects it, then rasterizes onto a character grid via a z-buffer (the
// classic "spinning donut" technique generalized to torus/cube/sphere).
// Kept separate from SpinningShape.tsx so the math is unit-testable without
// mounting React.

import { charForBrightness, DEFAULT_RAMP } from "./fallback";

// DEFAULT_RAMP's darkest character is a literal space -- correct for
// AsciiCanvas's noise layer (an unlit cell SHOULD be invisible there), but
// wrong for a solid object: any actual surface point that wins a z-buffer
// cell should always render as a visible glyph, never blank, so every face
// of the shape stays legible regardless of its lighting angle ("each face
// should be visible, ' ' shouldn't be a valid character" for the object).
// Slicing off the leading space means the darkest a real point can render
// is the next-darkest glyph, never nothing.
const SHAPE_RAMP = DEFAULT_RAMP.slice(1);

// Faces angled away from the light still need to read as part of the solid,
// not vanish into near-zero brightness -- a small ambient floor (on top of
// SHAPE_RAMP already excluding space) keeps every face visibly part of the
// object rather than just technically non-space-but-imperceptible.
const AMBIENT_FLOOR = 0.16;

// normal-dot-light ranges over [-1, 1] (1 = facing the light directly, -1 =
// facing directly away). A first pass clamped negative dot products to a
// single flat AMBIENT_FLOOR value with Math.max(), which crushed the
// entire away-facing hemisphere of the object to one identical brightness
// -- visually flat there, with all the gradient detail squeezed into just
// the half of the surface facing toward the light ("not that great...
// actually see the gradients"). Remapping the full [-1, 1] range linearly
// onto [AMBIENT_FLOOR, 1] gave every point its own brightness, but most of
// the camera-FACING surface still landed in the dark/purple half of the
// gradient ("not bright enough... everything seems to be purple") -- a
// BRIGHTEN_GAMMA < 1 pulls midtones up (the same gamma trick used for
// perceptual brightness in fallback.ts, applied here to push the visible
// range toward the bright/yellow end rather than sitting mid-dark/purple).
const BRIGHTEN_GAMMA = 0.6;

function shadeFromDot(dot: number): number {
  const normalized = (dot + 1) / 2; // [-1, 1] -> [0, 1]
  const brightened = Math.pow(normalized, BRIGHTEN_GAMMA);
  return AMBIENT_FLOOR + (1 - AMBIENT_FLOOR) * brightened;
}

export type ShapeKind = "donut" | "cube" | "sphere";

export interface Point3 {
  x: number;
  y: number;
  z: number;
}

export interface SurfacePoint {
  position: Point3;
  normal: Point3;
  // Extra brightness added on top of the lighting calculation -- used by
  // generateCube to give points near a face boundary a slight rim-light
  // boost, so edges/corners read as crisp lines instead of blending into
  // the flat-shaded face on either side ("better edge rendering on the
  // cube"). 0 for shapes that don't use it (donut, sphere).
  edgeBoost?: number;
}

const SHAPE_KINDS: ShapeKind[] = ["donut", "cube", "sphere"];

export function randomShapeKind(): ShapeKind {
  return SHAPE_KINDS[Math.floor(Math.random() * SHAPE_KINDS.length)];
}

function normalize(v: Point3): Point3 {
  const len = Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z) || 1;
  return { x: v.x / len, y: v.y / len, z: v.z / len };
}

// --- Quaternion rotation -----------------------------------------------
//
// Orientation is tracked as a single accumulated quaternion, not a pair of
// Euler angles (angleX, angleY) applied in sequence each frame. Sequential
// Euler angles are exactly what made the drag controls feel like they
// "rotate the wrong way" depending on the shape's current orientation --
// each frame's rotation was applied around the fixed WORLD X/Y axes, so
// once the shape had already turned partway, a horizontal drag no longer
// corresponded to the visually-horizontal axis on screen (a version of
// gimbal lock). Quaternions accumulated via left-multiplication by a
// world-space incremental rotation (see SpinningShape.tsx) keep "drag
// right" meaning the same visual thing regardless of accumulated spin.

export interface Quaternion {
  w: number;
  x: number;
  y: number;
  z: number;
}

export function quatIdentity(): Quaternion {
  return { w: 1, x: 0, y: 0, z: 0 };
}

export function quatFromAxisAngle(axis: Point3, angle: number): Quaternion {
  const a = normalize(axis);
  const half = angle / 2;
  const s = Math.sin(half);
  return { w: Math.cos(half), x: a.x * s, y: a.y * s, z: a.z * s };
}

/** Hamilton product a*b -- applying the result to a vector rotates by b first, then a. */
export function quatMultiply(a: Quaternion, b: Quaternion): Quaternion {
  return {
    w: a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
    x: a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
    y: a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
    z: a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
  };
}

export function quatNormalize(q: Quaternion): Quaternion {
  const len = Math.sqrt(q.w * q.w + q.x * q.x + q.y * q.y + q.z * q.z) || 1;
  return { w: q.w / len, x: q.x / len, y: q.y / len, z: q.z / len };
}

/** Rotates vector `p` by quaternion `q` (q must be unit-length). */
export function rotateByQuaternion(p: Point3, q: Quaternion): Point3 {
  const { w, x, y, z } = q;
  // t = 2 * cross(q.xyz, p)
  const tx = 2 * (y * p.z - z * p.y);
  const ty = 2 * (z * p.x - x * p.z);
  const tz = 2 * (x * p.y - y * p.x);
  // p' = p + w*t + cross(q.xyz, t)
  return {
    x: p.x + w * tx + (y * tz - z * ty),
    y: p.y + w * ty + (z * tx - x * tz),
    z: p.z + w * tz + (x * ty - y * tx),
  };
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

// Fraction of each face's [-1, 1] u/v range, measured from the boundary,
// that gets a rim-light edge boost -- and how strong that boost is. Wider/
// stronger than a hairline so the edge reads clearly at the font sizes
// this renders at, without visibly eating into the face.
const CUBE_EDGE_MARGIN = 0.06;
const CUBE_EDGE_BOOST = 0.35;

function generateCube(halfSide = 1.3): SurfacePoint[] {
  const points: SurfacePoint[] = [];
  // Denser than the donut's effective sampling was leaving the cube's
  // edges comparatively soft/under-defined ("better edge rendering on the
  // cube... donut looks the best currently") -- bumped from 40 to 64.
  const stepsPerEdge = 64;
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
        // Distance from the nearest face boundary in u/v space; points
        // within CUBE_EDGE_MARGIN of an edge (including corners, where
        // both a and b are near +-1) get a brightness boost proportional
        // to how close they are to that boundary.
        const distFromEdge = Math.min(1 - Math.abs(a), 1 - Math.abs(b));
        const edgeBoost =
          distFromEdge < CUBE_EDGE_MARGIN
            ? CUBE_EDGE_BOOST * (1 - distFromEdge / CUBE_EDGE_MARGIN)
            : 0;
        points.push({ position, normal: face.normal, edgeBoost });
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

// --- Rasterization -------------------------------------------------------

export interface ShapeCell {
  char: string;
  brightness: number;
}

// z dominant (camera points toward +z, so a more-negative z is more
// "toward the camera" / front-facing -- see rasterizeShape's projection
// below) and only a small x/y offset for shape definition. The earlier
// (-0.5, -0.5, -1) mix put 45 degrees of lateral skew on the light,
// shifting the brightest point off toward a corner and leaving most of the
// camera-facing surface dim ("not bright enough... everything seems
// purple, move the light to be more on the front side").
const LIGHT_DIR = normalize({ x: -0.2, y: -0.15, z: -1.6 });

/**
 * Rotates every point in `points` by the quaternion `orientation`, projects
 * with a simple perspective division, and rasterizes onto a `cols` x `rows`
 * character grid using a z-buffer so nearer points win overlapping cells.
 *
 * Lighting uses the point's LOCAL (unrotated) normal, not the rotated one
 * -- per feedback, the light should stay on the same side OF THE OBJECT as
 * it spins (i.e. the light rotates along with the object, so a given
 * physical face is always lit/shadowed the same way), rather than being
 * fixed in camera/world space (which would make a fixed face flicker
 * between lit and shadowed as it rotates in and out of facing a
 * screen-fixed light). Only position is rotated for projection/visibility.
 */
export function rasterizeShape(
  points: SurfacePoint[],
  orientation: Quaternion,
  cols: number,
  rows: number,
  ramp: string = SHAPE_RAMP,
): ShapeCell[][] {
  const zBuffer = new Float64Array(cols * rows).fill(-Infinity);
  const charGrid: string[] = new Array(cols * rows).fill(" ");
  const brightnessGrid = new Float64Array(cols * rows);

  // Camera/projection constants tuned so the shape comfortably fills a
  // terminal-ish aspect ratio; cells are roughly 2x taller than wide in a
  // monospace font, so X is scaled up relative to Y to compensate.
  const cameraDistance = 5;
  const scale = Math.min(cols, rows * 2) * 0.38;

  for (const { position, normal, edgeBoost } of points) {
    const rotated = rotateByQuaternion(position, orientation);

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
    // Local (unrotated) normal, not rotatedNormal -- see the function
    // doc comment above: the light is meant to stay fixed relative to the
    // OBJECT, not the camera. shadeFromDot remaps the full [-1, 1] dot
    // product range so the gradient is visible across the whole surface,
    // not just clamped flat on the away-facing half.
    const dot = normal.x * LIGHT_DIR.x + normal.y * LIGHT_DIR.y + normal.z * LIGHT_DIR.z;
    const luminance = Math.min(1, shadeFromDot(dot) + (edgeBoost ?? 0));
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
