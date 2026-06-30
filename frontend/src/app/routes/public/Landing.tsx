import { SpinningShape } from "../../../ascii/SpinningShape";
import { LINK_CLASS } from "../../../styles/a11y";

// Public routes must render real semantic content -- crawlers and the
// vite-ssg prerender pass (see docs/design/10) read this markup directly,
// not a post-hydration DOM. Keep real text here even at stub stage.
//
// SpinningShape composes on top of Shell's faint AsciiCanvas noise layer
// rather than replacing it: Shell's layer stays as the site-wide quiet
// atmosphere (docs/design/09), while this page gets a second, more
// prominent decorative layer befitting the landing page specifically
// ("public-facing pages get a more prominent animated ASCII background"
// per docs/design/09). It sits between the noise layer (-z-10) and the
// real content (default stacking), and is itself non-interactive for
// assistive tech (aria-hidden) since it's pure decoration -- the actual
// navigation lives in the real <nav> below, never inside the shape.
export function Landing() {
  return (
    // `isolate` for the same reason as Shell.tsx's root div -- without its
    // own stacking context, this <main> being transparent doesn't matter,
    // but ANY ancestor up the tree painting a background after this point
    // in z-order would hide SpinningShape; isolating here makes this
    // component's stacking self-contained regardless of what wraps it.
    //
    // `min-h-screen` -- without an explicit height, <main> only sizes to
    // its content (a few hundred px of heading/text), so SpinningShape's
    // `absolute inset-0` was clipped well before filling the viewport
    // ("the animation in the background is cut off"). SpinningShape now
    // computes its own font-size to fit whatever box it's given (see
    // useFitFontSize), so the only fix needed here is giving it a full
    // viewport-height box to fit *into*.
    <main className="relative isolate min-h-screen">
      <SpinningShape className="pointer-events-auto absolute inset-0 -z-[5] flex items-center justify-center overflow-hidden opacity-50" />
      <div className="relative mx-auto w-full max-w-2xl px-4 py-12">
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
    </main>
  );
}
