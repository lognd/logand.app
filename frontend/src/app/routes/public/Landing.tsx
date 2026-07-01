import { useState } from "react";
import { BackgroundPicker, type BackgroundOption } from "../../../ascii/BackgroundPicker";
import { MatrixRain } from "../../../ascii/MatrixRain";
import { ParticleLayer } from "../../../ascii/ParticleLayer";
import { SpinningShape } from "../../../ascii/SpinningShape";
import { randomShapeKind } from "../../../ascii/shapes";
import { LINK_CLASS } from "../../../styles/a11y";

// Public routes must render real semantic content -- crawlers and the
// vite-ssg prerender pass (see docs/design/10) read this markup directly,
// not a post-hydration DOM. Keep real text here even at stub stage.
//
// The background is one of four mutually-exclusive options (donut/cube/
// globe/rain) picked via BackgroundPicker, composing on top of Shell's
// faint site-wide AsciiCanvas noise layer (docs/design/09's "public pages
// get a more prominent animated background" -- this is that more
// prominent layer; Shell's noise stays as the calm site-wide atmosphere
// underneath it). It sits between the noise layer (-z-10) and the real
// content (z-10 by default), and is itself non-interactive for assistive
// tech (aria-hidden) since it's pure decoration -- the actual navigation
// lives in the real <nav> below, never inside the shape/rain.
//
// ParticleLayer (the click/drag trail + explosion interaction) is mounted
// unconditionally, on top of whichever background is selected -- it used
// to live inside MatrixRain only, but per feedback ("I don't see the
// trail and explosion on the donut and cube and globe") it now works
// regardless of which background is showing.
export function Landing() {
  const [background, setBackground] = useState<BackgroundOption>(() => randomShapeKind());

  return (
    // `isolate` for the same reason as Shell.tsx's root div -- without its
    // own stacking context, this <main> being transparent doesn't matter,
    // but ANY ancestor up the tree painting a background after this point
    // in z-order would hide the selected background layer; isolating here
    // makes this component's stacking self-contained regardless of what
    // wraps it.
    //
    // `h-full` (not `min-h-screen`): Shell's root is a flex column with
    // this <main>'s wrapper set to flex-1, so "fill 100% of the remaining
    // height after the header" is already exactly what h-full resolves to
    // here. min-h-screen would ADD a full 100vh on top of that flex-1 box
    // (header height + 100vh > 100vh), which is what caused the page to be
    // taller than the viewport and produce a permanent vertical scrollbar.
    //
    // No min-h-[480px] floor (removed) -- it forced this <main> taller
    // than the viewport whenever the actual available height dropped
    // below 480px (mobile landscape, a short/zoomed-out desktop window),
    // which is exactly a vertical overflow/scrollbar with nothing real to
    // scroll to ("the overflow is busted on mobile"). h-full already
    // sizes this correctly down to whatever height is actually available.
    <main className="relative isolate flex h-full flex-col">
      {background === "rain" ? (
        // No opacity wrapper here -- MatrixRain paints its own solid,
        // stationary backdrop (see MatrixRain.tsx's BACKDROP_COLOR) rather
        // than compositing over whatever's behind it, so it isn't faded
        // the way the shapes are.
        <MatrixRain className="absolute inset-0 -z-[5]" />
      ) : (
        // opacity-30, down from an earlier 50% -- feedback was that the
        // combined background (this shape + Shell's ambient noise layer
        // underneath) read as distracting at full strength; the shape is
        // still clearly visible and draggable, just quieter as atmosphere
        // rather than competing with the real heading/nav text.
        <SpinningShape
          kind={background}
          className="pointer-events-auto absolute inset-0 -z-[5] flex items-center justify-center overflow-hidden opacity-30"
        />
      )}
      {/* Muted (desaturated) over the spinning shape so the click/drag
          particle layer doesn't compete with the shape's own shading;
          full heat-curve color is kept on the Matrix-rain background,
          where it's the point. */}
      <ParticleLayer
        className="pointer-events-none absolute inset-0 -z-[4]"
        muted={background !== "rain"}
      />
      {/* flex-1 + items-center/justify-center centers the heading block
          vertically within the available space (between header and
          footer) instead of pinning it to the top. */}
      <div className="relative z-10 flex flex-1 items-center justify-center px-4 py-12">
        <div className="w-full max-w-2xl">
          <h1 className="mb-4 text-3xl text-fg-primary">Logan Dapp</h1>
          <p className="mb-6 text-base text-fg-primary">
            Personal and professional site of Logan Dapp -- software engineer, builder of
            logand.app.
          </p>
          <nav aria-label="primary" className="flex flex-wrap gap-4">
            <a href="/projects" className={LINK_CLASS}>
              Projects
            </a>
            <a href="/contact" className={LINK_CLASS}>
              Contact
            </a>
          </nav>
        </div>
      </div>
      {/* fixed + bottom-0, not mt-auto -- locked to the actual viewport
          bottom edge regardless of content height (an mt-auto footer
          inside the flex column could end up short of the true bottom on
          a tall viewport, reading as an "abrupt cutoff"). bg-transparent
          is explicit (not just the absence of a class) so it never
          accidentally inherits an opaque background and blocks the
          rain/shape layer from showing through behind it. */}
      <footer className="fixed inset-x-0 bottom-0 z-10 border-t border-border bg-transparent px-4 py-4">
        <BackgroundPicker value={background} onChange={setBackground} />
      </footer>
    </main>
  );
}
