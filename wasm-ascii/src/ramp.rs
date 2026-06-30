// Default brightness ramp, darkest -> brightest. Kept in sync by hand with
// frontend/src/ascii/fallback.ts's DEFAULT_RAMP -- if you change one, change
// both (see docs/design/08-ascii-wasm-renderer.md).
pub const DEFAULT_RAMP: &str = " .:-=+*#%@";

pub fn char_for_brightness(brightness: f32, ramp: &str) -> char {
    let ramp = if ramp.is_empty() { DEFAULT_RAMP } else { ramp };
    let chars: Vec<char> = ramp.chars().collect();
    let clamped = brightness.clamp(0.0, 1.0);
    let index = ((clamped * (chars.len() - 1) as f32).floor() as usize).min(chars.len() - 1);
    chars[index]
}
