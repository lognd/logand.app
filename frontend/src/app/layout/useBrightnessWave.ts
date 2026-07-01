import { useEffect, type RefObject } from "react";

// How fast the brightness ripple expands outward from its origin, and how
// long each individual element's own brightness pulse lasts once it's hit.
// Slowed down from 2.6 px/ms / 650ms -- "the ripple is a little too fast
// and needs to be a little less subtle... slowing it down will help with
// that" (a slower expansion also gives each element's own pulse more time
// to actually read before the next one starts, which is most of what made
// it feel more noticeable without changing the brightness peak itself).
const WAVE_SPEED_PX_PER_MS = 1.4;
const PULSE_DURATION_MS = 900;
// Elements marked with this attribute (headings, paragraphs, links) are
// what the wave actually brightens -- not every descendant, so decorative
// wrappers/containers don't also get a filter applied for no visual
// reason.
const WAVE_SELECTOR = "[data-wave-text]";

/**
 * Makes marked text within `containerRef` brighten in an outward-expanding
 * wave, lightly, originating from wherever the user clicks anywhere on the
 * page, and once automatically on mount (originating from the content's
 * own center) -- per explicit feedback ("the text in the content should
 * become brighter in a wave lightly originating from the point that you
 * click and on first load"). Skipped entirely under
 * prefers-reduced-motion, same convention as GlitchText/SpinningShape.
 */
export function useBrightnessWave(containerRef: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    function pulseFrom(x: number, y: number) {
      const elements = container!.querySelectorAll<HTMLElement>(WAVE_SELECTOR);
      for (const el of elements) {
        const rect = el.getBoundingClientRect();
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        const delay = Math.hypot(cx - x, cy - y) / WAVE_SPEED_PX_PER_MS;
        // Restarting a CSS animation that's already applied requires
        // clearing it and forcing a reflow first -- just re-setting the
        // same animation/delay values is a no-op as far as the browser is
        // concerned, so a second click before the first pulse finishes
        // would otherwise not visibly restart it.
        el.style.animation = "none";
        void el.offsetWidth;
        el.style.animationDelay = `${delay}ms`;
        el.style.animation = `wave-brighten ${PULSE_DURATION_MS}ms ease-out`;
      }
    }

    // First-load wave, originating from the content area's own center
    // (there's no click yet to originate from).
    const rect = container.getBoundingClientRect();
    pulseFrom(rect.left + rect.width / 2, rect.top + rect.height / 2);

    function onClick(e: MouseEvent) {
      pulseFrom(e.clientX, e.clientY);
    }
    // window, not the container -- a click anywhere on the page (nav,
    // background, footer) should still ripple the content text, not just
    // clicks landing inside the content area itself.
    window.addEventListener("click", onClick);
    return () => window.removeEventListener("click", onClick);
  }, [containerRef]);
}
