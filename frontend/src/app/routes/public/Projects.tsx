import { useEffect, useRef, useState } from "react";
import { MatrixRain } from "../../../ascii/MatrixRain";
import { ParticleLayer } from "../../../ascii/ParticleLayer";
import { useBrightnessWave } from "../../layout/useBrightnessWave";
import { ImageCarousel, type CarouselSlide } from "./ImageCarousel";

interface Project {
  title: string;
  description: string;
  slides: CarouselSlide[];
}

// TODO(logan): replace with real project list (CreativeWork/SoftwareSourceCode
// JSON-LD per docs/design/10) once content is provided -- these entries and
// their carousel slides are placeholders (see ImageCarousel.tsx's
// CarouselSlide doc comment: a slide without a real `src` renders a
// labeled placeholder panel instead of a broken <img>), just enough to
// demonstrate the actual feed/carousel/scroll behavior end to end.
const PROJECTS: Project[] = [
  {
    title: "logand.app",
    description:
      "This site -- a FastAPI + Postgres backend, a React/TypeScript frontend, and a Rust/WASM ASCII renderer, all in one monorepo. Session-cookie auth, Stripe-backed invoicing, and the animated ASCII backgrounds you're looking at right now were all built and iterated on live with a lot of back-and-forth on the exact look and feel. Deployed as a single-VPS Docker Compose stack behind Caddy.",
    slides: [
      // "/?bg=donut" -- root-relative, not a hardcoded "https://logand.app"
      // or "http://localhost:..." -- so this embeds whatever domain/origin
      // the app itself is actually being served from (dev, staging,
      // production) rather than only ever working in one of them.
      // "?bg=donut" pins the embedded landing page to a specific
      // background (see Landing.tsx's backgroundFromSearchParams) --
      // a regular site visit randomizes among all four, but this preview
      // should reliably show the same good-looking background every time
      // rather than whatever a fresh random pick happens to land on.
      { alt: "logand.app (embedded live)", iframeSrc: "/?bg=donut" },
      { alt: "Screenshot placeholder -- admin invoice dashboard" },
      { alt: "Screenshot placeholder -- spinning ASCII globe" },
    ],
  },
  {
    title: "Project two",
    description:
      "Placeholder description for a second project -- replace with real project copy once it's available. Long enough text to demonstrate the description area's own internal scroll independent of the page-level card feed.",
    slides: [{ alt: "Screenshot placeholder -- project two" }],
  },
  {
    title: "Project three",
    description: "Placeholder description for a third project.",
    slides: [
      { alt: "Screenshot placeholder -- project three, view A" },
      { alt: "Screenshot placeholder -- project three, view B" },
    ],
  },
];

// Same MatrixRain background + ParticleLayer (mouse-drag/explosion)
// interaction as Landing's "Rain" option -- per explicit feedback ("I
// actually really like the mouse drag and explosion, can we make that
// appear on the other landing pages?") this isn't picker-selectable here
// (no donut/cube/globe alternative on this page), just always on.
//
// Layout: a vertical snap-scroll feed, one project per "page" -- "make the
// projects page infinitely scrollable until the last card of course."
// Genuinely scrollable (mouse wheel/touch drag/keyboard), just with the
// scrollbar itself hidden ("I don't want scroll bars," see tailwind.css's
// .no-scrollbar). The feed is the ONLY thing that scrolls -- <main> itself
// is sized to exactly fill the space below the header (same flex-1
// pattern as every other public route) and never overflows on its own, so
// the header stays fixed in place the whole time ("I want the header to
// stay glued to the top") without needing any position:sticky/fixed trick
// of its own -- it's simply never inside a scrolling container.
export function Projects() {
  const feedRef = useRef<HTMLDivElement | null>(null);
  useBrightnessWave(feedRef);
  // flex-1 alone doesn't reliably cap this div's height: Shell.tsx's root
  // uses min-h-dvh (a floor, not a ceiling -- see that file's comment,
  // load-bearing for admin/customer table pages that rely on natural
  // page-level scroll), so once real content is taller than the viewport
  // (true here for the first time, with 3 stacked full-page project
  // sections), nothing in the ancestor chain stops <main> from just
  // growing to fit it -- the whole document scrolls instead of only this
  // feed, breaking "I want the header to stay glued to the top."
  // Measuring this div's own actual available height in JS and applying
  // it as an explicit pixel height sidesteps that ambiguous CSS chain
  // entirely, without touching Shell.tsx's sizing model at all.
  const [feedHeight, setFeedHeight] = useState<number | null>(null);
  useEffect(() => {
    function measure() {
      const el = feedRef.current;
      if (!el) return;
      const top = el.getBoundingClientRect().top;
      setFeedHeight(window.innerHeight - top);
    }
    measure();
    window.addEventListener("resize", measure);
    window.visualViewport?.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("resize", measure);
      window.visualViewport?.removeEventListener("resize", measure);
    };
  }, []);

  return (
    // No min-h-[480px] floor -- see Landing.tsx's identical fix; it forced
    // overflow whenever the real available height dropped below 480px.
    // flex-1 (not h-full) for the same reason as Landing.tsx's <main> --
    // see Shell.tsx's content-wrapper comment.
    <main className="relative isolate flex flex-1 flex-col">
      <MatrixRain className="absolute inset-0 -z-[5]" />
      {/* -z-[4] (behind content), not z-20 -- Landing.tsx's footer needed
          a higher z-index specifically because its footer has an opaque
          background that otherwise occluded particles painted behind it
          (see that file's comment); there's no such element here, and
          keeping this behind the actual project titles/descriptions is
          what makes it read as background decoration rather than
          something drawn over text the user is trying to read. */}
      <ParticleLayer className="pointer-events-none fixed inset-0 -z-[4]" />
      <div
        ref={feedRef}
        className="relative z-10 snap-y snap-mandatory overflow-y-auto no-scrollbar"
        style={feedHeight != null ? { height: feedHeight } : undefined}
      >
        {PROJECTS.map((project, i) => (
          <section
            key={project.title}
            className="flex h-full min-h-full shrink-0 snap-start flex-col items-center gap-4 px-4 py-12"
          >
            {/* justify-start (the flex default), NOT justify-center: when
                a section's content (title + card, for the first one) is
                taller than the section's own box, justify-center
                overflows it EQUALLY above and below to keep it visually
                centered -- the overflow above the box is exactly what's
                clipped by the outer feed's overflow-y-auto (with
                snap-mandatory refusing to scroll up past this section's
                own snap point to reveal it), which is what made the
                title read as completely invisible ("the Projects header
                is not visible"). The overflow below the box is what
                visually spilled into the NEXT section's territory
                ("the cards overlap"). Top-aligning fixes both, since any
                overflow then only ever happens on the bottom.
                No overflow-y-auto on the section itself (tried that,
                reverted) -- a nested scrollable ancestor under the
                cursor gets first refusal of any wheel/trackpad scroll
                event, and even with nothing of its own to scroll, some
                browsers still spend one whole scroll gesture "realizing"
                that before chaining to the outer feed, which is exactly
                what made it take two scrolls to advance one card
                ("make it so the first scroll actually works"). In
                practice the content already fits one screen (see the
                card's own max-h-40 description scroll for the one place
                that genuinely needs independent scrolling); trading away
                a rare-edge-case overflow guard for the outer feed's
                scroll always working on the first try is the right
                call.
                "Projects" title lives on the FIRST card's own section,
                not as a separate snap point above the feed -- a
                persistent title outside the feed turned out to
                permanently cover the top of the first card ("the
                Projects header is stuck... it blocks the top of the top
                card"), while giving it its OWN separate snap point left
                it as the only thing on screen with the card entirely
                below the fold. Rendering it INSIDE the first project's
                own section, stacked above that card in the same flex
                column, means it's part of the one thing that's already
                guaranteed to be reachable on load. */}
            {i === 0 && (
              <h1 data-wave-text className="shrink-0 text-center text-3xl text-fg-primary">
                Projects
              </h1>
            )}
            {/* One bordered card per project -- carousel, title, and
                description all inside the same box, rather than loose
                stacked elements -- "make sure the grouping of carousel
                with text makes intuitive sense." glass-panel (see
                tailwind.css) is the exact same translucent treatment as
                Shell.tsx's mobile nav dropdown -- "I would prefer that we
                use the same glass look for the card as we did for the
                menu." */}
            <div className="glass-panel w-full max-w-2xl rounded border p-4 sm:p-6">
              <ImageCarousel slides={project.slides} />
              {/* data-wave-text: see useBrightnessWave's doc comment. */}
              <h2 data-wave-text className="mb-2 mt-4 text-2xl text-fg-primary">
                {project.title}
              </h2>
              {/* The card itself is capped to the feed's own height (one
                  "page" per project), so a description longer than the
                  remaining space scrolls on its own -- "a scrollable
                  description and title" -- independent of the outer
                  snap-scroll feed. NOT overscroll-contain -- "when the
                  bottom of the text in the scrollable card is reached, the
                  background should scroll," i.e. once this inner scroll
                  runs out of room, the gesture should chain through to the
                  outer feed (advancing to the next/previous project)
                  rather than being swallowed here; that chaining is the
                  browser's default overscroll-behavior, which
                  overscroll-contain would have blocked.
                  border-y (thin, matching --border) marks the actual
                  scrollable region's boundary -- without it the text just
                  starts/stops abruptly at the card's padding with no visual
                  cue that this specific bit, and not the whole card, is
                  what scrolls. */}
              <div
                data-wave-text
                className="max-h-40 overflow-y-auto no-scrollbar border-y border-border py-2 pr-1 text-base text-fg-primary"
              >
                {project.description}
              </div>
            </div>
          </section>
        ))}
      </div>
    </main>
  );
}
