import { useEffect, useRef, useState } from "react";

// Circular, translucent overlay buttons -- not BUTTON_CLASS (a boxy, opaque
// tap target meant for real nav/form buttons) -- sitting directly on top of
// the image itself is what makes this read as an actual carousel control
// rather than a form button that happens to be positioned over a picture
// ("the buttons are a little ugly"). Same glass-panel-style translucency as
// the rest of the site rather than a one-off, without pulling in the shared
// class (which assumes a full border box + backdrop-blur meant for a
// larger panel, not a small round hit target).
//
// Positioning itself (not baked into this constant) is responsive: on a
// narrow viewport the image box has little or no side space to sit in
// (see the outer wrapper's own doc comment), so vertically-centered edge
// buttons there just look like they're floating disconnected from
// anything -- "make the arrows look better on mobile, maybe move the
// arrows to inside the image on the bottom right and left in narrow
// viewport." Below `sm`, they sit inside the image's own bottom corners
// instead; `sm` and up switches to the side-space placement.
const ARROW_BUTTON_CLASS =
  "absolute flex h-9 w-9 items-center justify-center rounded-full border border-[rgba(235,219,178,0.25)] bg-[rgba(40,40,40,0.55)] text-lg leading-none text-fg-primary transition-colors hover:bg-[rgba(40,40,40,0.8)] hover:text-accent-aqua focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-orange";

// The real site is a desktop-width layout (header/content/footer, not a
// screenshot) -- rendering the <iframe> at the slide's own small box size
// would force it into a narrow, near-mobile viewport, wrapping/squishing
// the real desktop layout instead of showing what the page actually looks
// like ("the iframe is now ridiculous"). Rendering it at a fixed desktop
// width, then scaling the whole thing down with a CSS transform to fit
// the same aspect-video box every other slide uses, gives a proper
// miniature of the real layout instead of a squished mobile render --
// same slide size as a photo ("keep it the same size as regular
// photos"), sensible content inside it ("make sure the rendered size
// makes sense").
const PREVIEW_WIDTH_PX = 1280;
const PREVIEW_HEIGHT_PX = (PREVIEW_WIDTH_PX * 9) / 16;

function IframeSlide({ src, alt }: { src: string; alt: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      setScale(entry.contentRect.width / PREVIEW_WIDTH_PX);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={containerRef} className="h-full w-full overflow-hidden">
      {/* pointer-events-none unconditionally, not just while dragging -- an
          iframe is its own separate document/browsing context, so pointer/
          touch events starting on top of it never reach this carousel's
          onPointerDown/onPointerMove at all (the iframe's content consumes
          them internally, a real cross-frame browser restriction, not
          something a dragging-state check can work around). Without this,
          a swipe gesture that happened to start over the embedded frame
          would silently do nothing ("make sure on mobile it is swipable"
          needs to hold for every slide, not just the ones that aren't an
          iframe) -- the tradeoff is this embedded preview is view-only,
          not click-through interactive, which is fine for a carousel
          showcase slide. */}
      <iframe
        src={src}
        title={alt}
        // scrolling="no" -- the embedded page can be taller than
        // PREVIEW_HEIGHT_PX, which otherwise shows its own scrollbar
        // inside the preview; this is a non-interactive (pointer-events-
        // none, see above) preview thumbnail, not somewhere a visitor is
        // meant to scroll around, so suppress it rather than let the
        // page's real scrollbar show up in miniature here. Deprecated
        // from the HTML spec but still honored by every major browser,
        // there's no non-deprecated CSS-only equivalent that reaches
        // into a cross-document iframe's own scrollbar.
        scrolling="no"
        loading="lazy"
        className="pointer-events-none origin-top-left border-0"
        style={{
          width: PREVIEW_WIDTH_PX,
          height: PREVIEW_HEIGHT_PX,
          transform: `scale(${scale})`,
        }}
      />
    </div>
  );
}

// Click-to-load gate for a video slide -- renders NO <video> element at all
// (not even preload="none", which still fetches enough of the file to
// determine duration/dimensions) until a real click, so a video slide
// costs nothing over the network until someone actually wants to watch it.
// Own component (not inline in the slide-rendering switch below) because it
// needs its own "has this been clicked" state, which must NOT be shared
// across different slides or reset by anything other than this slide
// itself unmounting.
function VideoPlayGate({ slide, onActivate }: { slide: CarouselSlide; onActivate: () => void }) {
  return (
    <button
      type="button"
      onClick={onActivate}
      aria-label={`Play video: ${slide.alt}`}
      className="group relative block h-full w-full select-none overflow-hidden focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-orange"
    >
      {/* Real poster image (a pre-extracted first frame, see
          Projects.tsx's media() calls) if the slide has one -- same
          cover/letterbox treatment as a photo slide, so a video without a
          poster yet doesn't look inconsistent with one that has it. Falls
          back to a flat panel, never to loading the video itself just to
          show a frame -- that would defeat click-to-load's whole point. */}
      {slide.poster ? (
        slide.fit === "cover" ? (
          <img
            src={slide.poster}
            alt=""
            loading="lazy"
            decoding="async"
            className="h-full w-full object-cover"
          />
        ) : (
          <LetterboxFrame
            backdrop={<img src={slide.poster} alt="" className="h-full w-full object-cover" />}
          >
            <img
              src={slide.poster}
              alt=""
              loading="lazy"
              decoding="async"
              className="max-h-full max-w-full object-contain"
            />
          </LetterboxFrame>
        )
      ) : (
        <div className="h-full w-full bg-bg-secondary" />
      )}
      {/* Dark scrim (strengthens on hover) -- a photo alone doesn't read as
          "click to play" the way a flat placeholder box did before it had
          a real thumbnail. */}
      <div
        aria-hidden
        className="absolute inset-0 bg-black/10 transition-colors group-hover:bg-black/25"
      />
      {/* Same translucent circular treatment as the carousel's own arrow
          buttons (ARROW_BUTTON_CLASS), sized up since this is the primary
          call to action for the slide, not a secondary nav control.
          Centered absolutely over the whole box (not the letterboxed
          image within it) -- dead-center of the thumbnail area is where a
          play button always goes, letterboxing or not. */}
      <span className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <span className="flex h-14 w-14 items-center justify-center rounded-full border border-[rgba(235,219,178,0.25)] bg-[rgba(40,40,40,0.55)] text-2xl leading-none text-fg-primary transition-colors group-hover:bg-[rgba(40,40,40,0.8)] group-hover:text-accent-aqua">
          {/* CSS triangle, not a glyph -- a play-triangle unicode character
              (e.g. U+25B6) renders with inconsistent optical centering
              across fonts/platforms; a border-triangle is pixel-exact
              everywhere. */}
          <span
            className="ml-1 block h-0 w-0 border-y-[10px] border-l-[16px] border-y-transparent border-l-current"
            aria-hidden
          />
        </span>
      </span>
    </button>
  );
}

function VideoSlide({ slide }: { slide: CarouselSlide }) {
  const [activated, setActivated] = useState(false);
  const activate = () => setActivated(true);

  if (!activated) {
    return <VideoPlayGate slide={slide} onActivate={activate} />;
  }

  return slide.fit === "cover" ? (
    <video
      src={slide.videoSrc}
      poster={slide.poster}
      controls
      autoPlay
      playsInline
      preload="metadata"
      className="h-full w-full select-none object-cover"
    >
      <track kind="captions" />
    </video>
  ) : (
    <LetterboxFrame
      backdrop={
        <video
          src={slide.videoSrc}
          muted
          loop
          autoPlay
          playsInline
          preload="metadata"
          className="h-full w-full object-cover"
        />
      }
    >
      <video
        src={slide.videoSrc}
        poster={slide.poster}
        controls
        autoPlay
        playsInline
        preload="metadata"
        className="max-h-full max-w-full select-none"
      >
        <track kind="captions" />
      </video>
    </LetterboxFrame>
  );
}

// A flat bg-bg-secondary letterbox behind a contained (non-cropped) photo
// or video reads as an empty gap, not a deliberate frame ("doesn't look
// professional"). This gives it a real backdrop instead: the same media,
// blown up and blurred to fill the box completely, sitting behind the
// crisp, fully-visible foreground copy -- the same "blurred album art
// backdrop" treatment music apps use for non-square covers. `backdrop` is
// itself an <img>/<video> (not a CSS background-image), so it works for
// both media kinds with one component.
function LetterboxFrame({
  backdrop,
  children,
}: {
  backdrop: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="relative h-full w-full overflow-hidden bg-bg-secondary">
      <div
        aria-hidden
        className="absolute inset-0 scale-125 opacity-40 blur-2xl brightness-75"
      >
        {backdrop}
      </div>
      <div className="relative flex h-full w-full items-center justify-center">{children}</div>
    </div>
  );
}

export interface CarouselSlide {
  alt: string;
  // Optional -- a slide without any of src/iframeSrc/videoSrc renders a
  // labeled placeholder panel instead of a broken <img>. Swap in a real
  // one of these and the same slide renders the actual media with no
  // other changes needed.
  src?: string;
  // Renders a live <iframe> instead of a static image -- used for the
  // logand.app project entry itself, which can just embed the real
  // running site rather than a screenshot of it.
  iframeSrc?: string;
  // Renders a real <video controls> element -- for local demo/timelapse
  // clips (see Projects.tsx's media() helper). Checked after iframeSrc,
  // before src, since a slide should never define more than one of these.
  videoSrc?: string;
  // A real still image shown (as the video's own poster attribute, and as
  // the click-to-load play-gate's thumbnail before that) instead of a
  // flat placeholder box -- only meaningful alongside videoSrc. Optional:
  // a video with no poster still gets a working play gate, just with a
  // plain background instead of a real thumbnail.
  poster?: string;
  // Renders a normal, INTERACTIVE responsive iframe (pointer events left
  // enabled, no fixed-desktop-width scale hack) -- for third-party embeds
  // that are natively responsive and meant to be played, like a YouTube
  // "/embed/<id>" URL. Distinct from `iframeSrc`, which is specifically
  // the logand.app self-preview hack (fixed 1280px width scaled down,
  // pointer-events-none) -- reusing it here would both mis-size a
  // YouTube embed (it's already responsive, doesn't want the 16:9-at-
  // 1280px-then-shrink treatment) and make the video unplayable (its
  // pointer-events-none is load-bearing for that hack's own drag-to-swipe
  // requirement, but this slide type needs real Play-button clicks to
  // reach the iframe instead).
  embedSrc?: string;
  // "contain" (default) always shows the whole photo, letterboxed against
  // the box's own background if its aspect ratio isn't 16:9 -- cropping
  // to fill (object-cover) was cutting real content out of most of these
  // source photos, which weren't shot/exported at 16:9 to begin with.
  // "cover" opts back into fill-and-crop for a slide where that's
  // actually fine (a busy background photo with no important edges).
  fit?: "cover" | "contain";
  // An arbitrary React element for a slide (a <TerminalWindow>, say) --
  // for real, live-rendered content instead of a static screenshot image.
  // Checked first: an element slide should never also define src/
  // iframeSrc/videoSrc/embedSrc.
  element?: React.ReactNode;
}

// Below this horizontal drag distance (px), a touch/pointer gesture is
// treated as "didn't mean to swipe" and the track snaps back to the
// current slide instead of advancing -- otherwise an incidental sideways
// thumb movement while scrolling the page vertically would flip slides.
const SWIPE_THRESHOLD_PX = 50;

/**
 * A small, dependency-free image carousel styled to match the rest of the
 * site (Gruvbox border/background tokens, BUTTON_CLASS's tap targets) --
 * "a professional carousel of images in a style that fits the site."
 *
 * Slides sit in a single flex row (a "track") that's translated
 * horizontally by -index*100% and CSS-transitioned, rather than swapping
 * which slide is rendered outright -- that's what makes moving between
 * slides an actual smooth slide animation instead of an instant cut ("I
 * want the carousel animation to be smooth"). Skips the transition
 * (snaps instantly) under prefers-reduced-motion, same convention as
 * every other animation in ascii/.
 *
 * Touch/pointer dragging on the track ("make sure on mobile it is
 * swipable") advances or returns to the previous slide past
 * SWIPE_THRESHOLD_PX of horizontal movement, snapping back otherwise;
 * `touch-action: pan-y` lets an incidental vertical page scroll continue
 * to work over the carousel while still letting this capture horizontal
 * drags itself.
 */
export function ImageCarousel({ slides }: { slides: CarouselSlide[] }) {
  const [index, setIndex] = useState(0);
  const [dragOffsetPx, setDragOffsetPx] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const reducedMotionRef = useRef(false);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const dragStartRef = useRef<{ x: number; width: number } | null>(null);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    reducedMotionRef.current = mq.matches;
    const onChange = () => {
      reducedMotionRef.current = mq.matches;
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  if (slides.length === 0) return null;

  function goTo(i: number) {
    setIndex(((i % slides.length) + slides.length) % slides.length);
  }

  // Real media (img/video/iframe) only mounts for the current slide and
  // its immediate neighbors -- everything else renders as an empty
  // placeholder box instead. Without this, the track's translate-based
  // layout means EVERY slide of EVERY project's carousel is mounted at
  // once (just visually off to the side), so autoplaying backdrop videos
  // and iframes (the live logand.app preview, YouTube embeds) all start
  // loading/playing simultaneously the instant the Projects page renders,
  // regardless of which project or slide is actually visible. Neighbors
  // (not just the current slide) stay mounted so a swipe/arrow-click mid-
  // transition doesn't reveal an empty box before the new slide finishes
  // sliding in.
  function isNearCurrent(i: number): boolean {
    const len = slides.length;
    const dist = Math.min(Math.abs(i - index), len - Math.abs(i - index));
    return dist <= 1;
  }

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    if (slides.length <= 1) return;
    // A pointerdown that started on a real interactive control inside a
    // slide (the video play-gate button, most notably) must NOT be
    // captured for dragging -- setPointerCapture below redirects every
    // subsequent pointer event to this track element regardless of where
    // the pointer actually is, which silently ate the button's own click
    // (video never loaded on click; it just looked like nothing happened).
    if ((e.target as HTMLElement).closest("button")) return;
    dragStartRef.current = { x: e.clientX, width: trackRef.current?.clientWidth || 1 };
    setIsDragging(true);
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (!dragStartRef.current) return;
    setDragOffsetPx(e.clientX - dragStartRef.current.x);
  }

  function endDrag() {
    if (!dragStartRef.current) return;
    if (dragOffsetPx <= -SWIPE_THRESHOLD_PX) goTo(index + 1);
    else if (dragOffsetPx >= SWIPE_THRESHOLD_PX) goTo(index - 1);
    dragStartRef.current = null;
    setIsDragging(false);
    setDragOffsetPx(0);
  }

  const dragPercent = dragStartRef.current
    ? (dragOffsetPx / dragStartRef.current.width) * 100
    : 0;

  return (
    // Outer wrapper spans the card's FULL width, not just the (now
    // height-capped, often narrower) image box -- the buttons anchor to
    // THIS element's edges, not the image's, so on a short viewport where
    // the aspect-video box shrinks narrower than the card, they land in
    // the real empty space beside it instead of on top of the image
    // itself ("now that there is space on the left and right, put the
    // buttons there and not on the carousel item").
    <div className="relative w-full">
      {/* aspect-video + a height cap (max-h-[38dvh]), NOT a width-driven
          aspect-video (w-full) -- the old width-driven version fixed this
          box's height at 16:9 of the card's full width (~378px at the
          card's max-w-2xl), which alone left almost no room for the
          description on a shorter viewport ("the bottom text area is
          ridiculously small, and the bottom border is cut"). Capping
          height and letting the browser derive width from it
          (aspect-ratio's normal sizing algorithm, given both an explicit
          height and a max-width) means this box shrinks on a short
          viewport instead of always claiming the same fixed height
          regardless of how much is actually available; max-w-full keeps
          it from exceeding the card's own width on a tall/wide viewport
          where 38dvh would otherwise compute wider than that. */}
      {/* min-h-[110px] -- a floor under the height cap above. Without it,
          a short-AND-narrow viewport could shrink this box below the
          arrow buttons' own height (h-9, 36px, sitting bottom-2/8px
          inside it on mobile -- see ARROW_BUTTON_CLASS's doc comment),
          which pushed them past the image's actual bottom edge into the
          description text below it ("now the arrows overlap the text in
          short viewport"). aspect-ratio + a min-height together just means
          the box stops shrinking at this floor rather than breaking the
          16:9 ratio in the other direction (getting wider than its
          max-width to keep the ratio) -- a slightly-off ratio at extreme
          sizes is a fine tradeoff for the buttons always actually fitting
          inside it. */}
      <div className="relative mx-auto aspect-video max-h-[32dvh] min-h-[110px] w-auto max-w-full overflow-hidden rounded border border-border bg-bg-secondary">
        <div
          ref={trackRef}
          className="flex h-full w-full touch-pan-y"
          style={{
            transform: `translateX(calc(${-index * 100}% + ${dragPercent}%))`,
            transition:
              isDragging || reducedMotionRef.current ? "none" : "transform 300ms ease-out",
          }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
        >
          {slides.map((slide, i) => (
            <div key={slide.alt} className="h-full w-full flex-shrink-0">
              {!isNearCurrent(i) ? (
                // Not near the current slide -- render an empty box (same
                // size/background as a real slide, no media at all) rather
                // than paying for a video/iframe/image load that's nowhere
                // near visible yet. Swapped for the real content once a
                // swipe/arrow-click brings this slide within one step of
                // current (see isNearCurrent's own doc comment).
                <div className="h-full w-full bg-bg-secondary" />
              ) : slide.element ? (
                <div className="h-full w-full overflow-hidden">{slide.element}</div>
              ) : slide.iframeSrc ? (
                <IframeSlide src={slide.iframeSrc} alt={slide.alt} />
              ) : slide.embedSrc ? (
                <iframe
                  src={slide.embedSrc}
                  title={slide.alt}
                  loading="lazy"
                  className="h-full w-full border-0"
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                  allowFullScreen
                />
              ) : slide.videoSrc ? (
                <VideoSlide slide={slide} />
              ) : slide.src ? (
                slide.fit === "cover" ? (
                  <img
                    src={slide.src}
                    alt={slide.alt}
                    draggable={false}
                    loading="lazy"
                    decoding="async"
                    className="h-full w-full select-none object-cover"
                  />
                ) : (
                  <LetterboxFrame
                    backdrop={
                      <img
                        src={slide.src}
                        alt=""
                        loading="lazy"
                        decoding="async"
                        className="h-full w-full object-cover"
                      />
                    }
                  >
                    <img
                      src={slide.src}
                      alt={slide.alt}
                      draggable={false}
                      loading="lazy"
                      decoding="async"
                      className="max-h-full max-w-full select-none object-contain"
                    />
                  </LetterboxFrame>
                )
              ) : (
                // Placeholder panel -- see CarouselSlide's doc comment. No
                // aspect-video here -- the track's OWN aspect-video already
                // gives this flex child a real height via the default
                // align-items:stretch, a second aspect-ratio on top of that
                // would fight it.
                <div className="flex h-full w-full select-none items-center justify-center px-4 text-center text-sm text-fg-muted">
                  {slide.alt}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      {slides.length > 1 && (
        <>
          <button
            type="button"
            aria-label="Previous image"
            onClick={() => goTo(index - 1)}
            className={`${ARROW_BUTTON_CLASS} bottom-2 left-2 sm:bottom-auto sm:left-0 sm:top-1/2 sm:-translate-y-1/2`}
          >
            {"<"}
          </button>
          <button
            type="button"
            aria-label="Next image"
            onClick={() => goTo(index + 1)}
            className={`${ARROW_BUTTON_CLASS} bottom-2 right-2 sm:bottom-auto sm:right-0 sm:top-1/2 sm:-translate-y-1/2`}
          >
            {">"}
          </button>
        </>
      )}
    </div>
  );
}
