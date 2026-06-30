import { describe, expect, it } from "vitest";
import { rasterizeFallback } from "../../src/ascii/fallback";

describe("rasterizeFallback", () => {
  it("maps an all-black pixel block to the darkest ramp character", () => {
    const ramp = " .:-=+*#%@";
    const pixels = new Uint8ClampedArray(4 * 4);
    for (let i = 0; i < pixels.length; i += 4) {
      pixels[i] = 0;
      pixels[i + 1] = 0;
      pixels[i + 2] = 0;
      pixels[i + 3] = 255;
    }
    const grid = rasterizeFallback(pixels, 2, 2, 1, 1, ramp);
    expect(grid[0][0].char).toBe(ramp[0]);
  });

  it("maps an all-white pixel block to the brightest ramp character", () => {
    const ramp = " .:-=+*#%@";
    const pixels = new Uint8ClampedArray(4 * 4);
    for (let i = 0; i < pixels.length; i += 4) {
      pixels[i] = 255;
      pixels[i + 1] = 255;
      pixels[i + 2] = 255;
      pixels[i + 3] = 255;
    }
    const grid = rasterizeFallback(pixels, 2, 2, 1, 1, ramp);
    expect(grid[0][0].char).toBe(ramp[ramp.length - 1]);
  });
});
