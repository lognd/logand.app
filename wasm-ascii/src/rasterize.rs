use crate::ramp::char_for_brightness;

fn luminance(r: u8, g: u8, b: u8) -> f32 {
    (0.299 * r as f32 + 0.587 * g as f32 + 0.114 * b as f32) / 255.0
}

/// Downsamples an RGBA pixel buffer into a `cols` x `rows` grid, averaging
/// luminance per cell. Mirrors frontend/src/ascii/fallback.ts's
/// rasterizeFallback exactly so WASM and JS-fallback output match.
pub fn rasterize_grid(
    pixels: &[u8],
    width: u32,
    height: u32,
    cols: u32,
    rows: u32,
    ramp: &str,
) -> Vec<(char, f32)> {
    let width = width as usize;
    let height = height as usize;
    let cols = cols.max(1) as usize;
    let rows = rows.max(1) as usize;

    let cell_w = width as f32 / cols as f32;
    let cell_h = height as f32 / rows as f32;

    let mut out = Vec::with_capacity(cols * rows);

    for row in 0..rows {
        for col in 0..cols {
            let x0 = (col as f32 * cell_w).floor() as usize;
            let y0 = (row as f32 * cell_h).floor() as usize;
            let x1 = (((col + 1) as f32 * cell_w).floor() as usize).min(width);
            let y1 = (((row + 1) as f32 * cell_h).floor() as usize).min(height);

            let mut total = 0.0f32;
            let mut count = 0u32;
            for y in y0..y1 {
                for x in x0..x1 {
                    let i = (y * width + x) * 4;
                    if i + 2 >= pixels.len() {
                        continue;
                    }
                    total += luminance(pixels[i], pixels[i + 1], pixels[i + 2]);
                    count += 1;
                }
            }
            let brightness = if count > 0 { total / count as f32 } else { 0.0 };
            out.push((char_for_brightness(brightness, ramp), brightness));
        }
    }

    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn black_pixel_maps_to_darkest_char() {
        let pixels = [0u8, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255];
        let grid = rasterize_grid(&pixels, 2, 2, 1, 1, " .:-=+*#%@");
        assert_eq!(grid[0].0, ' ');
    }

    #[test]
    fn white_pixel_maps_to_brightest_char() {
        let pixels = [
            255u8, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
        ];
        let grid = rasterize_grid(&pixels, 2, 2, 1, 1, " .:-=+*#%@");
        assert_eq!(grid[0].0, '@');
    }
}
