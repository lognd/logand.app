# 08 -- ASCII WASM Renderer

Audience: anyone building the Rust/WASM ASCII rasterizer or its JS
fallback. Read [00-overview.md](00-overview.md) first. Visual intent
(what it should look like) is owned by
[09-design-system.md](09-design-system.md) -- this doc is implementation
only.

## Purpose

Root README asks for an Ubuntu-shell-inspired, ASCII-heavy aesthetic,
with ASCII rasterization "done through web-assembly... if web-assembly
is supported, otherwise have a backup that's less intensive."

## Scope of the Rust crate

`wasm-ascii/` converts visual input (images, gradients, or generated
patterns used for backgrounds/headers) into ASCII-art character grids
at runtime, in-browser. It is not a terminal emulator and does not need
to render arbitrary HTML as ASCII -- scope is: take a bitmap (canvas
pixel buffer or generated noise/gradient field) and a target
character-cell grid size, return a 2D array of `(char, brightness)` for
the frontend to paint.

```
wasm-ascii/
  src/
    lib.rs              # wasm-bindgen entry points
    rasterize.rs          # core pixel -> ASCII-character mapping
    ramp.rs                # brightness-to-character ramp tables
  Cargo.toml
  Makefile
```

## Public WASM API (wasm-bindgen)

```rust
#[wasm_bindgen]
pub fn rasterize(
    pixels: &[u8],     // RGBA buffer
    width: u32,
    height: u32,
    cols: u32,
    rows: u32,
    ramp: &str,         // character ramp, darkest -> brightest
) -> Vec<u8>;            // packed (char_code, brightness) pairs, decoded in TS
```

Keep the surface minimal -- one pure function, no internal state, no
async. State (animation timing, which ramp is active) lives in
TypeScript; Rust only does the per-frame numeric work that's worth
offloading from JS.

## Crate choice

Use the `image` crate for any decoding needs and hand-rolled luminance
mapping (`0.299R + 0.587G + 0.114B`) into a configurable character ramp
-- this is simple enough that pulling in a full ASCII-art crate (most
target CLI/terminal output, not WASM buffers) adds more friction than it
saves. Revisit only if a WASM-targeted ASCII crate with an actively
maintained `wasm-bindgen` story turns up.

## JS fallback (`frontend/src/ascii/fallback.ts`)

If `WebAssembly` is undefined, or the WASM module fails to instantiate
(`try`/`catch` around `init()`), fall back to a pure-TS implementation
of the same luminance-to-character mapping, run at a lower
resolution/frame rate (fewer columns/rows, animation throttled) since
it's doing the same math without WASM's speed. The fallback must produce
the *same visual language* (same character ramp, same general look),
just less detailed/animated -- not a visually different degraded
experience.

`AsciiCanvas.tsx` (see [07](07-frontend-architecture.md)) is the only
component that decides which path to use; everything downstream
consumes the same `(char, brightness)[][]` shape regardless of source.

## Build & tooling

```
wasm-ascii/Makefile
  build:      wasm-pack build --target web --out-dir ../frontend/src/ascii/pkg
  check:      cargo check && cargo clippy -- -D warnings && cargo fmt --check && cargo test
  test:       cargo test
  clean:      rm -rf target pkg
```

`frontend/Makefile`'s `build` target depends on `wasm-ascii`'s `build`
target running first (root Makefile sequences this).

## Testing

Pixel-to-character mapping correctness (known input -> known ramp
output) is a Rust unit-test concern; the JS-fallback-matches-WASM-output
property is a frontend integration-test concern -- see
[12-testing-strategy.md](12-testing-strategy.md).
