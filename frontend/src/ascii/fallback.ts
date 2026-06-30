// Pure-TS luminance-to-ASCII mapping. This is the safety-net render path
// when WebAssembly is unavailable (see docs/design/08-ascii-wasm-renderer.md)
// -- it must produce the same visual language as wasm-ascii's rasterize(),
// just at lower resolution/frame rate, so the two are kept numerically
// in sync (same luminance formula, same default ramp).

export const DEFAULT_RAMP = " .:-=+*#%@";

export interface AsciiCell {
  char: string;
  brightness: number; // 0..1
}

function luminance(r: number, g: number, b: number): number {
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255;
}

function charForBrightness(brightness: number, ramp: string): string {
  const index = Math.min(
    ramp.length - 1,
    Math.max(0, Math.floor(brightness * (ramp.length - 1))),
  );
  return ramp[index];
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
