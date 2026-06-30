import { describe, expect, it } from "vitest";
import { decodeWasmGrid } from "../../src/ascii/AsciiCanvas";

describe("decodeWasmGrid", () => {
  it("decodes a single packed (char_code, brightness) pair", () => {
    const packed = new Uint8Array([65, 255]); // 'A', full brightness
    const grid = decodeWasmGrid(packed, 1, 1);
    expect(grid).toEqual([[{ char: "A", brightness: 1 }]]);
  });

  it("decodes row-major across multiple cells", () => {
    // 2 cols x 1 row: '#' at 128, '.' at 0
    const packed = new Uint8Array([35, 128, 46, 0]);
    const grid = decodeWasmGrid(packed, 2, 1);
    expect(grid[0][0].char).toBe("#");
    expect(grid[0][0].brightness).toBeCloseTo(128 / 255);
    expect(grid[0][1].char).toBe(".");
    expect(grid[0][1].brightness).toBe(0);
  });
});
