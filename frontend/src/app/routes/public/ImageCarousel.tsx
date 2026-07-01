import { useEffect, useRef, useState } from "react";

// Circular, translucent overlay buttons -- not BUTTON_CLASS (a boxy, opaque
// tap target meant for real nav/form buttons) -- sitting directly on top of
// the image itself is what makes this read as an actual carousel control
// rather than a form button that happens to be positioned over a picture
// ("the buttons are a little ugly"). Same glass-panel-style translucency as
// the rest of the site rather than a one-off, without pulling in the shared
// class (which assumes a full border box + backdrop-blur meant for a
// larger panel, not a small round hit target).
const ARROW_BUTTON_CLASS =
  "absolute top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full border border-[rgba(235,219,178,0.25)] bg-[rgba(40,40,40,0.55)] text-lg leading-none text-fg-primary transition-colors hover:bg-[rgba(40,40,40,0.8)] hover:text-accent-aqua focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-orange";

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

export interface CarouselSlide {
  alt: string;
  // Optional -- real project screenshots aren't provided yet (see
  // Projects.tsx's TODO), so a slide without one renders a labeled
  // placeholder panel instead of a broken <img>. Swap in a real `src` and
  // the same slide renders the actual image with no other changes needed.
  src?: string;
  // Renders a live <iframe> instead of a static image -- used for the
  // logand.app project entry itself, which can just embed the real
  // running site rather than a screenshot of it.
  iframeSrc?: string;
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

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    if (slides.length <= 1) return;
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
    <div className="relative w-full overflow-hidden rounded border border-border bg-bg-secondary">
      <div
        ref={trackRef}
        className="flex aspect-video w-full touch-pan-y"
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
        {slides.map((slide) => (
          <div key={slide.alt} className="h-full w-full flex-shrink-0">
            {slide.iframeSrc ? (
              <IframeSlide src={slide.iframeSrc} alt={slide.alt} />
            ) : slide.src ? (
              <img
                src={slide.src}
                alt={slide.alt}
                draggable={false}
                className="h-full w-full select-none object-cover"
              />
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
      {slides.length > 1 && (
        <>
          <button
            type="button"
            aria-label="Previous image"
            onClick={() => goTo(index - 1)}
            className={`${ARROW_BUTTON_CLASS} left-2`}
          >
            {"<"}
          </button>
          <button
            type="button"
            aria-label="Next image"
            onClick={() => goTo(index + 1)}
            className={`${ARROW_BUTTON_CLASS} right-2`}
          >
            {">"}
          </button>
        </>
      )}
    </div>
  );
}
