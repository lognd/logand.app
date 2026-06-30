// Pure-TS luminance-to-ASCII mapping. This is the safety-net render path
// when WebAssembly is unavailable (see docs/design/08-ascii-wasm-renderer.md)
// -- it must produce the same visual language as wasm-ascii's rasterize(),
// just at lower resolution/frame rate, so the two are kept numerically
// in sync (same luminance formula, same default ramp).

// Lengthened from the original 10-character ramp -- the short ramp produced
// visibly banded/blocky brightness transitions ("more gradual gradient"
// feedback). 19 characters, monotonically increasing perceived ink density.
export const DEFAULT_RAMP = " .'`,:;~-+=*#%&8@$";

export interface AsciiCell {
  char: string;
  brightness: number; // 0..1
}

function luminance(r: number, g: number, b: number): number {
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255;
}

// Gamma-correct the linear brightness before mapping to a ramp index --
// human perceived brightness isn't linear, so without this the ramp spends
// too many levels on the bright end and crushes the dark end into banding.
// 0.6 approximates the inverse of the usual ~2.2 display gamma closely
// enough for a decorative effect (not aiming for color-managed accuracy).
const GAMMA = 0.6;

export function charForBrightness(brightness: number, ramp: string): string {
  const perceptual = Math.pow(Math.max(0, Math.min(1, brightness)), GAMMA);
  const index = Math.min(
    ramp.length - 1,
    Math.max(0, Math.floor(perceptual * (ramp.length - 1))),
  );
  return ramp[index];
}

// Duotone brightness->color mapping per the user's color-theory request:
// brighter cells skew yellow-green (warm, higher lightness), darker cells
// skew purple-green (cool, lower lightness) -- implemented as an HSL lerp
// so the hue sweeps *through* pure green in the middle rather than muddying
// like a naive RGB lerp would. Hue 75 = yellow-green (Gruvbox-adjacent,
// near --accent-green #b8bb26's hue), hue 200 = blue-violet-green, picked to
// read as "purple-tinted" while staying in the green family per the brief
// ("purpler-green", not violet). Mirrors the classic warm-highlight /
// cool-shadow color-grading convention.
export function colorForBrightness(brightness: number): string {
  const b = Math.max(0, Math.min(1, brightness));
  const hue = 200 - b * 125;
  const sat = 35 + b * 30;
  const light = 26 + b * 44;
  return `hsl(${hue.toFixed(0)} ${sat.toFixed(0)}% ${light.toFixed(0)}%)`;
}

/**
 * Downsamples an RGBA pixel buffer into a `cols` x `rows` grid of ASCII
 * cells by averaging luminance over each cell's source pixel block.
 */
export function rasterizeFallback(
  pixels: Uint8ClampedArray,
  width: number,
  height: number,
  cols: number,
  rows: number,
  ramp: string = DEFAULT_RAMP,
): AsciiCell[][] {
  const cellW = width / cols;
  const cellH = height / rows;
  const grid: AsciiCell[][] = [];

  for (let row = 0; row < rows; row++) {
    const cells: AsciiCell[] = [];
    for (let col = 0; col < cols; col++) {
      const x0 = Math.floor(col * cellW);
      const y0 = Math.floor(row * cellH);
      const x1 = Math.min(width, Math.floor((col + 1) * cellW));
      const y1 = Math.min(height, Math.floor((row + 1) * cellH));

      let total = 0;
      let count = 0;
      for (let y = y0; y < y1; y++) {
        for (let x = x0; x < x1; x++) {
          const i = (y * width + x) * 4;
          total += luminance(pixels[i], pixels[i + 1], pixels[i + 2]);
          count++;
        }
      }
      const brightness = count > 0 ? total / count : 0;
      cells.push({ char: charForBrightness(brightness, ramp), brightness });
    }
    grid.push(cells);
  }

  return grid;
}
