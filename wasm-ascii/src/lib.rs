mod ramp;
mod rasterize;

use wasm_bindgen::prelude::*;

/// Rasterizes an RGBA pixel buffer into a `cols` x `rows` ASCII grid.
///
/// Returns a packed `Vec<u8>`: for each cell, two bytes
/// `(char_code as u8, brightness_0_255)`, row-major. The frontend decodes
/// this pair-wise -- see docs/design/08-ascii-wasm-renderer.md. char_code
/// is truncated to u8 because the default ramp (and any custom ramp passed
/// in) is expected to be ASCII-only, per the project's "no non-ASCII
/// characters" rule.
#[wasm_bindgen]
pub fn rasterize(
    pixels: &[u8],
    width: u32,
    height: u32,
    cols: u32,
    rows: u32,
    ramp: &str,
) -> Vec<u8> {
    let grid = rasterize::rasterize_grid(pixels, width, height, cols, rows, ramp);
    let mut out = Vec::with_capacity(grid.len() * 2);
    for (ch, brightness) in grid {
        out.push(ch as u8);
        out.push((brightness.clamp(0.0, 1.0) * 255.0) as u8);
    }
    out
}
