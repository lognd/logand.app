// Integration layer for this crate is the WASM boundary itself -- run via
// `wasm-pack test --headless --chrome` (see docs/design/08 and 12).
use wasm_bindgen_test::*;
use wasm_ascii::rasterize;

wasm_bindgen_test_configure!(run_in_browser);

#[wasm_bindgen_test]
fn rasterize_returns_packed_pairs_for_each_cell() {
    let pixels = [0u8, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255];
    let out = rasterize(&pixels, 2, 2, 1, 1, " .:-=+*#%@");
    assert_eq!(out.len(), 2); // one cell -> (char_code, brightness)
    assert_eq!(out[0], b' ');
}
